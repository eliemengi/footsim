from flask import Blueprint, jsonify, request, session, current_app, g, redirect
from flask_wtf.csrf import generate_csrf
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import hmac
import re
from urllib.parse import urlparse
from src.models import db, User, FavoriteTeam
from src.models.favorite import FAVORITE_TEAM_SOURCES, DEFAULT_FAVORITE_TEAM_SOURCE
from src.models.extensions import limiter
from src.utils.mail import send_verification_email, send_password_reset_email

auth_bp = Blueprint("auth", __name__)

def get_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


#: Gueltigkeit eines Passwort-Reset-Links.
PASSWORD_RESET_MAX_AGE = 3600  # 1 Stunde

#: Formatversion der Reset-Nutzlast. Aeltere Tokens (Version 1 war ein
#: blosser User-ID-String) werden kontrolliert abgelehnt, statt sie
#: weiter zu akzeptieren - sie waeren genau die mehrfach verwendbaren.
PASSWORD_RESET_TOKEN_VERSION = 2


#: Hosts, von denen FootSim Vereinswappen bezieht. Verifiziert an den
#: tatsaechlichen Providerantworten:
#:   crests.football-data.org  -> /api/standings (Tabellen, Spielplan)
#:   media.api-sports.io       -> /api/personalization/teams, Live, Teamprofil
#: Andere Hosts sind kein Wappen, sondern eine fremde Ressource.
ALLOWED_CREST_HOSTS = frozenset({
    "crests.football-data.org",
    "media.api-sports.io",
})

MAX_CREST_URL_LENGTH = 500


def normalize_crest_url(raw):
    """
    Prueft eine vom Client gelieferte Wappen-URL.

    Rueckgabe: (url_oder_None, fehlertext_oder_None).

    Eine fehlende URL ist ausdruecklich erlaubt - ein Favorit ohne
    Wappen ist ein gueltiger Zustand. Abgelehnt wird nur eine
    ANGEGEBENE, aber unzulaessige URL; sie stillschweigend zu verwerfen
    wuerde einen manipulierten Client nicht erkennbar machen.
    """
    if raw is None:
        return None, None

    value = str(raw).strip()
    if not value:
        return None, None

    if len(value) > MAX_CREST_URL_LENGTH:
        return None, "Crest URL is too long"

    try:
        parsed = urlparse(value)
    except ValueError:
        return None, "Invalid crest URL"

    # Nur HTTPS: schliesst zugleich javascript:, data:, file: und ftp: aus.
    if parsed.scheme != "https":
        return None, "Crest URL must use https"

    # Userinfo (https://host@evil.example) verschleiert den echten Host.
    if parsed.username or parsed.password:
        return None, "Invalid crest URL"

    # Nicht-Standardports deuten auf einen umgeleiteten Host hin.
    try:
        if parsed.port not in (None, 443):
            return None, "Invalid crest URL"
    except ValueError:
        return None, "Invalid crest URL"

    # Exakter Hostvergleich. Kein endswith(): "evil-media.api-sports.io"
    # und "media.api-sports.io.attacker.test" wuerden sonst passieren.
    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_CREST_HOSTS:
        return None, "Crest URL host is not allowed"

    return value, None


def _password_reset_marker(user):
    """
    Stabiler Marker des sicherheitsrelevanten Benutzerzustands.

    sessions_valid_after aendert sich bei JEDEM erfolgreichen
    set_password() (siehe User.invalidate_all_sessions). Wird der Wert
    in die signierte Nutzlast aufgenommen, entwertet sich ein Reset-Link
    nach seiner Verwendung von selbst - ohne zusaetzliche Spalte, ohne
    Token-Datenbank und ohne Aufraeumjob.

    isoformat() haelt Zeitzone und Mikrosekunden fest; beides muss exakt
    uebereinstimmen, sonst gilt der Token als verbraucht.
    """
    valid_after = getattr(user, "sessions_valid_after", None)
    return valid_after.isoformat() if valid_after else ""


