"""
Zuordnung von Team-IDs zwischen den beiden Datenquellen.

WARUM DAS NOETIG IST
--------------------
FootSim bezieht Ligen und Champions League von football-data.org, die
nationalen Pokale (seit GO 2) von API-Sports. Beide vergeben eigene
Team-IDs:

    FC Bayern Muenchen -> football-data 5, API-Sports 157

Das Projekt haelt bislang bewusst fest: "Ein ID-Raum, kein Crosswalk"
(src/api/team_detail.py). Fuer Belastungsrechnungen reicht das nicht:
Ohne Zuordnung liesse sich ein Pokalspiel keinem Ligateam zuschreiben,
und genau diese Mittwochsspiele sind der Grund, warum Belastung ueberhaupt
gemessen wird.

WIE ZUGEORDNET WIRD
-------------------
1. Explizite Alias-Tabelle (unten) - hat immer Vorrang.
2. Normalisierter Name INNERHALB einer Liga und Saison.

Der zweite Punkt ist eng gefuehrt und deshalb vertretbar: verglichen wird
nicht "irgendein Name gegen irgendeinen", sondern die 18-20 Vereine einer
Liga in einer Saison gegen dieselbe Liga beim anderen Anbieter. Bleibt ein
Name mehrdeutig, wird er NICHT zugeordnet, sondern als Konflikt gemeldet.

Ausdruecklich nicht: unscharfes Matching, Zusammenfuehren ueber
Ligagrenzen, Verwechslung von Jugend-, Frauen- oder Reserveteams.

FA-CUP-SONDERFALL
-----------------
Der FA Cup enthaelt ueber 800 Spiele pro Saison, viele davon zwischen
unterklassigen Vereinen. Diese Teams stehen in keiner Top-5-Liga und
bekommen deshalb keine Zuordnung. Ein Spiel zaehlt nur, wenn MINDESTENS
EIN Team sicher zugeordnet ist - der unterklassige Gegner bleibt einfach
ohne interne ID stehen, statt geraten zu werden.
"""

import unicodedata

from src.data.historical_loader import LEAGUE_CODES, load_season


#: Schreibweisen, die sich zwischen den Anbietern unterscheiden und die
#: eine reine Normalisierung nicht zusammenbringt.
#:
#: Format: (liga, normalisierter_apisports_name) -> normalisierter_fd_name
#: Jeder Eintrag ist eine bewusste, nachvollziehbare Ausnahme.
EXPLICIT_ALIASES = {
    # Format: (liga, normalisierter_apisports_name) -> normalisierter_fd_name
    #
    # ACHTUNG RICHTUNG: Der Wert ist der NORMALISIERTE Name der
    # football-data-Seite, nicht die Rohschreibweise. "RC Celta de Vigo"
    # normalisiert zu "celta vigo", weil "rc" und "de" als Rauschwoerter
    # entfallen - der Alias muss also auf "celta vigo" zeigen, nicht auf
    # den Rohnamen. Eine Tabelle mit Rohnamen greift schlicht nie.
    #
    # Es stehen hier nur Faelle, die die Normalisierung und die
    # Teilmengenregel nachweislich nicht zusammenbringen. Jeder Eintrag
    # wurde gegen die tatsaechlichen Schreibweisen beider Anbieter
    # geprueft, nicht geraten.

    # API-Sports fuehrt die Kurzform, football-data den Rechtsnamen.
    # Keine Teilmenge, weil sich die Woerter unterscheiden.
    ("pl", "wolves"): "wolverhampton wanderers",
    ("fl1", "lyon"): "olympique lyonnais",
    ("fl1", "rennes"): "stade rennais 1901",

    # Verkuerzung, die keine Teilmenge ist: "Inter" ist kein Wort aus
    # "Internazionale Milano", sondern dessen Abkuerzung.
    ("sa", "inter"): "internazionale milano",
}

