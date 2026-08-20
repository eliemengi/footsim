"""Add auth tracking fields

Revision ID: 13bfa4eb853e
Revises: 5bbd7b62dcc3
Create Date: 2026-08-16 19:02:32.688858

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13bfa4eb853e'
down_revision = '5bbd7b62dcc3'
branch_labels = None
depends_on = None


def upgrade():
    """
    Fuegt die beiden Auth-Tracking-Spalten hinzu.

    WARUM NICHT DER AUTOGENERIERTE CODE
    -----------------------------------
    Alembic hatte hier urspruenglich

        add_column(Column('sessions_valid_after', DateTime(timezone=True),
                          nullable=False))

    erzeugt - mit dem Hinweis "please adjust!", der nie umgesetzt wurde.
    PostgreSQL lehnt ADD COLUMN ... NOT NULL ohne DEFAULT auf einer
    Tabelle mit Zeilen grundsaetzlich ab:

        column "sessions_valid_after" of relation "users"
        contains null values

    Auf einer LEEREN users-Tabelle laeuft dieselbe Anweisung fehlerfrei
    durch. Genau deshalb ist der Fehler lokal und in der Testsuite nie
    aufgefallen und haette erst auf der Produktionsdatenbank mit echten
    Accounts zugeschlagen.

    Der Ablauf unten ist auf beiden Zustaenden sicher:
      1. Spalte MIT server_default anlegen -> vorhandene Zeilen werden
         beim ALTER TABLE sofort gefuellt, NOT NULL ist erfuellbar.
      2. Fachlich sinnvoll nachziehen: die Sessions eines bestehenden
         Kontos gelten ab dessen Erstellung, nicht ab dem Migrationszeit-
         punkt. Ein mengenbasiertes UPDATE, keine Python-Schleife.
      3. server_default wieder entfernen, weil das Modell den Wert
         ausschliesslich in Python setzt (User.sessions_valid_after mit
         default=get_utc_now). Ohne Schritt 3 wuerde das Schema dauerhaft
         vom Modell abweichen und den Drift-Test brechen.

    Bereits migrierte Datenbanken fuehren diese Revision nicht erneut
    aus - fuer sie aendert die Korrektur nichts.
    """
    op.add_column(
        'users',
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'sessions_valid_after',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.execute(
        "UPDATE users "
        "SET sessions_valid_after = created_at "
        "WHERE created_at IS NOT NULL"
    )

    op.alter_column('users', 'sessions_valid_after', server_default=None)


def downgrade():
    op.drop_column('users', 'sessions_valid_after')
    op.drop_column('users', 'verified_at')