def build_password_reset_token(user):
    """Erzeugt einen an den aktuellen Kontozustand gebundenen Reset-Token."""
    return get_serializer().dumps(
        {
            "v": PASSWORD_RESET_TOKEN_VERSION,
            "uid": str(user.id),
            "svc": _password_reset_marker(user),
        },
        salt="password-reset",
    )


def load_password_reset_token(token):
    """
    Loest einen Reset-Token auf.

    Rueckgabe: (user, None) bei Erfolg, sonst (None, fehlerschluessel).
    Die Fehlerschluessel sind bewusst grob - der Aufrufer gibt nach
    aussen eine generische Meldung, damit weder Kontoexistenz noch der
    Grund der Ablehnung erkennbar wird.
    """
    try:
        payload = get_serializer().loads(
            token, salt="password-reset", max_age=PASSWORD_RESET_MAX_AGE
        )
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"

    # Version 1 war ein reiner String. Solche Tokens sind genau die
    # mehrfach verwendbaren und werden deshalb nicht mehr akzeptiert.
    if not isinstance(payload, dict) or payload.get("v") != PASSWORD_RESET_TOKEN_VERSION:
        return None, "invalid"

    user_id = payload.get("uid")
    if not user_id:
        return None, "invalid"

    user = db.session.get(User, user_id)
    if user is None:
        return None, "invalid"

    # Der entscheidende Vergleich: stimmt der Kontozustand noch mit dem
    # ueberein, fuer den der Link ausgestellt wurde?
    expected = _password_reset_marker(user)
    presented = payload.get("svc") or ""
    if not hmac.compare_digest(str(presented), str(expected)):
        return None, "used"

    return user, None

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

@auth_bp.route("/csrf-token", methods=["GET"])
def csrf_token():
    """
    Issues (or reuses) the current session's CSRF token.

    GET is not one of the methods Flask-WTF protects
    (WTF_CSRF_METHODS defaults to POST/PUT/PATCH/DELETE), so this route
    needs no exemption and enforces nothing on its own - it is read-only
    with respect to CSRF protection itself.

    generate_csrf() always signs a fresh, non-expired token, whether the
    caller's previous token was missing, invalid, or merely expired; it
    only creates a new underlying session secret if none exists yet.
    This lets the frontend recover from a CSRF rejection with a single
    extra request instead of a full page reload.
    """
    return jsonify({"csrf_token": generate_csrf()})


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
        # Fetch the user's first favorite team if it exists
        favorite_team = FavoriteTeam.query.filter_by(user_id=g.user.id).first()
        favorite_team_id = favorite_team.team_id if favorite_team else None
        
        # Altbestand aus dem football-data-Namensraum bleibt gespeichert,
        # wird aber nicht gedeutet: dieselbe Zahl bezeichnet bei beiden
        # Anbietern verschiedene Vereine. Das Frontend bekommt deshalb
        # ein ausdrueckliches Flag statt einer Zahl, mit der es nichts
        # Richtiges anfangen koennte.
        resolvable = bool(favorite_team and favorite_team.is_resolvable())

        return jsonify({
            "authenticated": True,
            "user": {
                "first_name": g.user.first_name,
                "last_name": g.user.last_name,
                "email": g.user.email,
                "is_verified": g.user.is_verified,
                "profile_onboarding_completed": getattr(g.user, "profile_onboarding_completed", False)
            },
            "favorite_team_id": favorite_team_id if resolvable else None,
            # Ohne die Herkunft ist die ID oben nicht deutbar, siehe
            # FAVORITE_TEAM_SOURCES. Das Frontend vergleicht sie nur mit
            # Team-IDs aus derselben Quelle.
            "favorite_team_source": favorite_team.source if favorite_team else None,
            "favorite_team_name": favorite_team.team_name if resolvable else None,
            "favorite_team_crest": favorite_team.crest_url if resolvable else None,
            # true = es existiert eine Auswahl, die im aktuellen
            # Namensraum nicht gedeutet werden kann. Die UI bittet dann
            # um eine einmalige Neuauswahl, statt etwas Falsches zu zeigen.
            "favorite_team_needs_reselect": bool(favorite_team) and not resolvable
        })
    return jsonify({"authenticated": False})