#: Fuer Atletico Madrid und Celta Vigo braucht es KEINEN Eintrag: nach
#: dem Entfernen der Rauschwoerter ("de", "rc", "club") stimmen beide
#: Seiten exakt ueberein. Ein frueherer Eintrag zeigte hier sogar in die
#: falsche Richtung und verhinderte die Zuordnung aktiv - Aliase, die
#: nichts tun, sind nicht harmlos, sondern koennen die Normalisierung
#: ueberschreiben.

#: Wortbestandteile, die keine Identitaet tragen und vor dem Vergleich
#: entfernt werden. Bewusst konservativ: "united" oder "city" bleiben,
#: weil sie Vereine unterscheiden (Manchester United vs Manchester City).
NOISE_TOKENS = frozenset({
    "fc", "cf", "sc", "ac", "as", "sv", "tsg", "vfb", "vfl", "bsc", "fsv",
    "sge", "rc", "cd", "ud", "rcd", "ss", "us", "aс", "club", "calcio",
    "de", "the", "1899", "1904", "1846", "05", "04", "96", "poule",
})


def _normalize(name):
    """
    Vereinsname auf eine vergleichbare Form bringen.

    Akzente werden gefaltet, Rauschwoerter entfernt, Rest alphabetisch
    stabil zusammengesetzt. "FC Bayern Muenchen" und "Bayern München"
    landen so beide auf "bayern munchen".
    """
    if not name:
        return ""

    zerlegt = unicodedata.normalize("NFKD", str(name))
    ohne_akzente = "".join(c for c in zerlegt if not unicodedata.combining(c))

    bereinigt = []
    for zeichen in ohne_akzente.lower():
        bereinigt.append(zeichen if zeichen.isalnum() or zeichen.isspace() else " ")

    tokens = [t for t in "".join(bereinigt).split() if t and t not in NOISE_TOKENS]
    return " ".join(tokens)


def _league_teams_football_data(league_key, season):
    """Vereine einer Liga laut football-data (aus der lokalen Historie)."""
    api_code = LEAGUE_CODES.get(league_key)
    if not api_code:
        return {}

    payload = load_season(api_code, season)
    if not payload:
        return {}

    teams = {}
    for tid, info in (payload.get("teams") or {}).items():
        name = (info or {}).get("name") or (info or {}).get("short_name")
        if name:
            teams[int(tid)] = name
    return teams


