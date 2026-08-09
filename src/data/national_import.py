"""
national_import.py - Import der A-Nationalmannschaftsstatistiken.

Aufgabe
-------
Fuer eine FootSim-Saison die Laenderspiel-Statistiken NUR der bereits im
Top-5-Ligen-Pool vorhandenen Spieler beschaffen und persistent ablegen,
sodass die vier Scopes (league / club_all / national / all) fuer Radar,
Scatter und Perzentile dieselbe Datenbasis nutzen.

Warum wettbewerbsbasiert
------------------------
Ein Laenderspielturnier ist ein kleiner, abgeschlossener Datensatz. Statt pro
Spieler dessen NM-Saison zu erraten und einzeln abzufragen, wird jeder
Zielwettbewerb EINMAL paginiert geladen (/players?league=<id>&season=<api>)
und daraus eine Map player_id -> [statistics-Bloecke] gebaut. Das ist deutlich
sparsamer und trifft genau die verifizierten Turniere aus der Discovery.

Grenze bewusst eng
------------------
Es werden ausschliesslich Spieler beruecksichtigt, die bereits im Pool sind.
Kein einziger neuer Spieler kommt hinzu. Der Pool bleibt der Top-5-Ligen-Pool;
er wird nur um die NM-Bloecke seiner vorhandenen Spieler ergaenzt.

Persistenz
----------
Die NM-Bloecke werden je FootSim-Saison unter data/national/national_<season>.json
abgelegt: player_id -> Liste roher statistics-Bloecke. Diese Datei ist die
Bruecke zwischen Import (einmalig, teuer) und Laufzeit (Radar/Scatter, gratis).
get_national_blocks() liest sie; die Anreicherung der Rohantwort passiert in
player_compare_loader.get_player_season_raw_enriched().
"""

import json
import os
import time

from src.api.apisports_api import (
    _get_full,
    ApisportsUnavailable,
    ApisportsRateLimit,
)
from src.data.national_competitions import national_targets_for_footsim_season
from src.utils.disk_cache import disk_cached_call


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NATIONAL_DIR = os.path.join(_PROJECT_ROOT, "data", "national")

# Sichere Drosselung zwischen echten Seitenabrufen.
THROTTLE_SECONDS = 0.5

# WICHTIG: Dies ist KEIN Datendeckel, sondern nur ein Notausstieg gegen eine
# fehlerhafte paging.total-Angabe der API (theoretische Endlosschleife). Der
# Import laeuft normal bis zur von der API gemeldeten letzten Seite. Der Wert
# liegt bewusst weit ueber jedem realen Turnier: die WM mit 48 Teams hat rund
# 63 Seiten; grosse laufende Wettbewerbe (Friendlies ueber eine ganze Saison)
# koennen mehr haben. Wird diese Grenze je erreicht, ist das ein Warnsignal
# und wird protokolliert - dann stimmt etwas mit der API-Antwort nicht.
PAGE_SAFETY_LIMIT = 500


def national_path(footsim_season):
    return os.path.join(NATIONAL_DIR, f"national_{footsim_season}.json")


def _ensure_dir():
    os.makedirs(NATIONAL_DIR, exist_ok=True)


def _fetch_competition_page(league_id, api_season, page):
    """Eine Seite /players?league=&season=&page= - mit Disk-Cache."""
    def loader():
        result = _get_full("players", params={
            "league": league_id, "season": api_season, "page": page,
        })
        time.sleep(THROTTLE_SECONDS)
        return result

    return disk_cached_call(
        key=f"apisports:natplayers:{league_id}:{api_season}:{page}",
        ttl_seconds=_national_ttl(api_season),
        loader=loader,
        source="api-sports",
    )


def _national_ttl(api_season):
    # Abgeschlossene Turniere aendern sich nicht mehr -> lange TTL.
    # Laufende (aktuelle/kommende) Saison kuerzer halten.
    from src.api.apisports_api import CURRENT_SEASON
    if api_season < CURRENT_SEASON:
        return 365 * 24 * 3600
    return 7 * 24 * 3600


def _iter_competition_players(league_id, api_season, progress=None):
    """
    Generator ueber alle (player_id, statistics_block) eines Turniers.

    Laeuft ueber ALLE von der API gemeldeten Seiten (paging.total). Kein
    kuenstlicher Datendeckel mehr - ein Turnier mit 63 Seiten wird vollstaendig
    geladen, eines mit 5 Seiten eben nur 5. PAGE_SAFETY_LIMIT greift nur, wenn
    die API eine unplausibel hohe Seitenzahl meldet (Schutz vor Endlosschleife).

    statistics_block ist der rohe API-Block MIT league-Objekt, so wie er auch
    in einer /players?id=-Antwort staende. So passt er nahtlos in die
    bestehende Aggregation.
    """
    first = _fetch_competition_page(league_id, api_season, 1)
    reported_total = (first.get("paging") or {}).get("total", 1) or 1

    # Vollstaendig bis zur gemeldeten letzten Seite. Das Safety-Limit ist nur
    # ein Notausstieg, kein Beschnitt realer Daten.
    total_pages = reported_total
    capped = False
    if total_pages > PAGE_SAFETY_LIMIT:
        total_pages = PAGE_SAFETY_LIMIT
        capped = True

    def emit(payload):
        for item in payload or []:
            player = item.get("player") or {}
            pid = player.get("id")
            if pid is None:
                continue
            for block in item.get("statistics") or []:
                yield pid, block

    yield from emit(first.get("response"))
    if progress:
        progress(league_id, api_season, 1, total_pages)

    for page in range(2, total_pages + 1):
        data = _fetch_competition_page(league_id, api_season, page)
        yield from emit(data.get("response"))
        if progress:
            progress(league_id, api_season, page, total_pages)

    if capped:
        # Sollte bei realen Turnieren nie passieren. Wenn doch, sichtbar machen.
        print(f"\n  WARNUNG: Wettbewerb {league_id}/{api_season} meldet "
              f"{reported_total} Seiten - bei {PAGE_SAFETY_LIMIT} gestoppt. "
              f"API-Antwort pruefen.")


