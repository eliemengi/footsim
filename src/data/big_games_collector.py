"""
Sammler fuer den Big-Games-Datensatz (Block C24).

STANDARD IST DER TROCKENLAUF
----------------------------
Ohne ausdrueckliches execute=True wird GARANTIERT kein Anbieterabruf
ausgefuehrt. Das ist keine Konvention der Aufrufer, sondern technisch
erzwungen: Waehrend des Laufs sitzt ein Tor (disk_cache.request_gate) vor
jedem Nachladen. Im Trockenlauf weist es jeden Loader VOR seinem Aufruf
ab und zaehlt den Schluessel als geplanten Abruf.

Ein echter Abruf ist nur moeglich mit
    execute=True UND einem positiven max_provider_requests (hoechstens 500).
Fehlt eines davon, bricht der Lauf vor dem ersten Abruf ab.

WAS GESAMMELT WIRD
------------------
Population: alle Spieler der Top-5-Ligapools einer Saison, eindeutig ueber
die Player-ID. Je Spieler rechnet der Sammler exakt, was der
Einzelvergleich rechnet (big_games_loader.compute_player_big_games_uncached):
Profil -> Vereinswettbewerbe -> Spielplaene -> Klassifikation ->
Einzelspielerwerte nur fuer qualifizierte Spiele, dazu Nationalspiele.

Vorhandene Cacheeintraege werden immer zuerst benutzt, auch abgelaufene:
Spielplan und Einzelspielerwerte einer abgeschlossenen Saison aendern
sich nicht mehr. Ein Spiel, dessen Werte schon lokal liegen, wird daher
nie erneut geladen. Dieselbe Fixture wird ueber alle Spieler hinweg
genau einmal geholt (gemeinsamer Cacheschluessel).

VOLLSTAENDIG ODER NICHT
-----------------------
Ein Spieler gilt nur dann als erledigt, wenn waehrend seiner Rechnung kein
einziger benoetigter Eintrag gefehlt hat oder fehlgeschlagen ist. Erst
wenn ALLE Spieler der Population erledigt sind, entsteht der Datensatz.
Vorher gibt es ausschliesslich den Checkpoint - fortsetzbar, nie als
vollstaendig markiert.
"""

import os
import time
from collections import deque
from datetime import datetime, timezone

from src.api.apisports_api import ApisportsRateLimit, ApisportsUnavailable
from src.data import big_games_dataset as dataset
from src.utils import disk_cache

#: Harte Obergrenze je Ausfuehrung, unabhaengig von jeder Eingabe.
MAX_REQUESTS_PER_RUN = 500

#: Takt je Minute. Der Anbieter nennt sein Minutenlimit im Antwortkopf
#: (x-ratelimit-limit, aktuell 300 im Pro-Tarif). Ohne Taktung feuert ein
#: 500er-Lauf rund 400 Abrufe je Minute und bekommt den Rest als HTTP 429
#: zurueck - gemessen 176 von 500. Der Wert hier liegt bewusst darunter,
#: damit auch Abrufe anderer Programmteile im selben Zeitfenster Platz
#: haben. Das haelt das Limit ein; es wird nicht umgangen.
MAX_REQUESTS_PER_MINUTE = 240

#: Fenster, ueber das der Takt gemessen wird.
RATE_WINDOW_SECONDS = 60.0

#: Ein Lock gilt als verwaist, wenn er aelter ist als diese Spanne.
LOCK_STALE_SECONDS = 6 * 60 * 60

#: Checkpoint nach so vielen erledigten Spielern zwischenspeichern.
CHECKPOINT_EVERY = 25

MODE_DRY_RUN = "dry_run"
MODE_EXECUTE = "execute"

#: Schluesselpraefixe -> Art des Abrufs (fuer die Messung).
KEY_KINDS = (
    ("apisports:playerprofile:", "player_profile"),
    ("apisports:team_season_fixtures:", "club_team_fixtures"),
    ("apisports:fixture_players:", "club_fixture_players"),
    ("national_big_games:v2:team_season_fixtures:", "national_team_fixtures"),
    ("national_big_games:v2:fixture_players:", "national_fixture_players"),
    ("national_big_games:v2:team_identity:", "national_team_identity"),
)


