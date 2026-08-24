"""
Spielersuche direkt beim Anbieter (Block F1.1).

Abgrenzung - das ist der Kern dieses Moduls
--------------------------------------------
FootSim hat ZWEI Spielersuchen, und sie duerfen sich nicht vermischen:

  1. POOL-SUCHE (src/data/player_compare_loader.py::search_players_in_pool)
     Durchsucht den lokal importierten Top-5-Ligen-Pool. Sie definiert die
     Vergleichspopulation: Perzentile, Scatter/Plots und Kohorten haengen
     an genau dieser Menge. Sie bleibt unveraendert.

  2. LIVE-SUCHE (dieses Modul)
     Fragt API-Football direkt und findet dadurch auch Spieler, die nicht
     im lokalen Pool stehen - historische Spieler, Wechsler, Spieler aus
     Wettbewerben ohne Poolimport.

Dieses Modul befuellt AUSDRUECKLICH KEINEN Pool und veraendert keine
Population. Ein hier gefundener Spieler taucht dadurch NICHT in den
Scatter-Plots oder in einer Perzentil-Vergleichsgruppe auf. Die Trennung
ist Absicht: Big Games und der direkte Radarvergleich duerfen einen
groesseren Spielerraum kennen als die statistische Population.

Warum ueberhaupt live gesucht wird
----------------------------------
API-Football verlangt bei /players?search= zwingend zusaetzlich league
ODER team - eine freie Namenssuche ueber alle Wettbewerbe gibt es nicht
(an echten Antworten geprueft). Deshalb wird gezielt ueber die FootSim
bekannten Wettbewerbe iteriert statt "irgendwo" zu suchen. Das begrenzt
zugleich den Spielerraum sinnvoll: gefunden wird nur, wer in einem
Wettbewerb gespielt hat, den FootSim ohnehin auswertet.

Identitaet
----------
Zusammengefuehrt wird ausschliesslich ueber die stabile
API-Football-Player-ID, nie ueber den Namen. Derselbe Spieler taucht in
Liga UND Champions League auf, und ueber mehrere Saisons hinweg ohnehin -
er darf trotzdem nur einmal erscheinen. Namensvergleiche waeren bei
Umschrift und Namensgleichheit unzuverlaessig.
"""

from src.api import apisports_api
from src.api.apisports_api import ApisportsUnavailable, ApisportsRateLimit
from src.data.player_metrics import POSITION_LABELS
from src.utils.disk_cache import disk_cached_call


# Wettbewerbe, in denen live gesucht wird. Bewusst die bestehenden
# FootSim-Wettbewerbe und NICHT der komplette API-Football-Katalog:
# die Suche soll gezielt bleiben, und wer in keinem dieser Wettbewerbe
# gespielt hat, ist fuer einen FootSim-Vergleich ohnehin nicht sinnvoll
# einzuordnen.
#
# Reihenfolge ist bedeutsam: die nationalen Ligen stehen vorn, damit ein
# Spieler mit seinem Ligaverein angezeigt wird und nicht mit dem
# Wettbewerb, ueber den er zufaellig zuerst gefunden wurde.
LIVE_SEARCH_LEAGUE_CODES = ("pl", "pd", "sa", "bl1", "fl1", "cl", "el")

# Anzeigenamen der durchsuchten Wettbewerbe. COMPARE_LEAGUE_LABELS deckt
# nur die fuenf Ligen ab; hier kommen die beiden europaeischen dazu.
LIVE_SEARCH_LEAGUE_LABELS = {
    "pl":  "Premier League",
    "pd":  "LaLiga",
    "sa":  "Serie A",
    "bl1": "Bundesliga",
    "fl1": "Ligue 1",
    "cl":  "Champions League",
    "el":  "Europa League",
}

# Die Uebersetzung der Providerpositionen liegt seit der Datenreparatur in
# src/data/player_metrics.py, direkt neben POSITION_GROUPS. Vorher stand sie
# hier - in einem Suchmodul, das mit Positionslogik nichts zu tun hat. Genau
# deshalb fehlte dort jahrelang die Variante "Forward" (2.424 Vorkommen im
# lokalen Cache): Wer nach Positionslogik sucht, sucht nicht in der
# Live-Suche.
#
# Der Name bleibt hier als Re-Export erhalten, damit bestehende Aufrufer
# (big_games_loader) unveraendert weiterlaufen.
from src.data.player_metrics import (          # noqa: F401  (Re-Export)
    POSITION_ALIASES,
    normalize_position,
)

TTL_LIVE_SEARCH = 60 * 60 * 12     # 12 Stunden


