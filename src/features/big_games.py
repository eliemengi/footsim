"""
Big-Game-Modell (Block F1).

Zweck
-----
Beantwortet fuer ein einzelnes Spiel zwei getrennte Fragen:

    1. Ist dieses Spiel ueberhaupt ein Big Game?      -> is_big_game()
    2. Wie stark war der Kontext dieses Spiels?       -> big_game_weight()

Und fuer eine Menge solcher Spiele:

    3. Wie hat der Spieler darin abgeschnitten?       -> aggregate_big_games()

Dieses Modul enthaelt BEWUSST keinen Netzwerkzugriff, keinen Cache und
keinen Dateizugriff - genau wie src/data/player_metrics.py und
src/features/transfer_comparison.py. Alle Eingaben kommen als einfache
Datenstrukturen herein. Dadurch ist das komplette Modell ohne Mocking
testbar.

Zwei Dimensionen, bewusst getrennt
----------------------------------
GEGNERSTAERKE  - wie stark war der Gegner in GENAU DIESER Saison?
MATCHBEDEUTUNG - wie wichtig war die Partie an sich (Runde/Phase)?

Ein Spiel kann ueber jede der beiden Dimensionen ein Big Game werden:
ein Ligaspiel gegen einen Elitegegner ebenso wie ein Finale gegen einen
Aussenseiter. Deshalb ist die Zulassung eine ODER-Verknuepfung.

Keine kuenstliche Stufe bei Rang 30/31
--------------------------------------
Die echten UEFA-Daten zeigen Saisons, in denen Rang 30 und Rang 31
DENSELBEN Koeffizienten haben (2021/22 und 2022/23: beide 53.0 bzw.
54.0). Eine Gewichtungsstufe an dieser Grenze wuerde zwei nachweislich
gleich starke Klubs unterschiedlich bewerten - das waere erfundene
Struktur.

Deshalb strikt getrennt:
    - Rang <= 30 ist eine ZULASSUNGSGRENZE (binaer, Produktentscheidung).
    - Die GEWICHTUNG selbst ist stetig und leitet sich aus dem echten
      Koeffizienten ab. Gleicher Koeffizient => gleiches Gewicht.

Kein ML
-------
Alles hier ist deterministisch und nachrechenbar. Ein Nutzer soll
nachvollziehen koennen, warum ein Spieler besser bewertet wurde.
"""

# ---------------------------------------------------------------------------
# Rundennormalisierung
# ---------------------------------------------------------------------------
#
# API-Football liefert die Runde als freien Text im Feld league.round.
# Die hier verwendeten Zeichenketten sind an ECHTEN Antworten geprueft
# (verifiziert waehrend der F1-Analyse, mehrere Saisons und Formate):
#
#   "Regular Season - 1"        Bundesliga/PL/La Liga/Ligue 1/Serie A
#   "Group Stage - 1"           CL 2021/22
#   "Group A - 2"               CL 2022/23   (Gruppenbuchstabe im String!)
#   "League Stage - 1"          CL ab 2024/25 (Reform, voellig neues Format)
#   "Knockout Round Play-offs"  CL ab 2024/25
#   "1st Qualifying Round"      CL/EL Qualifikation
#   "Round of 16"               CL K.o.
#   "Quarter-finals"            CL K.o.
#   "Semi-finals"               CL K.o.
#   "Final"                     CL Finale
#
# Wichtig: es wird NICHT mit `"Final" in round` gearbeitet - das wuerde
# "Quarter-finals" und "Semi-finals" faelschlich als Finale erkennen.
# Stattdessen wird exakt bzw. ueber eindeutige Praefixe geprueft.

STAGE_LEAGUE       = "league"          # nationale Liga, regulaerer Spieltag
STAGE_GROUP        = "group"           # Gruppen-/Ligaphase eines Wettbewerbs
STAGE_QUALIFYING   = "qualifying"      # Qualifikationsrunden
STAGE_PLAYOFF      = "playoff"         # K.o.-Playoff vor dem Achtelfinale
STAGE_ROUND_OF_16  = "round_of_16"
STAGE_QUARTERFINAL = "quarterfinal"
STAGE_SEMIFINAL    = "semifinal"
STAGE_FINAL        = "final"
STAGE_UNKNOWN      = "unknown"