class CollectorError(Exception):
    """Ungueltiger Aufruf - wird vor jedem Abruf erkannt."""


class CollectorLocked(CollectorError):
    """Ein anderer Sammler laeuft bereits."""


class ProviderRequestBlocked(ApisportsUnavailable):
    """
    Ein benoetigter Abruf wurde nicht ausgefuehrt (Trockenlauf oder Budget).

    Bewusst eine Unterart von ApisportsUnavailable: Die Loader behandeln
    ihn dadurch genau wie einen Anbieterausfall. Das Tor merkt sich
    zusaetzlich, dass der betroffene Spieler unvollstaendig ist.
    """


class _CachedEntryPreferred(Exception):
    """Ein vorhandener (auch abgelaufener) Eintrag wird benutzt."""


def key_kind(key):
    for prefix, kind in KEY_KINDS:
        if str(key).startswith(prefix):
            return kind
    return "other"


def _now():
    return datetime.now(timezone.utc)


class RequestGate:
    """
    Das Tor vor jedem Nachladen waehrend eines Sammlerlaufs.

    Trockenlauf: jeder fehlende Schluessel wird abgewiesen und gezaehlt.
    Ausfuehrung: fehlende Schluessel werden geladen, solange Budget da ist.
    Ein vorhandener Eintrag wird immer benutzt, nie erneut geladen.

    Die Abrufe werden getaktet (MAX_REQUESTS_PER_MINUTE) und ein
    Minutenlimit des Anbieters beendet den Lauf, statt ihn ins Limit
    hineinlaufen zu lassen.
    """

    def __init__(self, execute, max_requests, sleep=None, clock=None):
        self.execute = bool(execute)
        self.max_requests = int(max_requests or 0)
        self.used = 0
        self.exhausted = False
        self.missing_keys = set()      # fehlten lokal (geplant oder geladen)
        self.requested_keys = set()    # tatsaechlich an den Anbieter
        self.fetched_keys = set()      # erfolgreich geladen
        self.failed_keys = set()       # Anbieter hat mit Fehler geantwortet
        self.stale_keys = set()        # abgelaufen, aber lokal vorhanden
        self.rate_limited_keys = set()  # Anbieter hat mit 429 geantwortet
        self.rate_limited = False      # Minutenlimit erreicht -> Lauf beenden
        self._player_problem = False
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._times = deque()          # Zeitpunkte der letzten Abrufe

    def begin_player(self):
        self._player_problem = False

    @property
    def player_incomplete(self):
        return self._player_problem

    def _pace(self):
        """
        Wartet, bis der naechste Abruf innerhalb des Minutentakts liegt.

        Kein Umgehen des Limits, sondern dessen Einhaltung: Es wird nie
        mehr als MAX_REQUESTS_PER_MINUTE in einem Fenster gestartet.
        """
        while True:
            now = self._clock()
            while self._times and now - self._times[0] >= RATE_WINDOW_SECONDS:
                self._times.popleft()
            if len(self._times) < MAX_REQUESTS_PER_MINUTE:
                break
            # Warten, bis der aelteste Abruf aus dem Fenster faellt. Danach
            # erneut pruefen: Ein Rundungsrest darf das Fenster nicht um
            # einen Abruf ueberlaufen lassen.
            wait = RATE_WINDOW_SECONDS - (now - self._times[0])
            self._sleep(max(wait, 0.001))
        self._times.append(self._clock())

    def __call__(self, key, source, has_entry, loader):
        if has_entry:
            self.stale_keys.add(key)
            raise _CachedEntryPreferred(key)

        self.missing_keys.add(key)
        if not self.execute:
            self._player_problem = True
            raise ProviderRequestBlocked(f"Trockenlauf: {key_kind(key)} nicht geladen")
        if key in self.failed_keys:
            self._player_problem = True
            raise ProviderRequestBlocked("in diesem Lauf bereits fehlgeschlagen")
        if self.used >= self.max_requests:
            self.exhausted = True
            self._player_problem = True
            raise ProviderRequestBlocked("Abrufbudget erschoepft")
        if self.rate_limited:
            # Nach einem Minutenlimit wird in diesem Lauf nichts mehr
            # nachgeladen - kein Nachsetzen gegen ein laufendes Limit.
            self._player_problem = True
            raise ProviderRequestBlocked("Minutenlimit des Anbieters erreicht")

        self.used += 1
        self.requested_keys.add(key)

        def run():
            self._pace()
            try:
                result = loader()
            except ApisportsRateLimit:
                self.rate_limited_keys.add(key)
                self.failed_keys.add(key)
                self.rate_limited = True
                self._player_problem = True
                raise
            except Exception:
                self.failed_keys.add(key)
                self._player_problem = True
                raise
            self.fetched_keys.add(key)
            return result

        return run


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------

