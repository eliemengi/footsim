"""
Wettbewerbstaxonomie: Was ist ein Pflichtspiel, und welcher Art?

WARUM ES DIESES MODUL GIBT
--------------------------
Die Einordnung eines Wettbewerbs lag bisher in einer Heuristik
(player_compare_loader._infer_comp_type), die zuerst prueft, ob eine
Liga-ID in apisports_api.LEAGUE_IDS steht. Dort stehen aber auch
Supercups - sie sind dort eingetragen, weil man sie irgendwann einmal
abrufen wollte, nicht weil sie Ligen waeren.

Die Folge war eine Aufteilung, die niemand beabsichtigt hat. Am
gespeicherten Stand nachgemessen:

    529 Super Cup            Deutschland   -> "league" -> NICHT in club_all
    528 Community Shield     England       -> "league" -> NICHT in club_all
    531 UEFA Super Cup       Welt          -> "league" -> NICHT in club_all
    556 Super Cup            Spanien       -> "cup"    -> in club_all
    547 Super Cup            Italien       -> "cup"    -> in club_all
    526 Trophee des Champions Frankreich   -> "cup"    -> in club_all
    667 Friendlies Clubs     Welt          -> "cup"    -> in club_all

Drei Supercups fielen also aus "Alle Vereinswettbewerbe" heraus, drei
andere waren drin - und Klubfreundschaftsspiele zaehlten wie
Pflichtspiele mit. Beides ist falsch, und beides entstand aus derselben
Ursache: Der Typ eines Wettbewerbs wurde an mehreren Stellen aus Namen
und ID erraten, statt einmal benannt zu werden.

ALLE IDS SIND BELEGT
--------------------
Jede ID unten stammt aus den lokal gespeicherten Anbieterantworten
(data/cache/apisports__playerprofile__*), zusammen mit Name und Land.
Keine ID ist geraten. Die Zahl in Klammern ist die Anzahl der Bloecke,
in denen der Wettbewerb dort real vorkommt.

WAS BEI UNBEKANNTEN WETTBEWERBEN PASSIERT
-----------------------------------------
Sie werden UNKNOWN und gelten NICHT als Pflichtspiel. Das ist die
vorsichtige Richtung: Ein unbekannter Wettbewerb, der faelschlich
mitzaehlt, verfaelscht stillschweigend jede Statistik; einer, der fehlt,
ist eine sichtbare Luecke. Die Namensheuristik unten fuellt die
haeufigen Faelle, und was uebrig bleibt, wird gezaehlt und ist ueber
unknown_competition_report() sichtbar.
"""


# ---------------------------------------------------------------------------
# Kategorien
# ---------------------------------------------------------------------------

DOMESTIC_LEAGUE = "domestic_league"
DOMESTIC_CUP = "domestic_cup"
DOMESTIC_SUPERCUP = "domestic_supercup"
CONTINENTAL_CUP = "continental_cup"
CONTINENTAL_SUPERCUP = "continental_supercup"
CLUB_WORLD_COMPETITION = "club_world_competition"
CLUB_FRIENDLY = "club_friendly"
NATIONAL_COMPETITION = "national_competition"
NATIONAL_FRIENDLY = "national_friendly"
UNKNOWN = "unknown"

CATEGORIES = (
    DOMESTIC_LEAGUE, DOMESTIC_CUP, DOMESTIC_SUPERCUP,
    CONTINENTAL_CUP, CONTINENTAL_SUPERCUP, CLUB_WORLD_COMPETITION,
    CLUB_FRIENDLY, NATIONAL_COMPETITION, NATIONAL_FRIENDLY, UNKNOWN,
)

#: Kategorien, die ein Vereins-PFLICHTSPIEL bezeichnen.
#:
#: Das ist die Menge, die "Alle Vereinswettbewerbe" ausmacht. Ein
#: Freundschaftsspiel steht bewusst nicht darin: Es hat kein Ergebnis, das
#: fuer irgendetwas zaehlt, wird mit Probeaufstellungen bestritten und
#: wuerde Pro-90-Werte verwaessern.
CLUB_COMPETITIVE = frozenset({
    DOMESTIC_LEAGUE, DOMESTIC_CUP, DOMESTIC_SUPERCUP,
    CONTINENTAL_CUP, CONTINENTAL_SUPERCUP, CLUB_WORLD_COMPETITION,
})

#: Kategorien der Nationalmannschaft.
NATIONAL_CATEGORIES = frozenset({NATIONAL_COMPETITION, NATIONAL_FRIENDLY})

#: Supercup-Kategorien - fuer Big Games und Diagnose.
SUPERCUP_CATEGORIES = frozenset({DOMESTIC_SUPERCUP, CONTINENTAL_SUPERCUP})