# Exakte Treffer (nach Normalisierung auf Kleinbuchstaben).
_STAGE_EXACT = {
    "round of 16":              STAGE_ROUND_OF_16,
    "8th finals":               STAGE_ROUND_OF_16,   # alternative Schreibweise
    "quarter-finals":           STAGE_QUARTERFINAL,
    "quarter finals":           STAGE_QUARTERFINAL,
    "quarterfinals":            STAGE_QUARTERFINAL,
    "semi-finals":              STAGE_SEMIFINAL,
    "semi finals":              STAGE_SEMIFINAL,
    "semifinals":               STAGE_SEMIFINAL,
    "final":                    STAGE_FINAL,
    "knockout round play-offs": STAGE_PLAYOFF,
    "knockout round play offs": STAGE_PLAYOFF,
    "play-offs":                STAGE_PLAYOFF,
    "play offs":                STAGE_PLAYOFF,
    "playoffs":                 STAGE_PLAYOFF,
    "3rd place final":          STAGE_SEMIFINAL,     # Spiel um Platz 3
}

# Praefixe fuer Runden, die eine laufende Nummer bzw. einen Gruppenbuchstaben
# tragen ("Regular Season - 12", "Group A - 2", "League Stage - 7").
_STAGE_PREFIX = (
    ("regular season", STAGE_LEAGUE),
    ("league stage",   STAGE_GROUP),
    ("group stage",    STAGE_GROUP),
    ("group ",         STAGE_GROUP),
    ("qualifying",     STAGE_QUALIFYING),
)


def normalize_round(raw_round):
    """
    Bildet den Rundentext des Providers auf eine FootSim-Phase ab.

    Unbekannte Texte ergeben STAGE_UNKNOWN statt einer Exception: der
    Provider darf jederzeit neue Formate einfuehren (er hat es mit der
    CL-Reform 2024/25 nachweislich getan), und ein unbekannter Rundentext
    darf die Auswertung nicht zerlegen. Ein unbekanntes Spiel bekommt
    schlicht keinen Bedeutungsbonus.
    """
    if not raw_round or not isinstance(raw_round, str):
        return STAGE_UNKNOWN

    text = raw_round.strip().lower()
    if not text:
        return STAGE_UNKNOWN

    exact = _STAGE_EXACT.get(text)
    if exact is not None:
        return exact

    # "1st Qualifying Round", "2nd Qualifying Round", ... - die Nummer steht
    # vorne, deshalb hier ein Enthaltensein-Test auf einen eindeutigen Begriff
    # (kein generisches Fragment: "qualifying" kommt in keiner anderen Phase vor).
    if "qualifying" in text:
        return STAGE_QUALIFYING

    for prefix, stage in _STAGE_PREFIX:
        if text.startswith(prefix):
            return stage

    return STAGE_UNKNOWN


# ---------------------------------------------------------------------------
# Matchbedeutung
# ---------------------------------------------------------------------------
#
# Die Faktoren sind bewusst klein. Begruendung siehe DOMINANZ-INVARIANTE
# unten: die Turnierphase soll die Gegnerstaerke NIE ueberstimmen koennen.
# Ein Finale gegen einen schwachen Gegner darf nicht schwerer wiegen als
# ein Ligaspiel gegen den europaeischen Spitzenreiter.

IMPORTANCE_BASE = 1.00

MATCH_IMPORTANCE = {
    STAGE_LEAGUE:       1.00,
    STAGE_GROUP:        1.00,
    STAGE_QUALIFYING:   1.00,
    STAGE_UNKNOWN:      1.00,
    STAGE_PLAYOFF:      1.05,
    STAGE_ROUND_OF_16:  1.08,
    STAGE_QUARTERFINAL: 1.10,
    STAGE_SEMIFINAL:    1.12,
    STAGE_FINAL:        1.15,
}

