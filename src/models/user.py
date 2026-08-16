import uuid
from datetime import datetime, timezone
import uuid6
from .extensions import db

def generate_uuid7():
    """Generates a UUIDv7 for time-ordered database primary keys."""
    return uuid6.uuid7()

def get_utc_now():
    """Returns the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=generate_uuid7)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    is_verified = db.Column(db.Boolean, nullable=False, default=False)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    preferred_language = db.Column(db.String(10), nullable=False, default='de')
    
    # Track the moment all active sessions must have been created AFTER
    # Defaults to creation time. Changed on password change to invalidate old sessions.
    sessions_valid_after = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now)
    
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now, onupdate=get_utc_now)

    # Relationships
    favorite_teams = db.relationship('FavoriteTeam', backref='user', cascade='all, delete-orphan', lazy='select')
    favorite_players = db.relationship('FavoritePlayer', backref='user', cascade='all, delete-orphan', lazy='select')

    @classmethod
    def normalize_email(cls, email: str) -> str:
        """
        Consistently normalizes emails by stripping whitespace and lowercasing.
        """
        if email:
            return email.strip().lower()
        return email
        
    def set_password(self, raw_password: str):
        from argon2 import PasswordHasher
        ph = PasswordHasher()
        self.password_hash = ph.hash(raw_password)
        self.invalidate_all_sessions()
        
    def check_password(self, raw_password: str) -> bool:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError
        ph = PasswordHasher()
        try:
            return ph.verify(self.password_hash, raw_password)
        except VerifyMismatchError:
            return False
            
    def invalidate_all_sessions(self):
        """Invalidates all currently active sessions for this user by advancing the watermark."""
        self.sessions_valid_after = get_utc_now()

    def __repr__(self):
        return f"<User {self.id} (email={self.email})>"