# ---------------------------------------------------------------------------
# Belegte Wettbewerbs-IDs
# ---------------------------------------------------------------------------

#: Nationale Supercups der fuenf unterstuetzten Ligen.
#:
#: Alle sechs Eintraege sind aus dem lokalen Antwortcache belegt
#: (ID, Name, Land), nicht geraten:
#:
#:     529  "Super Cup"              Germany       (62 Bloecke)
#:     528  "Community Shield"       England      (113 Bloecke)
#:     556  "Super Cup"              Spain        (151 Bloecke)
#:     547  "Super Cup"              Italy        (144 Bloecke)
#:     526  "Trophee des Champions"  France        (85 Bloecke)
DOMESTIC_SUPERCUP_IDS = {
    529: ("Germany", "bl1"),
    528: ("England", "pl"),
    556: ("Spain", "pd"),
    547: ("Italy", "sa"),
    526: ("France", "fl1"),
}

#: Kontinentaler Supercup. Belegt: 531 "UEFA Super Cup", World (161 Bloecke).
CONTINENTAL_SUPERCUP_IDS = {531: "UEFA Super Cup"}

#: Die fuenf Vergleichsligen.
DOMESTIC_LEAGUE_IDS = {78: "bl1", 39: "pl", 140: "pd", 135: "sa", 61: "fl1"}

#: Nationale Hauptpokale der fuenf Laender. Belegt ueber den Cache und
#: deckungsgleich mit src/data/domestic_cup_loader.DOMESTIC_CUPS.
DOMESTIC_CUP_IDS = {81: "bl1", 45: "pl", 143: "pd", 137: "sa", 66: "fl1"}

#: Europapokal-Hauptwettbewerbe.
CONTINENTAL_CUP_IDS = {2: "UEFA Champions League",
                       3: "UEFA Europa League",
                       848: "UEFA Europa Conference League"}

#: Klub-Weltwettbewerbe.
CLUB_WORLD_IDS = {15: "FIFA Club World Cup"}

#: Freundschaftsspiele. Belegt:
#:     667  "Friendlies Clubs"  World  (2.723 Bloecke)  -> Vereine
#:      10  "Friendlies"        World  (2.952 Bloecke)  -> Nationalmannschaft
#:
#: Die Trennung ist wesentlich: Ein Klubtestspiel gehoert aus den
#: Vereinsstatistiken heraus, ein Laenderspiel-Testspiel bleibt im
#: Nationalmannschafts-Scope, wo es hingehoert.
CLUB_FRIENDLY_IDS = {667: "Friendlies Clubs"}
NATIONAL_FRIENDLY_IDS = {10: "Friendlies"}

#: Nationalmannschafts-Pflichtwettbewerbe, die im Projekt vorkommen.
NATIONAL_COMPETITION_IDS = {
    1: "World Cup",
    4: "Euro Championship",
    5: "UEFA Nations League",
    6: "Africa Cup of Nations",
    9: "Copa America",
    32: "World Cup - Qualification Europe",
    34: "World Cup - Qualification",
    960: "Euro Championship - Qualification",
}

#: Namensbausteine als Rueckfallebene fuer nicht gelistete Wettbewerbe.
#: Reihenfolge ist Absicht - siehe classify().
_SUPERCUP_TOKENS = ("super cup", "supercup", "supercoppa", "supercopa",
                    "super copa", "trophee des champions",
                    "trophée des champions", "community shield",
                    "supercupa", "super liga cup")
_CLUB_FRIENDLY_TOKENS = ("friendlies clubs", "club friendly", "friendly clubs")
_NATIONAL_TOKENS = ("world cup", "euro championship", "nations league",
                    "copa america", "africa cup of nations", "gold cup",
                    "asian cup", "confederations cup", "olympics")
_CUP_TOKENS = ("cup", "pokal", "coupe", "coppa", "copa", "trophy", "shield",
               "beker", "taca", "taça")

#: Nicht zuordenbare Wettbewerbe - rein diagnostisch.
UNKNOWN_COMPETITIONS = {}


def _text(value):
    return (str(value) if value is not None else "").strip().lower()