def build_crosswalk(league_key, season, apisports_teams):
    """
    Ordnet API-Sports-Team-IDs den football-data-IDs einer Liga zu.

    apisports_teams: {team_id: name} - typischerweise die Vereine aus
                     einer Pokaldatei oder aus league_team_ids().

    Rueckgabe:
        {
          "mapping":    {apisports_id: football_data_id},
          "reverse":    {football_data_id: apisports_id},
          "unmapped":   [{"id":, "name":, "normalized":}],
          "ambiguous":  [{"normalized":, "candidates": [...]}],
          "aliases_used": [...],
          "duplicates": [...],
          "league": league_key, "season": season,
          "mapped_count":, "source_count":,
        }

    Die Diagnosefelder sind kein Beiwerk: ohne sie liesse sich ein
    fehlendes Pokalspiel nicht von einem fehlgeschlagenen Mapping
    unterscheiden.
    """
    fd_teams = _league_teams_football_data(league_key, season)

    # football-data-Seite nach normalisiertem Namen indizieren.
    fd_nach_name = {}
    fd_mehrdeutig = set()
    for fd_id, name in fd_teams.items():
        norm = _normalize(name)
        if norm in fd_nach_name:
            fd_mehrdeutig.add(norm)
        fd_nach_name.setdefault(norm, []).append(fd_id)

    mapping = {}
    reverse = {}
    unmapped = []
    ambiguous = []
    aliases_used = []
    duplicates = []

    for as_id, as_name in sorted((apisports_teams or {}).items()):
        norm = _normalize(as_name)

        alias = EXPLICIT_ALIASES.get((league_key, norm))
        if alias:
            norm = alias
            aliases_used.append({"apisports_id": as_id, "name": as_name,
                                 "alias": alias})

        kandidaten = fd_nach_name.get(norm) or []

        if not kandidaten:
            # ZWEITE STUFE: Token-Teilmenge innerhalb DIESER Liga und
            # Saison. Die Anbieter kuerzen unterschiedlich stark -
            # "Olympique de Marseille" gegen "Marseille", "SSC Napoli"
            # gegen "Napoli".
            #
            # NUR EINE RICHTUNG IST ZULAESSIG: der gesuchte Name muss
            # eine Teilmenge des Ligateams sein, also die KUERZERE
            # Schreibweise. Die Gegenrichtung waere gefaehrlich, denn
            # zusaetzliche Woerter bezeichnen in aller Regel einen
            # ANDEREN Verein:
            #
            #     "City of Liverpool"    ist nicht Liverpool FC
            #     "United of Manchester" ist nicht Manchester United
            #     "South Liverpool"      ist nicht Liverpool FC
            #
            # Das sind reale Gegner aus dem FA Cup, allesamt
            # unterklassig. Die Gegenrichtung zuzulassen hiesse genau
            # das zu tun, was hier verboten ist: einen Unterklassigen in
            # ein Top-5-Team hineinzuraten.
            #
            # Das ist auch mit dieser Einschraenkung KEIN unscharfes
            # Matching: verglichen werden ganze Woerter, der Suchraum
            # sind die 18-20 Vereine einer Liga in einer Saison, und bei
            # mehr als einem Treffer wird abgelehnt statt geraten.
            gesucht = set(norm.split())
            if gesucht:
                treffer = [
                    ids[0] for kandidat, ids in fd_nach_name.items()
                    if len(ids) == 1 and kandidat
                    and gesucht < set(kandidat.split())
                ]
                if len(treffer) == 1:
                    kandidaten = treffer
                elif len(treffer) > 1:
                    ambiguous.append({"apisports_id": as_id, "name": as_name,
                                      "normalized": norm, "candidates": treffer})
                    continue

        if len(kandidaten) > 1 or norm in fd_mehrdeutig:
            # Mehrdeutig: lieber gar nicht zuordnen als falsch.
            ambiguous.append({"apisports_id": as_id, "name": as_name,
                              "normalized": norm, "candidates": list(kandidaten)})
            continue

        if not kandidaten:
            unmapped.append({"id": as_id, "name": as_name, "normalized": norm})
            continue

        fd_id = kandidaten[0]
        if fd_id in reverse:
            # Zwei API-Sports-Teams auf dasselbe football-data-Team:
            # ein Konflikt, der gemeldet und nicht stillschweigend
            # ueberschrieben wird.
            duplicates.append({"football_data_id": fd_id,
                               "apisports_ids": [reverse[fd_id], as_id],
                               "name": as_name})
            continue

        mapping[as_id] = fd_id
        reverse[fd_id] = as_id

    return {
        "league": league_key,
        "season": season,
        "mapping": mapping,
        "reverse": reverse,
        "unmapped": unmapped,
        "ambiguous": ambiguous,
        "aliases_used": aliases_used,
        "duplicates": duplicates,
        "mapped_count": len(mapping),
        "source_count": len(apisports_teams or {}),
        "target_count": len(fd_teams),
    }


def crosswalk_report(results):
    """
    Verdichtet mehrere Crosswalk-Ergebnisse zu einer Diagnoseuebersicht.

    Enthaelt bewusst nur Vereinsnamen und IDs - keine Schluessel, keine
    Pfade, keine Anbieterantworten.
    """
    zeilen = []
    for r in results:
        zeilen.append({
            "league": r["league"],
            "season": r["season"],
            "mapped": r["mapped_count"],
            "of_source": r["source_count"],
            "target_teams": r["target_count"],
            "unmapped": len(r["unmapped"]),
            "ambiguous": len(r["ambiguous"]),
            "duplicates": len(r["duplicates"]),
            "aliases_used": len(r["aliases_used"]),
        })
    return zeilen