# ---------------------------------------------------------------------------
# Wettbewerbsebene
# ---------------------------------------------------------------------------
#
# Fuer die Zulassung ueber die Bedeutung ist nicht nur die Phase wichtig,
# sondern auch WELCHER Wettbewerb. Ein Achtelfinale der Champions League
# ist ein grosses Spiel; ein Achtelfinale im nationalen Pokal gegen einen
# Zweitligisten ist es nicht. Beides traegt beim Provider aber denselben
# Rundentext "Round of 16".
#
# Deshalb zwei Ebenen. Die Zuordnung erfolgt ueber die Liga-ID, nie ueber
# den Wettbewerbsnamen - Namen variieren je Land und Saison.

TIER_EUROPEAN = "european"    # CL, EL, Conference League
TIER_DOMESTIC = "domestic"    # nationale Liga und nationaler Pokal

# Champions League, Europa League, Europa Conference League.
EUROPEAN_COMPETITION_IDS = frozenset({2, 3, 848})


def competition_tier(league_id):
    """Wettbewerbsebene anhand der API-Football-Liga-ID."""
    return TIER_EUROPEAN if league_id in EUROPEAN_COMPETITION_IDS else TIER_DOMESTIC


# K.o.-Phasen, die in einem EUROPAEISCHEN Wettbewerb allein genuegen, um
# ein Spiel zum Big Game zu machen - unabhaengig von der Gegnerstaerke.
_EUROPEAN_QUALIFYING_STAGES = frozenset({
    STAGE_PLAYOFF,
    STAGE_ROUND_OF_16,
    STAGE_QUARTERFINAL,
    STAGE_SEMIFINAL,
    STAGE_FINAL,
})

# Ein FINALE qualifiziert immer - auch im nationalen Pokal. Ein
# Pokalfinale ist unabhaengig vom Gegner ein grosses Spiel. Fruehere
# Runden desselben Wettbewerbs sind es ausdruecklich nicht.
_DOMESTIC_QUALIFYING_STAGES = frozenset({
    STAGE_FINAL,
})


def match_importance(stage):
    """Bedeutungsfaktor einer Phase. Unbekanntes bekommt den neutralen Basiswert."""
    return MATCH_IMPORTANCE.get(stage, IMPORTANCE_BASE)


def is_importance_qualified(stage, tier=TIER_EUROPEAN):
    """
    True, wenn Phase UND Wettbewerbsebene allein das Spiel zum Big Game machen.

    Der Standardwert TIER_EUROPEAN haelt aeltere Aufrufe mit nur einem
    Argument gueltig; der Produktivpfad uebergibt die Ebene immer explizit.
    """
    if tier == TIER_EUROPEAN:
        return stage in _EUROPEAN_QUALIFYING_STAGES
    return stage in _DOMESTIC_QUALIFYING_STAGES


# ---------------------------------------------------------------------------
# Gegnerstaerke
# ---------------------------------------------------------------------------
#
# Stetig und aus dem ECHTEN Koeffizienten der jeweiligen Saison abgeleitet,
# nicht aus dem Rang. Grund: der Rang ist nur eine Ordnungszahl ueber einer
# in Wahrheit kontinuierlichen Groesse. Rang 1 und 2 koennen praktisch
# gleich stark sein, Rang 5 und 6 weit auseinander liegen.
#
# Normalisiert wird innerhalb der Spannweite DERSELBEN Saison. Damit ist
# das Ergebnis unabhaengig von der absoluten Koeffizienteninflation ueber
# die Jahre (die Werte steigen langfristig) und immer zwischen den beiden
# Grenzen unten.

OPPONENT_STRENGTH_FLOOR = 1.00   # schwaechster Klub der Top-40-Liste
OPPONENT_STRENGTH_CEILING = 1.50  # staerkster Klub der Top-40-Liste