def _search_one(query, league_id, season):
    """Ein Wettbewerb, eine Saison - mit Plattencache."""
    def loader():
        return apisports_api.search_players_in_league(query, league_id, season)

    return disk_cached_call(
        key=f"livesearch:{season}:{league_id}:{query.lower()}",
        ttl_seconds=TTL_LIVE_SEARCH,
        loader=loader,
        source="api-football.com/players",
    )


def _pick_statistics_block(entry, league_id):
    """
    Der Statistikblock, der zum durchsuchten Wettbewerb gehoert.

    Der Provider liefert je Spieler mehrere Bloecke (ein Verein/Wettbewerb
    je Block). Ohne diese Auswahl wuerde bei einem Spieler mit mehreren
    Stationen ein beliebiger Verein angezeigt.
    """
    blocks = [b for b in (entry.get("statistics") or []) if isinstance(b, dict)]
    if not blocks:
        return {}

    for block in blocks:
        if (block.get("league") or {}).get("id") == league_id:
            return block

    return blocks[0]


def _build_result(entry, league_code, league_id, season):
    """
    Ein Suchtreffer in GENAU der Form, die die bestehende Trefferliste
    erwartet (siehe pcRenderResults/pcSelectPlayer/pcRenderSelected in
    static/script.js sowie _search_result_from_pool_entry).

    Abweichende Feldnamen waren die Ursache dafuer, dass Big-Games-Treffer
    als "Unbekannt" und deaktiviert erschienen (Block F1.1).
    """
    player = entry.get("player") or {}
    player_id = player.get("id")
    if player_id is None:
        return None

    stats = _pick_statistics_block(entry, league_id)
    team = stats.get("team") or {}
    games = stats.get("games") or {}

    position = normalize_position(games.get("position")) or normalize_position(
        player.get("position"))

    return {
        "player_id": player_id,
        "name": player.get("name"),
        "photo": player.get("photo"),
        "age": player.get("age"),
        "nationality": player.get("nationality"),
        "season": season,
        "team_name": team.get("name"),
        "team_logo": team.get("logo"),
        "league_code": league_code,
        "league_label": LIVE_SEARCH_LEAGUE_LABELS.get(league_code),
        "position": position,
        "position_label": POSITION_LABELS.get(position),
        "minutes": games.get("minutes"),
        # Ein live gefundener Spieler IST fuer den direkten Vergleich
        # nutzbar - er hat in einem von FootSim ausgewerteten Wettbewerb
        # gespielt. "comparable" beschreibt die Vergleichbarkeit, NICHT
        # die Mitgliedschaft im Top-5-Populationspool. Genau diese
        # Verwechslung hat in F1 jeden Treffer deaktiviert.
        "comparable": True,
        # Herkunft des Treffers - erlaubt dem Aufrufer, Pool- und
        # Live-Treffer zu unterscheiden, ohne sie zu vermischen.
        "source": "live",
    }


def search_live(query, seasons, league_codes=LIVE_SEARCH_LEAGUE_CODES):
    """
    Sucht einen Spieler live ueber mehrere Saisons und Wettbewerbe.

    seasons: iterierbare Saisonjahre. Die Reihenfolge bestimmt, welcher
             Treffer gewinnt, wenn ein Spieler mehrfach vorkommt - der
             Aufrufer uebergibt sie deshalb absteigend, damit der
             juengste (und dem Nutzer vertrauteste) Verein angezeigt wird.

    Ein Spieler muss nur in EINER Saison des Bereichs vorkommen, um
    gefunden zu werden. Das ist der fachlich entscheidende Punkt fuer
    Mehrjahresvergleiche: wer 2024/25 in einer unserer Ligen spielte und
    danach wechselte, bleibt fuer den Zeitraum 2024/25-2025/26 auffindbar.

    Ein einzelner nicht erreichbarer Wettbewerb laesst die Suche nicht
    scheitern - er fehlt dann eben.
    """
    found = {}

    for season in seasons:
        for code in league_codes:
            league_id = apisports_api.LEAGUE_IDS.get(code)
            if league_id is None:
                continue

            try:
                raw = _search_one(query, league_id, season)
            except (ApisportsUnavailable, ApisportsRateLimit):
                continue

            for entry in raw or []:
                if not isinstance(entry, dict):
                    continue

                player_id = (entry.get("player") or {}).get("id")
                if player_id is None or player_id in found:
                    # Erster Treffer gewinnt - siehe Reihenfolge oben.
                    continue

                result = _build_result(entry, code, league_id, season)
                if result is not None:
                    found[player_id] = result

    return sorted(found.values(), key=lambda item: (item["name"] or "").lower())
