"""
Spielerpool-Verwaltung fuer die Perzentilberechnung (Phase 3, Etappe 2).

Zustaendigkeit
--------------
Persistente Ablage der Referenzdaten, Importstatus, Sperre gegen parallele
Importe und ein resume-faehiger Importlauf.

Was dieses Modul NICHT tut
--------------------------
Es fuehrt keine HTTP-Requests selbst aus. Die Funktion import_league()
bekommt den Seitenabruf als Parameter uebergeben. Dadurch ist der komplette
Importablauf inklusive Wiederaufnahme ohne Netzwerk testbar, und die
Flask-Anwendung kann dieses Modul lesen, ohne je einen Import auszuloesen.

Warum kein Import im Nutzerrequest
----------------------------------
Der /players-Endpunkt von API-Sports liefert 20 Eintraege pro Seite. Eine
Top-5-Liga hat rund 500 bis 620 Spieler, also 26 bis 31 Seiten. Fuer alle
fuenf Ligen einer Saison sind das rund 136 bis 149 Requests. Mit sicherer
Drosselung dauert das ueber eine Minute. Das gehoert in einen Importjob,
nicht in eine Nutzeranfrage.

Ablageorte
----------
    data/player_pool/status.json            Importstatus aller Ligen
    data/player_pool/pool_{liga}_{saison}.json   Referenzdaten einer Liga
    data/player_pool/import.lock            Sperre gegen Doppelimporte
    data/percentiles/percentiles_{saison}.json   fertiger Snapshot

Die Rohpools bleiben ausserhalb der Versionsverwaltung, weil sie gross sind.
Der Snapshot dagegen ist kompakt und gehoert ins Repository, damit er nach
einem Deployment sofort vorliegt.
"""

import json
import os
import time
from datetime import datetime, timezone

from src.data.player_metrics import POSITION_GROUPS


# Absoluter Pfad, damit Importjob (Cron), Gunicorn und Tests unabhaengig vom
# aktuellen Arbeitsverzeichnis dieselben Dateien sehen. Ein relativer Pfad
# waere hier ein stiller Fehler: der Cronjob wuerde in ein anderes Verzeichnis
# schreiben als die Anwendung liest.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(_PROJECT_ROOT, "data", "player_pool")
STATUS_PATH = os.path.join(POOL_DIR, "status.json")
LOCK_PATH = os.path.join(POOL_DIR, "import.lock")

# Ein Lock, dessen Prozess nicht mehr laeuft und der aelter ist als diese
# Spanne, gilt als verwaist und darf uebernommen werden.
LOCK_STALE_SECONDS = 60 * 60  # 1 Stunde

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"


def _now():
    return datetime.now(timezone.utc)


def _ensure_dir():
    os.makedirs(POOL_DIR, exist_ok=True)


def _write_json_atomic(path, payload):
    """
    Schreibt JSON atomar: erst temporaer, dann umbenennen.

    Verhindert, dass ein parallel lesender Gunicorn-Worker eine halb
    geschriebene Datei sieht.
    """
    _ensure_dir()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_path, path)


def _read_json(path, fallback=None):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------

_LOCK_STALE_SECONDS = 7200  # 2 Stunden; ein echter Import braucht hoechstens 10 Minuten