# Gegner ohne verwertbares Ranking (nicht in den Top 40, unbekannte
# Identitaet, fehlender Snapshot) bekommen den neutralen Basiswert. Nie
# weniger: ein schwacher Gegner wird nicht ABgewertet, ein starker
# lediglich AUFgewertet.
OPPONENT_STRENGTH_UNKNOWN = OPPONENT_STRENGTH_FLOOR

# Zulassungsgrenze (Produktentscheidung, siehe Modulkopf). Ein Gegner
# innerhalb der Top 30 macht ein Spiel fuer sich genommen zum Big Game.
OPPONENT_ELIGIBLE_MAX_RANK = 30


def opponent_strength(coefficient, min_coefficient, max_coefficient):
    """
    Stetiger Gegnerstaerkefaktor zwischen FLOOR und CEILING.

    coefficient      UEFA-Koeffizient des Gegners in der betreffenden Saison
    min_/max_        Spannweite derselben Saisonliste

    Gleicher Koeffizient ergibt garantiert denselben Faktor - das ist die
    zentrale Eigenschaft, wegen der hier nicht mit dem Rang gerechnet wird.

    Rueckgabe OPPONENT_STRENGTH_UNKNOWN, wenn kein Koeffizient vorliegt
    oder die Spannweite unbrauchbar ist (alle Klubs gleichauf) - dann ist
    eine relative Einordnung schlicht nicht moeglich.
    """
    if coefficient is None or min_coefficient is None or max_coefficient is None:
        return OPPONENT_STRENGTH_UNKNOWN

    span = max_coefficient - min_coefficient
    if span <= 0:
        return OPPONENT_STRENGTH_UNKNOWN

    share = (coefficient - min_coefficient) / span
    # Ausserhalb der Liste liegende Werte werden nicht extrapoliert.
    share = max(0.0, min(1.0, share))

    return OPPONENT_STRENGTH_FLOOR + (OPPONENT_STRENGTH_CEILING - OPPONENT_STRENGTH_FLOOR) * share


def is_opponent_qualified(rank):
    """True, wenn der Gegner allein das Spiel zum Big Game macht."""
    if rank is None:
        return False
    return rank <= OPPONENT_ELIGIBLE_MAX_RANK


# ---------------------------------------------------------------------------
# DOMINANZ-INVARIANTE
# ---------------------------------------------------------------------------
#
# Die Bedeutung darf die Gegnerstaerke nie ueberstimmen:
#
#     staerkster Gegner, belangloses Spiel  = 1.50 * 1.00 = 1.50
#     schwaechster Gegner, Finale           = 1.00 * 1.15 = 1.15
#
# Solange der groesste Bedeutungsfaktor unter dem groessten
# Gegnerstaerkefaktor liegt, kann ein Finale gegen einen Aussenseiter nie
# schwerer wiegen als ein Spiel gegen den staerksten Klub Europas. Diese
# Eigenschaft wird in den Tests ausdruecklich geprueft, damit eine spaetere
# Neukalibrierung sie nicht unbemerkt bricht.
MAX_COMBINED_WEIGHT = OPPONENT_STRENGTH_CEILING * max(MATCH_IMPORTANCE.values())


def big_game_weight(strength, importance):
    """
    Kontextgewicht eines Spiels: Gegnerstaerke MAL Bedeutung.

    Multiplikativ statt additiv, damit beide Dimensionen ihren relativen
    Charakter behalten und die Dominanz-Invariante oben gilt.
    """
    return strength * importance


# ---------------------------------------------------------------------------
# Mindestumfang
# ---------------------------------------------------------------------------
#
# Ein Spieler mit 90 Minuten und zwei Toren darf nicht automatisch besser
# dastehen als einer mit 3000 Minuten und 25 Toren. Unterhalb dieser
# Schwellen werden die Rohwerte weiterhin gezeigt (Transparenz), aber
# KEIN Big Game Score gebildet - genau wie der bestehende Radar unterhalb
# von DEFAULT_MIN_MINUTES kein Perzentil vergibt.