@auth_bp.route("/favorite", methods=["POST", "DELETE"])
@limiter.limit("20 per minute")
def favorite():
    if not getattr(g, "user", None):
        return jsonify({"error": "Unauthorized"}), 401
        
    if request.method == "DELETE":
        FavoriteTeam.query.filter_by(user_id=g.user.id).delete()
        db.session.commit()
        return jsonify({"message": "Favorite removed"})
        
    # POST
    data = request.get_json()
    if not data or "team_id" not in data:
        return jsonify({"error": "Missing team_id"}), 400
        
    team_id = data.get("team_id")

    # Very basic validation: it should be an integer
    try:
        team_id = int(team_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid team_id format"}), 400

    # Die Herkunft der ID wird mitgespeichert, nicht erraten. Ohne
    # Angabe gilt der kanonische Namensraum der Teamauswahl.
    source = data.get("source") or DEFAULT_FAVORITE_TEAM_SOURCE
    if source not in FAVORITE_TEAM_SOURCES:
        return jsonify({"error": "Unknown team_id source"}), 400

    # Name und Wappen kommen aus derselben Antwort wie die ID; sie
    # werden uebernommen, nicht nachgeschlagen. Laengen entsprechen den
    # Spalten, damit ein ueberlanger Wert nicht erst in der Datenbank
    # auffaellt.
    team_name = data.get("team_name")
    if team_name is not None:
        team_name = str(team_name).strip()[:120] or None

    # Die Wappen-URL landet spaeter als img.src im Browser. Ein
    # javascript:-Schema fuehrt dort zwar kein Skript aus, ein beliebiger
    # Fremdhost wuerde aber bei jedem Seitenaufbau die IP-Adresse des
    # Nutzers abfliessen lassen - ein selbst gewaehltes Trackingpixel.
    # Deshalb Allowlist statt blosser Laengenbegrenzung.
    crest_url, crest_error = normalize_crest_url(data.get("crest_url"))
    if crest_error is not None:
        return jsonify({"error": crest_error, "error_key": "account.invalidCrestUrl"}), 400

    # Remove existing favorites (V1 semantics: ONE favorite)
    FavoriteTeam.query.filter_by(user_id=g.user.id).delete()

    # Add new favorite
    new_fav = FavoriteTeam(
        user_id=g.user.id,
        team_id=team_id,
        source=source,
        team_name=team_name,
        crest_url=crest_url,
    )
    db.session.add(new_fav)
    g.user.profile_onboarding_completed = True
    db.session.commit()

    return jsonify({"message": "Favorite updated", "team_id": team_id, "source": source})

@auth_bp.route("/favorite/skip", methods=["POST"])
@limiter.limit("20 per minute")
def favorite_skip():
    if not getattr(g, "user", None):
        return jsonify({"error": "Unauthorized"}), 401
        
    g.user.profile_onboarding_completed = True
    db.session.commit()
    return jsonify({"message": "Account onboarding skipped"})

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
        token = build_password_reset_token(user)
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
        
    user, failure = load_password_reset_token(token)

    if failure == "expired":
        return jsonify({
            "error": "Password reset link has expired.",
            "error_key": "auth.resetExpired",
        }), 400

    if failure is not None:
        # "invalid" und "used" werden bewusst NICHT unterschieden: sonst
        # verriete die Antwort, ob ein Link echt war und bereits benutzt
        # wurde. Auch ein unbekannter Nutzer landet hier - damit gibt es
        # keine 404-basierte Kontoauskunft mehr.
        return jsonify({
            "error": "Invalid password reset link.",
            "error_key": "auth.resetInvalid",
        }), 400

    # set_password() setzt sessions_valid_after neu. Damit werden in
    # derselben Sekunde ALLE offenen Sessions und ALLE noch gueltigen
    # Reset-Links dieses Kontos ungueltig - auch dieser hier.
    user.set_password(new_password)
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
