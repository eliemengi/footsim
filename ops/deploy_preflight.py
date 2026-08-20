#!/usr/bin/env python3
"""
Deployment-Preflight: passt das Schema der Datenbank zum Code?

Warum es das gibt
-----------------
SQLAlchemy selektiert immer ALLE gemappten Spalten. Fehlt eine davon in
der Datenbank, liefert jeder betroffene Request HTTP 500 mit vollem
Traceback - und zwar erst NACH dem Neustart, wenn der alte Code schon
weg ist. Genau das ist in diesem Projekt einmal passiert: der Login gab
weiter 200 zurueck, nur das anschliessende /api/auth/me brach ab, was
wie ein kaputter Login aussah.

Dieses Skript beantwortet die Frage vorher, in einer Zeile, mit einem
Exit-Code - und ohne Zugangsdaten auszugeben.

Aufruf (auf dem VPS, im Projektverzeichnis):

    venv/bin/python ops/deploy_preflight.py

Exit-Codes:
    0  up-to-date          Datenbank ist auf dem Head des Codes
    10 migration-pending   Migration noetig (normaler Deploy-Fall)
    11 multiple-heads      Mehrdeutige Migrationskette
    12 db-unreachable      Datenbank nicht erreichbar
    13 inconsistent        Revision unbekannt / Schema passt nicht zum Code
    2  usage/config error

Bewusst KEIN Startup-Check in der App: ein blockierender Import wuerde
genau den Migrationslauf verhindern, der das Problem beheben soll.
"""

import os
import sys

EXIT_OK = 0
EXIT_PENDING = 10
EXIT_MULTIPLE_HEADS = 11
EXIT_UNREACHABLE = 12
EXIT_INCONSISTENT = 13
EXIT_USAGE = 2


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(root, ".env"))
    except ImportError:
        pass

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("preflight: FEHLER - DATABASE_URL ist nicht gesetzt")
        return EXIT_USAGE

    try:
        import sqlalchemy as sa
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError as error:
        print(f"preflight: FEHLER - Abhaengigkeit fehlt ({error.name})")
        return EXIT_USAGE

    # --- Head(s) aus dem Repository -------------------------------------
    config = Config(os.path.join(root, "migrations", "alembic.ini"))
    config.set_main_option("script_location", os.path.join(root, "migrations"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()

    if len(heads) != 1:
        print(f"preflight: MEHRDEUTIG - {len(heads)} Alembic-Heads: {', '.join(heads)}")
        print("preflight: 'flask db merge' noetig, kein Deployment")
        return EXIT_MULTIPLE_HEADS

    head = heads[0]

    # --- Stand der Datenbank --------------------------------------------
    try:
        engine = sa.create_engine(database_url)
        with engine.connect() as connection:
            current = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
    except Exception as error:
        # Niemals die Exception im Klartext ausgeben - sie enthaelt die
        # vollstaendige Verbindungs-URL inklusive Passwort.
        print(f"preflight: DATENBANK NICHT ERREICHBAR ({type(error).__name__})")
        return EXIT_UNREACHABLE

    if current is None:
        print("preflight: INKONSISTENT - alembic_version ist leer")
        return EXIT_INCONSISTENT

    if current == head:
        print(f"preflight: UP-TO-DATE (revision {current})")
        return EXIT_OK

    known = {revision.revision for revision in script.walk_revisions()}
    if current not in known:
        print(f"preflight: INKONSISTENT - Revision {current} ist dem Code unbekannt")
        print("preflight: laeuft die Datenbank gegen eine neuere Codeversion?")
        return EXIT_INCONSISTENT

    pending = [
        revision.revision
        for revision in script.iterate_revisions(head, current)
        if revision.revision != current
    ]
    print(f"preflight: MIGRATION NOETIG - db={current} head={head}")
    print(f"preflight: ausstehend ({len(pending)}): {', '.join(reversed(pending))}")
    print("preflight: VOR dem Neustart 'flask db upgrade' ausfuehren")
    return EXIT_PENDING


if __name__ == "__main__":
    sys.exit(main())
