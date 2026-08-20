"""
Der Upgrade-Pfad mit BESTEHENDEN Daten.

Warum diese Datei existiert
---------------------------
tests/test_migration_drift.py prueft, ob das Endschema zum Modell passt.
Das ist etwas anderes als die Frage, ob man dort ueberhaupt HINKOMMT,
wenn die Datenbank bereits Nutzer enthaelt.

Genau diese Luecke hatte die Migration 13bfa4eb853e:

    add_column(Column('sessions_valid_after', ..., nullable=False))

Auf einer leeren users-Tabelle laeuft das durch - und jede bisherige
Testeinrichtung migriert auf Leerstand. Auf einer Tabelle mit Zeilen
lehnt PostgreSQL es ab. Der Fehler war damit lokal und in CI unsichtbar
und haette ausschliesslich die Produktionsdatenbank getroffen.

Die Tests hier migrieren deshalb schrittweise und setzen zwischendurch
echte Zeilen ein, statt den ganzen Weg auf einer leeren Datenbank zu
gehen.

Sicherheit
----------
Ausschliesslich gegen eine ausdrueckliche Testdatenbank. Sieht die
DATABASE_URL nach Produktion aus, bricht der Test hart ab statt zu
laufen - siehe _assert_is_test_database().
"""

import os
import uuid

import pytest
from sqlalchemy import text

# Importiert app einmalig, damit load_dotenv() DATABASE_URL in os.environ
# legt - dieselbe Konvention wie tests/test_auth.py und
# tests/test_migration_drift.py. Ohne diesen Import wuerde die Fixture
# unten mangels DATABASE_URL stillschweigend ueberspringen.
import app as _app_bootstrap  # noqa: F401


#: Nur Datenbanknamen mit diesem Marker duerfen migriert werden.
REQUIRED_TEST_DB_MARKER = "footsim_test_db"

#: Hostnamen, die niemals Ziel eines Migrationstests sein duerfen.
FORBIDDEN_DB_HOST_HINTS = ("footsim.de", "hostinger", "187.124.161.32")


def _assert_is_test_database(db_url):
    """
    Harte Schutzvorrichtung gegen einen Lauf auf Produktionsdaten.

    Bewusst pytest.fail() statt skip: eine falsch konfigurierte
    DATABASE_URL soll auffallen, nicht stillschweigend uebersprungen
    werden.
    """
    if not db_url:
        pytest.skip("Keine DATABASE_URL konfiguriert")

    lowered = db_url.lower()

    for hint in FORBIDDEN_DB_HOST_HINTS:
        if hint in lowered:
            pytest.fail(
                f"Migrationstest gegen mutmassliche Produktionsdatenbank "
                f"abgebrochen (Treffer: {hint!r})"
            )

    if REQUIRED_TEST_DB_MARKER not in lowered:
        pytest.fail(
            "Migrationstest verlangt eine Datenbank mit "
            f"{REQUIRED_TEST_DB_MARKER!r} im Namen"
        )


