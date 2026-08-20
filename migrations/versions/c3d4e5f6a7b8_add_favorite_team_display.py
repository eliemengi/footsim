"""Add favorite_teams.team_name and .crest_url

Name und Wappen des Lieblingsteams werden bei der Auswahl
mitgeschrieben. Beide Werte liegen dort ohnehin vor; sie spaeter
nachzuschlagen waere ein zusaetzlicher Provider-Request nur fuer eine
Kopfzeile.

Beide Spalten sind nullable: Zeilen aus der Zeit vor dieser Revision
haben keinen Namen und kein Wappen. Sie werden NICHT befuellt - ihr
Altbestand stammt aus einem anderen ID-Namensraum (football-data) und
laesst sich nicht ohne Raten uebersetzen. Sie gelten stattdessen als
nicht aufloesbar (FavoriteTeam.is_resolvable) und der Nutzer waehlt
sein Team einmal neu.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('favorite_teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column('team_name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('crest_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('favorite_teams', schema=None) as batch_op:
        batch_op.drop_column('crest_url')
        batch_op.drop_column('team_name')