def import_national_for_season(footsim_season, pool_player_ids, progress=None,
                               targets=None, merge_existing=False):
    """
    Importiert die NM-Bloecke aller Zielwettbewerbe einer FootSim-Saison,
    beschraenkt auf die uebergebenen pool_player_ids.

    pool_player_ids: Menge/Set der player_id, die bereits im Pool sind.
    progress: optionales callback(league_id, api_season, page, total).

    targets: optionale, EXPLIZITE Zielliste im Format von
        national_targets_for_footsim_season() - also
        [{"league_id", "api_season", "name"}]. Ohne Angabe werden wie bisher
        alle Zielwettbewerbe der FootSim-Saison geladen.

        Damit laesst sich ein EINZELNER Wettbewerb importieren, ohne die
        uebrigen (Friendlies, Qualifikationen, ...) mitzuziehen. Das ist
        keine Bequemlichkeit, sondern eine Budgetfrage: die Zielliste einer
        Saison umfasst schnell mehrere hundert Seiten, eine einzelne
        Endrunde nur einige Dutzend.

    merge_existing: bei einem TEILIMPORT zwingend True. Die Saisondatei wird
        sonst komplett ueberschrieben, und ein zuvor importierter anderer
        Wettbewerb derselben Saison ginge verloren. Beim vollstaendigen Lauf
        (targets=None) ist das Ueberschreiben dagegen korrekt: dort ist das
        Ergebnis per Definition die vollstaendige Sicht der Saison.

    Rueckgabe: dict player_id(str) -> Liste roher statistics-Bloecke.
    Schreibt zusaetzlich data/national/national_<footsim_season>.json.

    Wirft ApisportsRateLimit weiter, damit ein Lauf am Tageslimit sauber
    stoppen und spaeter fortsetzen kann (Seiten sind einzeln gecacht).
    """
    if targets is None:
        targets = national_targets_for_footsim_season(footsim_season)
    wanted = set(pool_player_ids)

    blocks_by_player = {}

    for target in targets:
        league_id = target["league_id"]
        api_season = target["api_season"]

        for pid, block in _iter_competition_players(league_id, api_season, progress):
            if pid not in wanted:
                continue
            # league-Objekt so anreichern, dass _infer_comp_type es sicher als
            # international erkennt (der Block traegt bereits die richtige
            # league.id/name aus der API; wir lassen ihn unveraendert).
            blocks_by_player.setdefault(str(pid), []).append(block)

    merged_targets = list(targets)

    if merge_existing:
        # Teilimport: vorhandene Bloecke anderer Wettbewerbe erhalten.
        # Dedupliziert wird ueber league.id je Spieler - ein erneuter Lauf
        # desselben Wettbewerbs erzeugt also keine Doubletten.
        existing_payload = _read_national_payload(footsim_season)
        existing_blocks = existing_payload.get("blocks_by_player") or {}

        for pid, new_blocks in blocks_by_player.items():
            old_blocks = existing_blocks.get(pid) or []
            new_ids = {(b.get("league") or {}).get("id") for b in new_blocks}
            kept = [
                b for b in old_blocks
                if (b.get("league") or {}).get("id") not in new_ids
            ]
            existing_blocks[pid] = kept + new_blocks

        blocks_by_player = existing_blocks

        seen = {(t["league_id"], t["api_season"]) for t in merged_targets}
        for old_target in existing_payload.get("targets") or []:
            key = (old_target.get("league_id"), old_target.get("api_season"))
            if key not in seen:
                merged_targets.append(old_target)
        merged_targets.sort(key=lambda t: (t["league_id"], t["api_season"]))

    _ensure_dir()
    payload = {
        "footsim_season": footsim_season,
        "targets": merged_targets,
        "player_count": len(blocks_by_player),
        "blocks_by_player": blocks_by_player,
    }
    with open(national_path(footsim_season), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    return blocks_by_player


def _read_national_payload(footsim_season):
    """Vorhandene Saisondatei lesen. Leeres Geruest, wenn keine existiert."""
    path = national_path(footsim_season)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Laufzeit-Zugriff (von player_compare_loader genutzt)
# ---------------------------------------------------------------------------

# Kleiner Prozess-Cache, damit nicht bei jedem Spieler die Datei neu gelesen
# wird. Key: footsim_season -> blocks_by_player (oder None wenn keine Datei).
_RUNTIME_CACHE = {}


def get_national_blocks(player_id, footsim_season):
    """
    Liefert die gespeicherten NM-Bloecke eines Spielers fuer eine FootSim-Saison.

    Rueckgabe: Liste roher statistics-Bloecke (ggf. leer). Nie None.
    Liest die Saisondatei hoechstens einmal je Prozess.
    """
    if footsim_season not in _RUNTIME_CACHE:
        path = national_path(footsim_season)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                _RUNTIME_CACHE[footsim_season] = data.get("blocks_by_player") or {}
            except (OSError, ValueError):
                _RUNTIME_CACHE[footsim_season] = {}
        else:
            _RUNTIME_CACHE[footsim_season] = {}

    return _RUNTIME_CACHE[footsim_season].get(str(player_id), [])


def clear_runtime_cache():
    """Fuer Tests und nach einem Reimport."""
    _RUNTIME_CACHE.clear()