def acquire_lock(now=None):
    """
    Legt die Sperre atomar an. Wirft CollectorLocked, wenn belegt.

    Wie beim Poolimport (player_pool._lock_is_stale) ohne Prozesspruefung:
    os.kill(pid, 0) ist unter Windows kein harmloser Test (Signal 0 ist
    dort CTRL_C_EVENT). Ein Lock gilt ausschliesslich ueber sein Alter als
    verwaist.
    """
    path = dataset.lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = now or time.time()

    existing = dataset.read_json(path)
    if existing is not None:
        age = now - float(existing.get("created_ts") or 0)
        if age < LOCK_STALE_SECONDS:
            raise CollectorLocked(
                f"Sammler laeuft bereits (seit {int(age)} s, PID {existing.get('pid')}).")
        os.remove(path)
    elif os.path.exists(path):
        # Unlesbare Sperrdatei: lieber stehen lassen als uebergehen.
        raise CollectorLocked("Sperrdatei vorhanden, aber nicht lesbar.")

    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise CollectorLocked("Sammler laeuft bereits.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write('{"pid": %d, "created_ts": %f}' % (os.getpid(), now))


def release_lock():
    try:
        os.remove(dataset.lock_path())
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Population
# ---------------------------------------------------------------------------

def season_population(season, league_codes=None):
    """
    Alle Spieler der Ligapools einer Saison, einmal je Player-ID.

    Rueckgabe: (eintraege_nach_id, ligen, doppelte)
    """
    from src.data import player_pool
    from src.data.player_compare_loader import COMPARE_LEAGUE_CODES

    league_codes = tuple(league_codes or COMPARE_LEAGUE_CODES)
    by_id = {}
    used = []
    duplicates = 0
    for code in league_codes:
        players, used_codes = player_pool.load_all_players(season, [code])
        if not used_codes:
            continue
        used.append(code)
        for entry in players:
            player_id = entry.get("player_id")
            if not isinstance(player_id, int) or player_id <= 0:
                continue
            if player_id in by_id:
                duplicates += 1
                continue
            by_id[player_id] = {**entry, "league_code": entry.get("league_code") or code}
    return by_id, used, duplicates


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint(season):
    data = dataset.read_json(dataset.checkpoint_path(season))
    if (not data or data.get("season") != season
            or data.get("contract_version") != dataset.DATASET_CONTRACT_VERSION):
        return {
            "season": season,
            "contract_version": dataset.DATASET_CONTRACT_VERSION,
            "status": "not_started",
            "players_done": {},
            "requests_used_total": 0,
            "runs": [],
        }
    data.setdefault("players_done", {})
    data.setdefault("runs", [])
    return data


def save_checkpoint(checkpoint):
    checkpoint["updated_at"] = _now().isoformat(timespec="seconds")
    dataset.write_json_atomic(dataset.checkpoint_path(checkpoint["season"]), checkpoint)


# ---------------------------------------------------------------------------
# Lauf
# ---------------------------------------------------------------------------

def source_problem(result):
    """
    Ist die Rechnung eines Spielers belastbar? None oder ein Grund.

    Fail closed, wenn der historische Snapshot fehlte: Ohne UEFA-Snapshot
    der Saison liefert der Vereinsweg keine Big Games (club_available
    False) - das waere sonst ein Spieler mit scheinbar null Big Games.
    Ebenso bei fehlenden FIFA-Jahren oder nicht erreichbaren
    Nationalteamquellen. Es wird nie ein Ersatz-Snapshot eingesetzt.
    """
    for season in (result or {}).get("seasons") or []:
        if not season.get("club_available"):
            return "uefa_snapshot_missing"
        if season.get("national_unavailable_ranking_years"):
            return "fifa_snapshot_missing"
        if season.get("national_unavailable_targets"):
            return "national_source_incomplete"
    return None


def _validate(execute, max_provider_requests):
    if not execute:
        return 0
    if max_provider_requests is None:
        raise CollectorError(
            "Ausfuehrung ohne Abrufbudget ist nicht erlaubt: "
            "--max-provider-requests setzen (1 bis 500).")
    if isinstance(max_provider_requests, bool) or not isinstance(max_provider_requests, int):
        raise CollectorError("Das Abrufbudget muss eine ganze Zahl sein.")
    if max_provider_requests <= 0:
        raise CollectorError("Das Abrufbudget muss positiv sein.")
    if max_provider_requests > MAX_REQUESTS_PER_RUN:
        raise CollectorError(
            f"Hoechstens {MAX_REQUESTS_PER_RUN} Anbieterabrufe je Ausfuehrung.")
    return max_provider_requests


def run(season, execute=False, max_provider_requests=None, max_players=None,
        league_codes=None, compute=None, progress=None):
    """
    Ein Sammlerlauf. Rueckgabe: Bericht (dict).

    compute: Rechenweg je Spieler, Standard ist der des Einzelvergleichs
             ohne Ergebniscache. Nur Tests setzen ihn.
    """
    from src.data.big_games_loader import compute_player_big_games_uncached

    budget = _validate(execute, max_provider_requests)
    if max_players is not None and (not isinstance(max_players, int) or max_players <= 0):
        raise CollectorError("max_players muss eine positive ganze Zahl sein.")
    compute = compute or compute_player_big_games_uncached

    population, used_leagues, duplicate_entries = season_population(season, league_codes)
    player_ids = sorted(population)

    if execute:
        acquire_lock()
    started = time.time()
    try:
        checkpoint = load_checkpoint(season)
        done = checkpoint["players_done"]
        gate = RequestGate(execute, budget)

        processed = 0
        completed_now = 0
        pending = {}
        errors = {}
        source_problems = {}
        fifa_years = set()

        with disk_cache.request_gate(gate), disk_cache.read_memo() as memo:
            for player_id in player_ids:
                if str(player_id) in done:
                    continue
                if max_players is not None and processed >= max_players:
                    break
                if execute and (gate.exhausted or gate.rate_limited):
                    break
                processed += 1
                gate.begin_player()
                try:
                    result = compute(player_id, season, season)
                except (ApisportsUnavailable, ApisportsRateLimit):
                    result = None
                except Exception as error:   # ein Spieler darf den Lauf nicht beenden
                    errors[player_id] = type(error).__name__
                    result = None

                problem = source_problem(result) if result is not None else None
                if problem:
                    source_problems[problem] = source_problems.get(problem, 0) + 1

                if result is not None and not gate.player_incomplete and not problem:
                    if execute:
                        row = dataset.build_player_row(population[player_id], season, result)
                        done[str(player_id)] = row
                        for match in row["matches"]:
                            if match.get("source") == "national" and match.get("date"):
                                fifa_years.add(int(str(match["date"])[:4]))
                    completed_now += 1
                else:
                    pending[player_id] = (problem or
                                          ("error" if player_id in errors else "missing_data"))

                if execute and completed_now and completed_now % CHECKPOINT_EVERY == 0:
                    checkpoint["population_size"] = len(player_ids)
                    checkpoint["status"] = dataset.STATUS_INCOMPLETE
                    save_checkpoint(checkpoint)
                if progress:
                    progress(processed, len(player_ids), gate)

            memo_snapshot = dict(memo)

        remaining = [pid for pid in player_ids if str(pid) not in done]
        report = _report(season, execute, budget, population, used_leagues,
                         duplicate_entries, player_ids, processed, completed_now,
                         pending, errors, gate, memo_snapshot, done, started)
        report["measured"]["players_with_source_problems"] = source_problems

        if execute:
            checkpoint["population_size"] = len(player_ids)
            checkpoint["requests_used_total"] = (
                int(checkpoint.get("requests_used_total") or 0) + gate.used)
            checkpoint["runs"].append({
                "finished_at": _now().isoformat(timespec="seconds"),
                "requests_used": gate.used,
                "players_completed": completed_now,
                "exhausted": gate.exhausted,
            })
            if remaining:
                checkpoint["status"] = dataset.STATUS_INCOMPLETE
                save_checkpoint(checkpoint)
            else:
                document = dataset.build_dataset(
                    season,
                    list(done.values()),
                    population={
                        "source": "top5_player_pools",
                        "leagues": used_leagues,
                        "players": len(player_ids),
                        "duplicate_pool_entries": duplicate_entries,
                    },
                    collector_meta={
                        "requests_used_total": checkpoint["requests_used_total"],
                        "runs": len(checkpoint["runs"]),
                    },
                    fifa_years=sorted(fifa_years),
                )
                dataset.write_dataset(document)
                checkpoint["status"] = dataset.STATUS_COMPLETE
                save_checkpoint(checkpoint)
            report["checkpoint_status"] = checkpoint["status"]
            report["dataset_written"] = not remaining
        return report
    finally:
        if execute:
            release_lock()


def _report(season, execute, budget, population, used_leagues, duplicate_entries,
            player_ids, processed, completed_now, pending, errors, gate, memo,
            done, started):
    """Messbericht. Getrennt nach gemessen / abgeleitet."""
    by_kind = {}
    for key, entry in memo.items():
        kind = key_kind(key)
        if kind == "other":
            continue
        bucket = by_kind.setdefault(kind, {"accessed": 0, "fresh": 0, "stale": 0, "missing": 0})
        bucket["accessed"] += 1
        if entry is None:
            bucket["missing"] += 1
        elif disk_cache.is_fresh(entry):
            bucket["fresh"] += 1
        else:
            bucket["stale"] += 1

    planned = {}
    for key in gate.missing_keys - gate.fetched_keys:
        kind = key_kind(key)
        planned[kind] = planned.get(kind, 0) + 1

    teams = set()
    teams_with_any_list = set()
    team_lists_present = 0
    team_lists_missing = 0
    for key, entry in memo.items():
        if key.startswith("apisports:team_season_fixtures:"):
            parts = key.split(":")
            if len(parts) >= 5:
                teams.add(parts[2])
                if entry is not None:
                    teams_with_any_list.add(parts[2])
                    team_lists_present += 1
                else:
                    team_lists_missing += 1

    return {
        "mode": MODE_EXECUTE if execute else MODE_DRY_RUN,
        "season": season,
        "network_requests_allowed": bool(execute),
        "budget": budget,
        "requests_used": gate.used,
        "budget_exhausted": gate.exhausted,
        "measured": {
            "population_players": len(player_ids),
            "population_leagues": used_leagues,
            "duplicate_pool_entries": duplicate_entries,
            "players_processed": processed,
            "players_complete_from_local_data": completed_now if not execute else None,
            "players_completed_this_run": completed_now if execute else None,
            "players_already_done": len(done) - (completed_now if execute else 0),
            "players_needing_data": len(pending),
            "players_with_errors": len(errors),
            "unique_club_teams": len(teams),
            "club_teams_with_a_local_fixture_list": len(teams_with_any_list),
            "club_team_season_fixture_lists_present": team_lists_present,
            "club_team_season_fixture_lists_missing": team_lists_missing,
            "cache_by_kind": by_kind,
            "missing_keys_by_kind": planned,
            "missing_keys_total": sum(planned.values()),
            "stale_entries_used": len(gate.stale_keys),
            "requests_failed": len(gate.failed_keys),
            "requests_rate_limited": len(gate.rate_limited_keys),
        },
        "rate_limited": gate.rate_limited,
        "derived": {
            "club_qualified_fixtures_seen": (by_kind.get("club_fixture_players") or {}).get("accessed", 0),
            "national_qualified_fixtures_seen": (by_kind.get("national_fixture_players") or {}).get("accessed", 0),
            "note": ("Fehlt das Profil eines Spielers, sind seine Vereine und damit "
                     "seine Spielplaene unbekannt. Die Zahl fehlender Schluessel ist "
                     "deshalb eine UNTERGRENZE des Abrufbedarfs."),
        },
        "duration_seconds": round(time.time() - started, 1),
    }
