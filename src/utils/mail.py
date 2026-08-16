import os
from flask import current_app

def send_verification_email(to_email: str, token: str):
    """
    Sends an email verification link.
    In development, prints to the console.
    In production, would use SMTP or an API (e.g. Resend, SendGrid).
    """
    verify_url = f"http://127.0.0.1:5000/api/auth/verify?token={token}"
    
    if current_app.config.get("ENV") == "development" or os.environ.get("FLASK_ENV") != "production":
        print("="*60)
        print("MOCK EMAIL SERVICE")
        print(f"To: {to_email}")
        print(f"Subject: Verify your FootSim Account")
        print(f"Link: {verify_url}")
        print("="*60)
    else:
        # TODO: Implement production email provider here (e.g., Resend API)
        pass

def send_password_reset_email(to_email: str, token: str):
    """
    Sends a password reset link.
    """
    reset_url = f"http://127.0.0.1:5000/?reset_token={token}#reset"
    
    if current_app.config.get("ENV") == "development" or os.environ.get("FLASK_ENV") != "production":
        print("="*60)
        print("MOCK EMAIL SERVICE")
        print(f"To: {to_email}")
        print(f"Subject: Reset your FootSim Password")
        print(f"Link: {reset_url}")
        print("="*60)
    else:
        # TODO: Implement production email provider here
        pass
