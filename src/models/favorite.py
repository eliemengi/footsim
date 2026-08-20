from .extensions import db
from .user import get_utc_now

#: Erlaubte Herkunft einer Team-ID. FootSim spricht zwei Datenquellen
#: mit vollstaendig getrennten ID-Raeumen an (football-data.org fuer
#: Tabellen/Spielplan, API-Football fuer Live und Teamprofile). Ohne
#: festgehaltene Herkunft ist eine gespeicherte Zahl nicht deutbar -
#: und Raten ist im Projekt bewusst nicht zulaessig (vgl.
#: src/data/uefa_coefficients.py).
FAVORITE_TEAM_SOURCES = ('football-data', 'apisports')

#: Namensraum, in dem ein Lieblingsteam heute gespeichert wird.
#: API-Football, weil Teamprofil (src/api/team_detail.py) und Live
#: (src/api/live_api.py) bereits ausschliesslich darin arbeiten - nur so
#: kann dasselbe Team angezeigt, angeklickt UND in Live erkannt werden.
CANONICAL_FAVORITE_TEAM_SOURCE = 'apisports'

#: Frueher wurde die Auswahl aus /api/standings (football-data) befuellt.
#: Solche Zeilen bleiben erhalten, gelten aber als nicht aufloesbar,
#: siehe FavoriteTeam.is_resolvable().
LEGACY_FAVORITE_TEAM_SOURCE = 'football-data'

DEFAULT_FAVORITE_TEAM_SOURCE = CANONICAL_FAVORITE_TEAM_SOURCE


class FavoriteTeam(db.Model):
    __tablename__ = 'favorite_teams'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Uuid(as_uuid=True), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    team_id = db.Column(db.Integer, nullable=False)
    source = db.Column(
        db.String(32),
        nullable=False,
        default=DEFAULT_FAVORITE_TEAM_SOURCE,
        server_default=DEFAULT_FAVORITE_TEAM_SOURCE,
    )
    # Name und Wappen werden bei der Auswahl mitgeschrieben. Die Auswahl
    # hat beide Werte ohnehin in der Hand - sie spaeter nachzuschlagen
    # waere ein zusaetzlicher Provider-Request nur fuer eine Kopfzeile.
    # Nullable, weil Altbestand aus der Zeit vor dieser Spalte existiert.
    team_name = db.Column(db.String(120), nullable=True)
    crest_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=get_utc_now)

    def is_resolvable(self):
        """
        True, wenn die gespeicherte ID im heute verwendeten Namensraum
        gedeutet werden darf.

        Altbestand aus der football-data-Zeit bleibt bewusst erhalten,
        wird aber nicht uebersetzt: dieselbe Zahl bezeichnet bei beiden
        Anbietern verschiedene Vereine. Lieber gar keine Anzeige als die
        eines fremden Klubs (vgl. src/data/uefa_coefficients.py).
        """
        return self.source == CANONICAL_FAVORITE_TEAM_SOURCE

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