def classify(league):
    """
    Kategorie eines Wettbewerbs aus seinem league-Block.

    league: der "league"-Block einer API-Sports-Antwort
            ({"id":, "name":, "country":, "type":})

    Die Reihenfolge der Pruefungen ist Absicht:

      1. Belegte IDs. Sie sind eindeutig und schlagen jede Heuristik.
      2. Freundschaftsspiele. VOR den Supercups, weil ein Testspiel
         gelegentlich einen Turniernamen traegt.
      3. Supercups. VOR den allgemeinen Pokalbegriffen, weil "Super Cup"
         das Wort "cup" enthaelt und sonst als normaler Pokal durchginge.
      4. Nationalmannschaftsbegriffe. Ebenfalls vor "cup", weil "World
         Cup" sonst ein Vereinspokal waere.
      5. Pokalbegriffe.
      6. Sonst: UNKNOWN, und der Name wird mitgezaehlt.
    """
    league = league or {}
    lid = league.get("id")
    name = _text(league.get("name"))
    land = _text(league.get("country"))

    if lid in DOMESTIC_LEAGUE_IDS:
        return DOMESTIC_LEAGUE
    if lid in DOMESTIC_SUPERCUP_IDS:
        return DOMESTIC_SUPERCUP
    if lid in CONTINENTAL_SUPERCUP_IDS:
        return CONTINENTAL_SUPERCUP
    if lid in DOMESTIC_CUP_IDS:
        return DOMESTIC_CUP
    if lid in CONTINENTAL_CUP_IDS:
        return CONTINENTAL_CUP
    if lid in CLUB_WORLD_IDS:
        return CLUB_WORLD_COMPETITION
    if lid in CLUB_FRIENDLY_IDS:
        return CLUB_FRIENDLY
    if lid in NATIONAL_FRIENDLY_IDS:
        return NATIONAL_FRIENDLY
    if lid in NATIONAL_COMPETITION_IDS:
        return NATIONAL_COMPETITION

    if not name:
        _note_unknown(lid, league.get("name"))
        return UNKNOWN

    if any(token in name for token in _CLUB_FRIENDLY_TOKENS):
        return CLUB_FRIENDLY
    if name == "friendlies":
        # Ohne weitere Angabe ist "Friendlies" bei diesem Anbieter der
        # Laenderspielkalender; die Vereinsvariante heisst ausdruecklich
        # "Friendlies Clubs".
        return NATIONAL_FRIENDLY

    if any(token in name for token in _SUPERCUP_TOKENS):
        # Ein Supercup ohne Landesangabe laesst sich nicht einer der fuenf
        # Ligen zuordnen - er bleibt trotzdem ein Supercup und damit ein
        # Pflichtspiel.
        return DOMESTIC_SUPERCUP if land else CONTINENTAL_SUPERCUP

    if any(token in name for token in _NATIONAL_TOKENS):
        return NATIONAL_COMPETITION

    if any(token in name for token in _CUP_TOKENS):
        return DOMESTIC_CUP

    _note_unknown(lid, league.get("name"))
    return UNKNOWN


def _note_unknown(lid, name):
    schluessel = f"{lid}:{name}"
    UNKNOWN_COMPETITIONS[schluessel] = UNKNOWN_COMPETITIONS.get(schluessel, 0) + 1


def unknown_competition_report():
    """Welche Wettbewerbe konnten nicht eingeordnet werden?"""
    return dict(sorted(UNKNOWN_COMPETITIONS.items(), key=lambda kv: -kv[1]))


def is_club_competitive(league):
    """Ist das ein Vereins-Pflichtspiel? Freundschaftsspiele: nein."""
    return classify(league) in CLUB_COMPETITIVE


def is_national(league):
    """Gehoert der Wettbewerb zur Nationalmannschaft?"""
    return classify(league) in NATIONAL_CATEGORIES


def is_supercup(league):
    """Nationaler oder kontinentaler Supercup?"""
    return classify(league) in SUPERCUP_CATEGORIES


def supercup_ids():
    """Alle belegten Supercup-IDs - fuer Big Games und Tests."""
    return set(DOMESTIC_SUPERCUP_IDS) | set(CONTINENTAL_SUPERCUP_IDS)


def taxonomy_report():
    """
    Uebersicht der eingeordneten Wettbewerbe. Fuer Diagnosebefehle.

    Enthaelt nur IDs und Namen - keine Pfade, keine Schluessel.
    """
    return {
        "domestic_leagues": dict(DOMESTIC_LEAGUE_IDS),
        "domestic_cups": dict(DOMESTIC_CUP_IDS),
        "domestic_supercups": {k: v[0] for k, v in DOMESTIC_SUPERCUP_IDS.items()},
        "continental_cups": dict(CONTINENTAL_CUP_IDS),
        "continental_supercups": dict(CONTINENTAL_SUPERCUP_IDS),
        "club_world": dict(CLUB_WORLD_IDS),
        "club_friendlies": dict(CLUB_FRIENDLY_IDS),
        "national_friendlies": dict(NATIONAL_FRIENDLY_IDS),
        "unknown_seen": unknown_competition_report(),
    }
