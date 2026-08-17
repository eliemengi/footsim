import os
import requests
from flask import current_app

def _send_email(to_email: str, subject: str, html: str) -> bool:
    """Internal helper to send an email via Resend."""
    mock_env = os.environ.get("MAIL_MOCK")
    if mock_env is not None:
        mock_mail = str(mock_env).strip().lower() in {"true", "1", "yes", "on", "t"}
    else:
        # Default behavior: mock in development, real in production
        mock_mail = os.environ.get("FLASK_ENV") != "production"

    if mock_mail:
        print("="*60)
        print("MOCK EMAIL SERVICE")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(f"Content: {html}")
        print("="*60)
        return True

    resend_key = current_app.config.get("RESEND_API_KEY")
    if not resend_key:
        current_app.logger.warning("Email delivery skipped: RESEND_API_KEY is not configured.")
        return False
        
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "FootSim <noreply@footsim.de>")
    
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json"
            },
            json={
                "from": sender,
                "to": [to_email],
                "subject": subject,
                "html": html
            },
            timeout=10
        )
        response.raise_for_status()
        current_app.logger.info("Resend email accepted")
        return True
    except requests.RequestException as e:
        status_code = getattr(e.response, 'status_code', 'Network Error')
        error_msg = "No Resend error message available"
        if e.response is not None:
            try:
                err_json = e.response.json()
                if isinstance(err_json, dict) and "message" in err_json:
                    error_msg = err_json["message"]
            except ValueError:
                pass
                
        current_app.logger.error(f"Failed to send email via Resend (Status: {status_code}) - Details: {error_msg}")
        return False

def send_verification_email(to_email: str, token: str) -> bool:
    """
    Sends an email verification link.
    """
    base_url = current_app.config.get("BASE_URL", "http://127.0.0.1:5000")
    verify_url = f"{base_url}/api/auth/verify?token={token}"
    
    subject = "Bestätige deine E-Mail-Adresse für FootSim"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Willkommen bei FootSim!</h2>
        <p>Jemand hat einen Account mit dieser E-Mail-Adresse erstellt.</p>
        <p>Bitte bestätige deine Registrierung, indem du auf den folgenden Link klickst:</p>
        <div style="margin: 30px 0;">
            <a href="{verify_url}" style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">E-Mail bestätigen</a>
        </div>
        <p>Alternativ kannst du diesen Link kopieren:</p>
        <p><a href="{verify_url}">{verify_url}</a></p>
        <p style="color: #6c757d; font-size: 0.9em; margin-top: 40px;">
            Dieser Link ist für 24 Stunden gültig.<br>
            Falls du diesen Account nicht erstellt hast, kannst du diese E-Mail einfach ignorieren.
        </p>
    </div>
    """
    return _send_email(to_email, subject, html)

def send_password_reset_email(to_email: str, token: str) -> bool:
    """
    Sends a password reset link.
    """
    base_url = current_app.config.get("BASE_URL", "http://127.0.0.1:5000")
    reset_url = f"{base_url}/?reset_token={token}#reset"
    
    subject = "Passwort zurücksetzen (FootSim)"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>Passwort zurücksetzen</h2>
        <p>Wir haben eine Anfrage erhalten, dein Passwort bei FootSim zurückzusetzen.</p>
        <p>Klicke auf den folgenden Link, um ein neues Passwort zu vergeben:</p>
        <div style="margin: 30px 0;">
            <a href="{reset_url}" style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">Passwort zurücksetzen</a>
        </div>
        <p>Alternativ kannst du diesen Link kopieren:</p>
        <p><a href="{reset_url}">{reset_url}</a></p>
        <p style="color: #6c757d; font-size: 0.9em; margin-top: 40px;">
            Falls du kein neues Passwort angefordert hast, kannst du diese E-Mail einfach ignorieren. 
            Dein bestehendes Passwort bleibt weiterhin gültig.
        </p>
    </div>
    """
    return _send_email(to_email, subject, html)
