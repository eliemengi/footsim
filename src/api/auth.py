from flask import Blueprint, jsonify, request, session, current_app, g, redirect
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import re
from src.models import db, User
from src.models.extensions import limiter
from src.utils.mail import send_verification_email, send_password_reset_email

auth_bp = Blueprint("auth", __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])

def is_valid_password(password: str) -> bool:
    """Basic password policy: 8-128 chars."""
    if not password or not isinstance(password, str):
        return False
    return 8 <= len(password) <= 128

def validate_email_format(email: str) -> bool:
    """Basic sanity check for email."""
    if not email or not isinstance(email, str):
        return False
    # Simple regex for structure check, database unique constraint is authoritative.
    return bool(re.match(r"[^@]+@[^@]+\.[^@]+", email))

@auth_bp.before_request
def load_current_user():
    user_id = session.get("user_id")
    sessions_valid_after_ts = session.get("created_at")
    
    if user_id is None:
        g.user = None
        return
        
    user = db.session.get(User, user_id)
    
    if user is None:
        session.clear()
        g.user = None
        return
        
    # Check session fixation / invalidation
    if sessions_valid_after_ts is None or (user.sessions_valid_after and user.sessions_valid_after.timestamp() > sessions_valid_after_ts):
        session.clear()
        g.user = None
        return
        
    g.user = user

@auth_bp.route("/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400
        
    email = data.get("email", "")
    password = data.get("password", "")
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    
    if not validate_email_format(email):
        return jsonify({"error": "Invalid email format"}), 400
        
    if not is_valid_password(password):
        return jsonify({"error": "Password must be between 8 and 128 characters"}), 400
        
    if not first_name or not last_name:
        return jsonify({"error": "First name and last name are required"}), 400
        
    normalized_email = User.normalize_email(email)
    
    try:
        user = User(
            email=normalized_email,
            first_name=first_name,
            last_name=last_name
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Email is already registered"}), 409
        
    # Send verification email
    s = get_serializer()
    token = s.dumps(str(user.id), salt='email-verify')
    email_sent = send_verification_email(user.email, token)
    
    if email_sent:
        return jsonify({"message": "Registration successful. Please check your email to verify your account.", "status": "success"}), 201
    else:
        return jsonify({"message": "Account created, but verification email could not be sent.", "status": "email_failed"}), 201

@auth_bp.route("/login", methods=["POST"])
@limiter.limit("20 per hour")
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400
        
    email = User.normalize_email(data.get("email", ""))
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
        
    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    
    if user is None or not user.check_password(password):
        # Generic error message to prevent enumeration
        return jsonify({"error": "Invalid email or password"}), 401
        
    # Prevent session fixation by clearing existing session data
    session.clear()
    session["user_id"] = str(user.id)
    session.permanent = True
    
    import time
    session["created_at"] = time.time()
    
    return jsonify({
        "message": "Login successful",
        "user": {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_verified": user.is_verified
        }
    })

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully"})

@auth_bp.route("/me", methods=["GET"])
def me():
    if getattr(g, "user", None):
        return jsonify({
            "authenticated": True,
            "user": {
                "first_name": g.user.first_name,
                "last_name": g.user.last_name,
                "email": g.user.email,
                "is_verified": g.user.is_verified
            }
        })
    return jsonify({"authenticated": False})

@auth_bp.route("/verify", methods=["GET"])
def verify():
    token = request.args.get("token")
    base_url = current_app.config.get("BASE_URL", "http://127.0.0.1:5000")
    if not token:
        return redirect(f"{base_url}/?verify_error=invalid")
        
    s = get_serializer()
    try:
        user_id_str = s.loads(token, salt='email-verify', max_age=86400) # 24 hours
    except SignatureExpired:
        return redirect(f"{base_url}/?verify_error=expired")
    except BadSignature:
        return redirect(f"{base_url}/?verify_error=invalid")
        
    user = db.session.get(User, user_id_str)
    if not user:
        return redirect(f"{base_url}/?verify_error=invalid")
        
    if user.is_verified:
        return redirect(f"{base_url}/?verified=already")
        
    user.is_verified = True
    from src.models.user import get_utc_now
    user.verified_at = get_utc_now()
    db.session.commit()
    
    return redirect(f"{base_url}/?verified=1")

@auth_bp.route("/resend-verification", methods=["POST"])
@limiter.limit("5 per hour")
def resend_verification():
    data = request.get_json()
    email = User.normalize_email(data.get("email", "")) if data else ""
    
    if not email:
        return jsonify({"message": "If your email is registered and unverified, a new verification link has been sent."})
        
    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if user and not user.is_verified:
        s = get_serializer()
        token = s.dumps(str(user.id), salt='email-verify')
        email_sent = send_verification_email(user.email, token)
        if not email_sent:
            return jsonify({"error": "Could not send verification email at this time. Please try again later.", "status": "email_failed"}), 503
            
    return jsonify({"message": "If your email is registered and unverified, a new verification link has been sent."})

@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    data = request.get_json()
    email = User.normalize_email(data.get("email", "")) if data else ""
    
    # Generic response
    msg = "If an account exists for this email, we sent password reset instructions."
    
    if not email:
        return jsonify({"message": msg})
        
    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if user:
        s = get_serializer()
        token = s.dumps(str(user.id), salt='password-reset')
        send_password_reset_email(user.email, token)
        
    return jsonify({"message": msg})

@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400
        
    token = data.get("token")
    new_password = data.get("new_password")
    
    if not token or not new_password:
        return jsonify({"error": "Token and new password are required"}), 400
        
    if not is_valid_password(new_password):
        return jsonify({"error": "Password must be between 8 and 128 characters"}), 400
        
    s = get_serializer()
    try:
        user_id_str = s.loads(token, salt='password-reset', max_age=3600) # 1 hour
    except SignatureExpired:
        return jsonify({"error": "Password reset link has expired."}), 400
    except BadSignature:
        return jsonify({"error": "Invalid password reset link."}), 400
        
    user = db.session.get(User, user_id_str)
    if not user:
        return jsonify({"error": "User not found."}), 404
        
    user.set_password(new_password) # This also advances sessions_valid_after
    db.session.commit()
    
    return jsonify({"message": "Password reset successfully. You can now log in."})

@auth_bp.route("/change-password", methods=["POST"])
def change_password():
    if not getattr(g, "user", None):
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    
    if not current_password or not new_password:
        return jsonify({"error": "Current and new password are required"}), 400
        
    if not is_valid_password(new_password):
        return jsonify({"error": "New password must be between 8 and 128 characters"}), 400
        
    if not g.user.check_password(current_password):
        return jsonify({"error": "Incorrect current password"}), 401
        
    g.user.set_password(new_password)
    db.session.commit()
    
    return jsonify({"message": "Password changed successfully"})

@auth_bp.route("/delete-account", methods=["POST"])
def delete_account():
    if not getattr(g, "user", None):
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400
        
    current_password = data.get("current_password")
    
    if not current_password:
        return jsonify({"error": "Current password is required to delete account"}), 400
        
    if not g.user.check_password(current_password):
        return jsonify({"error": "Incorrect password"}), 401
        
    db.session.delete(g.user)
    db.session.commit()
    session.clear()
    
    return jsonify({"message": "Account deleted successfully"})