@pytest.fixture(scope="function")
def migration_db(monkeypatch):
    """
    Leere Datenbank OHNE angewendete Migrationen.

    Anders als postgres_db in conftest.py wird hier bewusst NICHT bis
    zum Head migriert - die Tests steuern die Revisionen selbst.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url or "footsim_db" not in db_url:
        pytest.skip("Kein lokales PostgreSQL in DATABASE_URL konfiguriert")

    test_db_url = db_url.replace("footsim_db", REQUIRED_TEST_DB_MARKER)
    _assert_is_test_database(test_db_url)

    monkeypatch.setenv("DATABASE_URL", test_db_url)
    monkeypatch.setenv("TESTING", "1")

    import importlib
    import app as main_app
    importlib.reload(main_app)

    with main_app.app.app_context():
        _assert_is_test_database(str(main_app.db.engine.url))

        main_app.db.drop_all()
        main_app.db.session.execute(
            main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE")
        )
        main_app.db.session.commit()

        yield main_app

        main_app.db.session.remove()
        main_app.db.drop_all()
        main_app.db.session.execute(
            main_app.db.text("DROP TABLE IF EXISTS alembic_version CASCADE")
        )
        main_app.db.session.commit()


def _column_exists(db, table, column):
    return db.session.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar() is not None


def _current_revision(db):
    return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _insert_legacy_user(db, email):
    """
    Fuegt einen Bestandsnutzer per Roh-SQL ein - bewusst ohne ORM, damit
    der Datensatz genau die Spalten der JEWEILS aktuellen Revision hat.

    Die Spaltenliste richtet sich nach dem tatsaechlichen Schema: vor
    13bfa4eb853e existiert sessions_valid_after noch nicht, danach ist
    sie NOT NULL und muss mitgeliefert werden.
    """
    user_id = uuid.uuid4()

    columns = [
        "id", "email", "password_hash", "first_name", "last_name",
        "is_verified", "preferred_language", "created_at", "updated_at",
    ]
    values = [
        ":id", ":email", ":pw", ":fn", ":ln",
        "false", "'de'",
        "NOW() - INTERVAL '30 days'", "NOW() - INTERVAL '30 days'",
    ]

    if _column_exists(db, "users", "sessions_valid_after"):
        columns.append("sessions_valid_after")
        values.append("NOW() - INTERVAL '30 days'")

    db.session.execute(text(
        f"INSERT INTO users ({', '.join(columns)}) "
        f"VALUES ({', '.join(values)})"
    ), {
        "id": user_id,
        "email": email,
        "pw": "argon2-placeholder-hash",
        "fn": "Bestand",
        "ln": "Nutzer",
    })
    db.session.commit()
    return user_id


# ---------------------------------------------------------------------------
# Test 1 - leere Datenbank
# ---------------------------------------------------------------------------

def test_upgrade_on_empty_database(migration_db):
    from flask_migrate import upgrade
    db = migration_db.db

    with migration_db.app.app_context():
        upgrade()

        for table in ("users", "favorite_teams", "favorite_players"):
            assert db.session.execute(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
            ), {"t": table}).scalar() is not None, table

        for column in ("verified_at", "sessions_valid_after",
                       "profile_onboarding_completed"):
            assert _column_exists(db, "users", column), column


# ---------------------------------------------------------------------------
# Test 2 - der eigentliche Regressionstest
# ---------------------------------------------------------------------------

def test_upgrade_succeeds_with_existing_users(migration_db):
    """
    DER Test, der den Produktionsfehler verhindert.

    Vor der Korrektur brach der Schritt auf 13bfa4eb853e hier mit
    psycopg2.errors.NotNullViolation ab, sobald auch nur EINE Zeile in
    users stand.
    """
    from flask_migrate import upgrade
    db = migration_db.db

    with migration_db.app.app_context():
        # Nur bis zur Revision VOR den Auth-Tracking-Feldern.
        upgrade(revision="5bbd7b62dcc3")
        assert _current_revision(db) == "5bbd7b62dcc3"
        assert not _column_exists(db, "users", "sessions_valid_after")

        user_id = _insert_legacy_user(db, "bestand@example.com")

        # Genau dieser Schritt war der Produktionsblocker.
        upgrade()

        assert _column_exists(db, "users", "sessions_valid_after")

        # Keine NULL-Werte, sonst waere NOT NULL nicht erfuellbar gewesen.
        assert db.session.execute(text(
            "SELECT COUNT(*) FROM users WHERE sessions_valid_after IS NULL"
        )).scalar() == 0

        # Die Spalte ist tatsaechlich NOT NULL, nicht bloss befuellt.
        assert db.session.execute(text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='sessions_valid_after'"
        )).scalar() == "NO"

        # Der Bestandsnutzer ist unveraendert erhalten.
        row = db.session.execute(text(
            "SELECT email, first_name, last_name, password_hash "
            "FROM users WHERE id = :id"
        ), {"id": user_id}).one()
        assert row.email == "bestand@example.com"
        assert row.first_name == "Bestand"
        assert row.password_hash == "argon2-placeholder-hash"

        # Backfill ist fachlich sinnvoll: ab Kontoerstellung, nicht ab
        # Migrationszeitpunkt.
        assert db.session.execute(text(
            "SELECT sessions_valid_after = created_at FROM users WHERE id = :id"
        ), {"id": user_id}).scalar() is True

        # Das Modell setzt den Wert in Python - im Schema darf deshalb
        # kein server_default zurueckbleiben.
        assert db.session.execute(text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='sessions_valid_after'"
        )).scalar() is None


# ---------------------------------------------------------------------------
# Test 3 - Favorite-Team-Altbestand
# ---------------------------------------------------------------------------

def test_favorite_team_legacy_row_survives_display_migration(migration_db):
    from flask_migrate import upgrade
    db = migration_db.db

    with migration_db.app.app_context():
        upgrade(revision="b2c3d4e5f6a7")
        assert not _column_exists(db, "favorite_teams", "team_name")

        user_id = _insert_legacy_user(db, "favorit@example.com")
        db.session.execute(text(
            "INSERT INTO favorite_teams (user_id, team_id, source, created_at) "
            "VALUES (:uid, 5, 'football-data', NOW())"
        ), {"uid": user_id})
        db.session.commit()

        upgrade()

        assert _column_exists(db, "favorite_teams", "team_name")
        assert _column_exists(db, "favorite_teams", "crest_url")

        row = db.session.execute(text(
            "SELECT team_id, source, team_name, crest_url "
            "FROM favorite_teams WHERE user_id = :uid"
        ), {"uid": user_id}).one()

        # Altbestand bleibt erhalten und wird NICHT geraten.
        assert row.team_id == 5
        assert row.source == "football-data"
        assert row.team_name is None
        assert row.crest_url is None


# ---------------------------------------------------------------------------
# Test 4/5 - genau ein Head, keine Drift
# ---------------------------------------------------------------------------

def test_exactly_one_alembic_head():
    """Mehrere Heads wuerden 'flask db upgrade' mehrdeutig machen."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(project_root, "migrations", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(project_root, "migrations"))

    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"Erwartet genau ein Head, gefunden: {heads}"


def test_no_downgrade_leaves_orphan_columns(migration_db):
    """Der Rueckweg muss die beiden Spalten wieder entfernen."""
    from flask_migrate import upgrade, downgrade
    db = migration_db.db

    with migration_db.app.app_context():
        upgrade(revision="13bfa4eb853e")
        assert _column_exists(db, "users", "sessions_valid_after")

        downgrade(revision="5bbd7b62dcc3")
        assert not _column_exists(db, "users", "sessions_valid_after")
        assert not _column_exists(db, "users", "verified_at")
