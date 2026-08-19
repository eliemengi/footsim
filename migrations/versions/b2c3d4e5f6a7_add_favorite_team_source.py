"""Add favorite_teams.source

FootSim spricht zwei Datenquellen mit vollstaendig getrennten
Team-ID-Raeumen an (football-data.org und API-Football). Eine
gespeicherte Team-ID ohne Herkunft ist damit nicht deutbar.

Die Spalte ist rueckwaertsvertraeglich: bestehende Zeilen stammen
ausnahmslos aus der bisherigen Auswahl, deren IDs football-data.org
sind - genau der server_default.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('favorite_teams', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'source',
            sa.String(length=32),
            server_default='football-data',
            nullable=False,
        ))


def downgrade():
    with op.batch_alter_table('favorite_teams', schema=None) as batch_op:
        batch_op.drop_column('source')