MIN_BIG_GAMES = 3
MIN_BIG_GAME_MINUTES = 180


def has_sufficient_sample(match_count, minutes):
    """True, wenn genug Datengrundlage fuer einen belastbaren Score vorliegt."""
    return (match_count or 0) >= MIN_BIG_GAMES and (minutes or 0) >= MIN_BIG_GAME_MINUTES


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _num(value):
    """Zahl oder None. None bleibt None und wird NIE zu 0 umgedeutet."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                       # NaN
        return None
    return number


def _sum_optional(values):
    """
    Summe ueber Werte, die None sein duerfen.

    Rueckgabe None, wenn KEIN einziger Wert vorlag - dann ist die Kennzahl
    fuer diesen Spieler nicht erhoben und eine 0 waere eine
    Tatsachenbehauptung, die wir nicht haben.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present)


def _goal_assist_contribution(goals, assists):
    """Direkte G+A-Produktion mit der festen Regel: ein Tor = ein Assist.

    Der Helfer wird sowohl fuer den rohen G+A-Wert als auch fuer die
    kontextgewichtete Produktion benutzt. So kann die nationale Erweiterung
    keine abweichende Assist-Bewertung einschleusen und fehlende Providerwerte
    bleiben weiterhin von echten Nullen unterscheidbar.
    """
    goal_value = _num(goals)
    assist_value = _num(assists)
    if goal_value is None and assist_value is None:
        return None
    return (goal_value or 0.0) + (assist_value or 0.0)