def _lock_is_stale(lock_data):
    """
    Prueft ob ein Lockfile veraltet ist.

    Timestamp-Ansatz statt Prozess-Check.

    os.kill(pid, 0) funktioniert auf Linux zuverlaessig, aber auf Windows
    mit Python 3.9 blockiert es oder wirft falsche Ausnahmen. Deshalb kein
    Prozess-Check: Ein Lock gilt als verwaist wenn er aelter als 2 Stunden
    ist. Ein echter Import braucht maximal 10 Minuten.
    """
    if not lock_data:
        return True
    started_at = lock_data.get("started_at")
    if not started_at:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except (ValueError, TypeError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = (_now() - started).total_seconds()
    return age > _LOCK_STALE_SECONDS


def read_lock():
    return _read_json(LOCK_PATH)


def acquire_lock():
    """
    Versucht die Importsperre zu setzen.

    Rueckgabe: (True, None) bei Erfolg,
               (False, info) wenn ein anderer Import laeuft.

    Ein Lock eines nicht mehr existierenden Prozesses wird uebernommen,
    ebenso ein sehr alter Lock. Sonst wuerde ein Absturz den Import
    dauerhaft blockieren.
    """
    existing = read_lock()

    if existing and not _lock_is_stale(existing):
        return False, existing

    _write_json_atomic(LOCK_PATH, {
        "pid": os.getpid(),
        "started_at": _now().isoformat(),
    })
    return True, None


def release_lock():
    """Entfernt die Sperre. Muss immer im finally-Zweig aufgerufen werden."""
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def pool_key(league_code, season):
    return f"{league_code}_{season}"


def pool_path(league_code, season):
    return os.path.join(POOL_DIR, f"pool_{league_code}_{season}.json")


def read_status():
    return _read_json(STATUS_PATH, fallback={}) or {}


def write_status(status):
    _write_json_atomic(STATUS_PATH, status)


def update_pool_status(league_code, season, **fields):
    """Aktualisiert den Statuseintrag einer Liga und schreibt ihn sofort weg."""
    status = read_status()
    key = pool_key(league_code, season)
    entry = status.get(key) or {
        "league": league_code,
        "season": season,
        "status": STATUS_PENDING,
        "total_pages": None,
        "loaded_pages": 0,
        "player_count": None,
        "updated_at": None,
    }
    entry.update(fields)
    entry["updated_at"] = _now().isoformat(timespec="seconds")
    status[key] = entry
    write_status(status)
    return entry


def get_pool_status(league_code, season):
    return read_status().get(pool_key(league_code, season))


def is_pool_complete(league_code, season):
    entry = get_pool_status(league_code, season)
    return bool(entry and entry.get("status") == STATUS_COMPLETE)


def completed_leagues(season, league_codes):
    return [code for code in league_codes if is_pool_complete(code, season)]


# ---------------------------------------------------------------------------
# Pooldaten
# ---------------------------------------------------------------------------

def read_pool(league_code, season):
    """
    Laedt die Referenzdaten einer Liga.

    Rueckgabe: dict mit "players" und "pages_done", oder ein leeres Geruest.
    """
    data = _read_json(pool_path(league_code, season))
    if not data:
        return {
            "league": league_code,
            "season": season,
            "pages_done": [],
            "players": [],
        }
    data.setdefault("pages_done", [])
    data.setdefault("players", [])
    return data


def write_pool(pool):
    _write_json_atomic(pool_path(pool["league"], pool["season"]), pool)


def load_all_players(season, league_codes):
    """
    Sammelt die Spieler aller angegebenen Ligen zu einem Referenzpool.

    Nur vollstaendig importierte Ligen werden beruecksichtigt. Eine halb
    geladene Liga wuerde die Verteilung verzerren.

    Rueckgabe: (players, used_leagues)
    """
    players = []
    used = []

    for code in league_codes:
        if not is_pool_complete(code, season):
            continue
        pool = read_pool(code, season)
        players.extend(pool.get("players") or [])
        used.append(code)

    return players, used


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def build_pool_entry(profile, metric_values):
    """
    Reduziert ein Spielerprofil auf das, was der Referenzpool braucht.

    Die vollstaendigen Rohdaten werden bewusst NICHT gespeichert: der Pool
    dient nur der Verteilungsberechnung, nicht der Anzeige. Das haelt die
    Dateien klein und den Import schnell.

    Gespeicherte Filterdimensionen (Stand Phase 3.1):
        player_id, name, position, minutes, league_code, age, team_name

    age und team_name werden NICHT fuer Perzentile gebraucht. Sie liegen hier,
    damit ein spaeterer Scatter-Plot nach Alter und Verein filtern kann, ohne
    dass der komplette Pool neu importiert werden muss. Ein Reimport kostet
    rund 140 API-Requests je Saison - das vorab mitzuspeichern ist deutlich
    billiger als es spaeter nachzuholen.
    """
    return {
        "player_id": profile.get("player_id"),
        "name": profile.get("name"),
        "position": profile.get("position"),
        "minutes": profile.get("minutes"),
        "league_code": profile.get("league_code"),

        # Filterdimensionen fuer spaetere Auswertungen (Scatter, ML)
        "age": profile.get("age"),
        "team_name": profile.get("team_name"),

        "metrics": {k: v for k, v in metric_values.items() if v is not None},
    }


def import_league(league_code, season, fetch_page, build_entry,
                  throttle_seconds=0.5, resume=True, progress=None):
    """
    Importiert alle Seiten einer Liga.

    fetch_page(page)  -> dict mit "response" und "paging" (siehe _get_full)
    build_entry(raw)  -> Pooleintrag oder None, wenn der Spieler nicht zaehlt

    Beide werden injiziert, damit dieser Ablauf ohne Netzwerk getestet
    werden kann.

    resume=True setzt einen abgebrochenen Lauf fort, statt bereits geladene
    Seiten erneut abzurufen. Bei rund 30 Requests pro Liga ist das den
    kleinen Mehraufwand wert.

    Rueckgabe: Statuseintrag der Liga.
    """
    pool = read_pool(league_code, season) if resume else {
        "league": league_code, "season": season, "pages_done": [], "players": [],
    }

    pages_done = set(pool.get("pages_done") or [])
    players_by_id = {
        entry.get("player_id"): entry
        for entry in pool.get("players") or []
        if entry.get("player_id") is not None
    }

    update_pool_status(league_code, season, status=STATUS_IN_PROGRESS)

    try:
        first = fetch_page(1)
        total_pages = int((first.get("paging") or {}).get("total") or 1)

        update_pool_status(
            league_code, season,
            status=STATUS_IN_PROGRESS,
            total_pages=total_pages,
            loaded_pages=len(pages_done),
        )

        for page in range(1, total_pages + 1):
            if page in pages_done:
                continue

            payload = first if page == 1 else fetch_page(page)

            for raw in payload.get("response") or []:
                entry = build_entry(raw)
                if entry and entry.get("player_id") is not None:
                    players_by_id[entry["player_id"]] = entry

            pages_done.add(page)

            pool["pages_done"] = sorted(pages_done)
            pool["players"] = list(players_by_id.values())
            write_pool(pool)

            update_pool_status(
                league_code, season,
                status=STATUS_IN_PROGRESS,
                total_pages=total_pages,
                loaded_pages=len(pages_done),
            )

            if progress:
                progress(league_code, season, len(pages_done), total_pages)

            # Drosselung gegen das Sekundenlimit der API.
            # Die letzte Seite braucht keine Pause mehr.
            if throttle_seconds and page < total_pages:
                time.sleep(throttle_seconds)

        pool["pages_done"] = sorted(pages_done)
        pool["players"] = list(players_by_id.values())
        write_pool(pool)

        return update_pool_status(
            league_code, season,
            status=STATUS_COMPLETE,
            total_pages=total_pages,
            loaded_pages=len(pages_done),
            player_count=len(players_by_id),
        )

    except Exception as error:
        # Teilergebnis bleibt erhalten, damit ein spaeterer Lauf fortsetzen kann.
        pool["pages_done"] = sorted(pages_done)
        pool["players"] = list(players_by_id.values())
        write_pool(pool)

        update_pool_status(
            league_code, season,
            status=STATUS_ERROR,
            loaded_pages=len(pages_done),
            error=str(error),
        )
        raise


def coverage_report(season, league_codes):
    """Uebersicht fuer die Kommandozeile und spaeter fuer eine Statusanzeige."""
    rows = []
    for code in league_codes:
        entry = get_pool_status(code, season) or {}
        rows.append({
            "league": code,
            "season": season,
            "status": entry.get("status", STATUS_PENDING),
            "loaded_pages": entry.get("loaded_pages", 0),
            "total_pages": entry.get("total_pages"),
            "player_count": entry.get("player_count"),
            "updated_at": entry.get("updated_at"),
        })
    return rows
