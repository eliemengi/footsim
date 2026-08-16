from .extensions import db
from .user import get_utc_now

class FavoriteTeam(db.Model):
    __tablename__ = 'favorite_teams'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Uuid(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    team_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'team_id', name='uq_user_favorite_team'),
    )

    def __repr__(self):
        return f"<FavoriteTeam user_id={self.user_id} team_id={self.team_id}>"


class FavoritePlayer(db.Model):
    __tablename__ = 'favorite_players'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Uuid(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    player_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'player_id', name='uq_user_favorite_player'),
    )

    def __repr__(self):
        return f"<FavoritePlayer user_id={self.user_id} player_id={self.player_id}>"