def aggregate_big_games(entries):
    """
    Fasst die Big Games eines Spielers zu einem Ergebnis zusammen.

    entries: Liste von Dicts je Spiel, jeweils mit
        weight    Kontextgewicht des Spiels (big_game_weight)
        strength  Gegnerstaerkefaktor
        minutes   gespielte Minuten (kann None sein)
        rating    Spielerbewertung des Providers (kann None sein)
        goals / assists / shots_total / shots_on / passes_key /
        passes_total / passes_accuracy / tackles / interceptions /
        duels_total / duels_won / dribbles_attempts / dribbles_success /
        saves / goals_conceded  (jeweils optional)

    ROHWERTE BLEIBEN ROH. Tore werden gezaehlt, nie gewichtet. Das
    Kontextgewicht fliesst ausschliesslich in die ausdruecklich als
    kontextgewichtet gekennzeichneten Felder ein.
    """
    played = [e for e in entries if (e.get("minutes") or 0) > 0]

    total_minutes = sum(e.get("minutes") or 0 for e in played)
    match_count = len(played)

    raw = {
        "matches": match_count,
        "minutes": total_minutes,
        "goals":             _sum_optional([e.get("goals") for e in played]),
        "assists":           _sum_optional([e.get("assists") for e in played]),
        "goal_assists": _sum_optional([
            _goal_assist_contribution(e.get("goals"), e.get("assists"))
            for e in played
        ]),
        "shots_total":       _sum_optional([e.get("shots_total") for e in played]),
        "shots_on":          _sum_optional([e.get("shots_on") for e in played]),
        "passes_key":        _sum_optional([e.get("passes_key") for e in played]),
        "passes_total":      _sum_optional([e.get("passes_total") for e in played]),
        "tackles":           _sum_optional([e.get("tackles") for e in played]),
        "interceptions":     _sum_optional([e.get("interceptions") for e in played]),
        "duels_total":       _sum_optional([e.get("duels_total") for e in played]),
        "duels_won":         _sum_optional([e.get("duels_won") for e in played]),
        "dribbles_attempts": _sum_optional([e.get("dribbles_attempts") for e in played]),
        "dribbles_success":  _sum_optional([e.get("dribbles_success") for e in played]),
        "saves":             _sum_optional([e.get("saves") for e in played]),
        "goals_conceded":    _sum_optional([e.get("goals_conceded") for e in played]),
    }

    # Bewertete Einsaetze als (Bewertung, Minuten, Kontextgewicht). Einmal
    # gebaut und danach fuer Durchschnittsbewertung UND Score benutzt -
    # zwei getrennte Durchlaeufe muessten sonst exakt dieselbe Filterung
    # wiederholen, und genau dort entstehen stille Zuordnungsfehler.
    rated = [
        (_num(e.get("rating")), e.get("minutes") or 0, e.get("weight") or 1.0)
        for e in played
        if _num(e.get("rating")) is not None and (e.get("minutes") or 0) > 0
    ]

    # Durchschnittliche Bewertung, nach Einsatzzeit gewichtet (ein
    # Kurzeinsatz soll nicht so schwer wiegen wie 90 Minuten).
    rating_minutes = sum(m for _, m, _w in rated)
    avg_rating = (sum(r * m for r, m, _w in rated) / rating_minutes) if rating_minutes else None

    # Durchschnittlich erlebter Kontext - beantwortet "wie stark war die
    # Gegnerschaft?" und macht den Score nachvollziehbar.
    weighted_minutes = sum((e.get("weight") or 1.0) * (e.get("minutes") or 0) for e in played)
    avg_weight = (weighted_minutes / total_minutes) if total_minutes else None
    avg_strength = (
        sum((e.get("strength") or 1.0) * (e.get("minutes") or 0) for e in played) / total_minutes
        if total_minutes else None
    )

    # ---- Kontextgewichtete Kennzahlen (ausdruecklich KEINE Rohwerte) ----
    #
    # Big Game Score = einsatzzeitgewichteter Mittelwert von
    #                  (Bewertung x Kontextgewicht des jeweiligen Spiels).
    #
    # Steigt sowohl mit besserer Leistung als auch mit staerkerem Kontext -
    # damit beantwortet er genau die Ausgangsfrage ("wer hat in den
    # groessten Spielen gegen die staerksten Gegner geliefert?"), ohne eine
    # einzige Rohstatistik zu veraendern. Zwei Spieler mit identischer
    # Leistung in identischem Kontext bekommen zwingend denselben Wert.
    big_game_score = None
    if has_sufficient_sample(match_count, total_minutes) and rating_minutes:
        big_game_score = (
            sum((r * w) * m for r, m, w in rated) / rating_minutes
        )

    # Gewichtete Torbeteiligungen je 90 Minuten. Ebenfalls ausdruecklich
    # gekennzeichnet - "4 Tore" bleiben an jeder anderen Stelle 4 Tore.
    weighted_involvement_per90 = None
    if total_minutes > 0:
        contributions = [
            _goal_assist_contribution(e.get("goals"), e.get("assists"))
            for e in played
        ]
        weighted_contributions = [
            contribution * (entry.get("weight") or 1.0)
            for entry, contribution in zip(played, contributions)
            if contribution is not None
        ]
        if weighted_contributions:
            weighted_involvement_per90 = (
                sum(weighted_contributions) / (total_minutes / 90.0)
            )

    return {
        "raw": raw,
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "avg_opponent_strength": round(avg_strength, 3) if avg_strength is not None else None,
        "avg_context_weight": round(avg_weight, 3) if avg_weight is not None else None,
        "big_game_score": round(big_game_score, 2) if big_game_score is not None else None,
        "weighted_involvement_per90": (
            round(weighted_involvement_per90, 3) if weighted_involvement_per90 is not None else None
        ),
        # Klarer Alias fuer die UI/Verbraucher. Der historische Feldname
        # bleibt zurueckwaertskompatibel erhalten.
        "weighted_goal_assists_per90": (
            round(weighted_involvement_per90, 3) if weighted_involvement_per90 is not None else None
        ),
        "sufficient_sample": has_sufficient_sample(match_count, total_minutes),
        "min_matches": MIN_BIG_GAMES,
        "min_minutes": MIN_BIG_GAME_MINUTES,
    }
