"""
Metrik-Katalog und Positionslogik fuer den Spielervergleich (Phase 3).

Dieses Modul enthaelt BEWUSST keinen API-Zugriff und keinen Cache.
Es definiert nur:
    - welche Positionsgruppen es gibt,
    - welche Kennzahlen je Gruppe sinnvoll sind,
    - wie Rohwerte in Per-90-Werte und Quoten umgerechnet werden.

Dadurch ist die gesamte fachliche Logik ohne Netzwerk testbar.

Grundregeln (siehe docs/player_comparison.md):
    1. Ein fehlender Wert ist None, niemals 0.
    2. Es wird nichts geschaetzt und nichts erfunden.
    3. Kennzahlen, die API-Sports nicht liefert (xG, xA, progressive Paesse,
       Pressures, Trackingdaten), existieren hier nicht.
    4. Weniger, gut erklaerte Kennzahlen schlagen viele unklare.
"""


# ---------------------------------------------------------------------------
# Positionsgruppen
# ---------------------------------------------------------------------------
#
# API-Sports liefert unter statistics[n].games.position ausschliesslich
# diese vier Werte. Eine feinere Einteilung (CB/RB, DM/CM/AM, Wing/ST)
# waere geraten, nicht gemessen, und wird deshalb NICHT vorgetaeuscht.

POSITION_GK  = "Goalkeeper"
POSITION_DEF = "Defender"
POSITION_MID = "Midfielder"
POSITION_ATT = "Attacker"

POSITION_GROUPS = (POSITION_GK, POSITION_DEF, POSITION_MID, POSITION_ATT)

POSITION_LABELS = {
    POSITION_GK:  "Torhüter",
    POSITION_DEF: "Abwehr",
    POSITION_MID: "Mittelfeld",
    POSITION_ATT: "Angriff",
}


# ---------------------------------------------------------------------------
# Kennzahl-Typen
# ---------------------------------------------------------------------------

KIND_PER90 = "per90"   # Ereignis pro 90 Minuten
KIND_RATE  = "rate"    # Quote in Prozent
KIND_TOTAL = "total"   # absoluter Saisonwert
KIND_VALUE = "value"   # bereits normierter Einzelwert (z. B. Rating)

HIGHER_BETTER = "higher_better"
LOWER_BETTER  = "lower_better"


def _metric(key, label, kind, direction, description,
            source=None, numerator=None, denominator=None):
    """Kleiner Helfer, damit die Katalogeintraege unten lesbar bleiben."""
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "direction": direction,
        "description": description,
        # source: Pfad im statistics-Objekt, z. B. ("tackles", "total")
        "source": source,
        # Fuer KIND_RATE: zwei Pfade statt einem
        "numerator": numerator,
        "denominator": denominator,
    }


# ---------------------------------------------------------------------------
# Metrik-Katalog
# ---------------------------------------------------------------------------
#
# Jeder Eintrag ist eine Kennzahl, die aus echten API-Sports-Feldern
# berechnet werden kann. Kein Eintrag ohne nachweisbare Datenquelle.

METRICS = {

    # --- universell, positionsuebergreifend ---------------------------------
    "rating": _metric(
        "rating", "Bewertung", KIND_VALUE, HIGHER_BETTER,
        "Durchschnittliche Spielbewertung von API-Sports, gewichtet nach Einsatzminuten.",
        source=("games", "rating"),
    ),
    "appearances": _metric(
        "appearances", "Einsätze", KIND_TOTAL, HIGHER_BETTER,
        "Anzahl der Spiele mit mindestens einer Einsatzminute.",
        source=("games", "appearences"),   # API-Sports schreibt das Feld so
    ),
    "lineups": _metric(
        "lineups", "Startelf", KIND_TOTAL, HIGHER_BETTER,
        "Anzahl der Spiele in der Startaufstellung.",
        source=("games", "lineups"),
    ),
    "minutes": _metric(
        "minutes", "Minuten", KIND_TOTAL, HIGHER_BETTER,
        "Gesamte Einsatzzeit in der Saison.",
        source=("games", "minutes"),
    ),
    "goals": _metric(
        "goals", "Tore", KIND_TOTAL, HIGHER_BETTER,
        "Erzielte Tore in der Saison, inklusive verwandelter Elfmeter.",
        source=("goals", "total"),
    ),
    "assists": _metric(
        "assists", "Assists", KIND_TOTAL, HIGHER_BETTER,
        "Torvorlagen in der Saison.",
        source=("goals", "assists"),
    ),
    "cards_yellow": _metric(
        "cards_yellow", "Gelbe Karten", KIND_TOTAL, LOWER_BETTER,
        "Gelbe Karten in der Saison. Niedriger ist in der Regel besser, "
        "sagt allein aber wenig über die Spielweise aus.",
        source=("cards", "yellow"),
    ),

    # --- pro 90 Minuten ----------------------------------------------------
    "goals_per90": _metric(
        "goals_per90", "Tore pro 90", KIND_PER90, HIGHER_BETTER,
        "Tore hochgerechnet auf 90 Einsatzminuten.",
        source=("goals", "total"),
    ),
    "assists_per90": _metric(
        "assists_per90", "Assists pro 90", KIND_PER90, HIGHER_BETTER,
        "Torvorlagen hochgerechnet auf 90 Einsatzminuten.",
        source=("goals", "assists"),
    ),
    "shots_per90": _metric(
        "shots_per90", "Schüsse pro 90", KIND_PER90, HIGHER_BETTER,
        "Abgegebene Schüsse hochgerechnet auf 90 Einsatzminuten.",
        source=("shots", "total"),
    ),
    "shots_on_per90": _metric(
        "shots_on_per90", "Schüsse aufs Tor pro 90", KIND_PER90, HIGHER_BETTER,
        "Schüsse aufs Tor hochgerechnet auf 90 Einsatzminuten.",
        source=("shots", "on"),
    ),
    "passes_per90": _metric(
        "passes_per90", "Pässe pro 90", KIND_PER90, HIGHER_BETTER,
        "Gespielte Pässe hochgerechnet auf 90 Einsatzminuten. "
        "Ein hoher Wert zeigt Ballbeteiligung, keine Passqualität.",
        source=("passes", "total"),
    ),
    "key_passes_per90": _metric(
        "key_passes_per90", "Schlüsselpässe pro 90", KIND_PER90, HIGHER_BETTER,
        "Pässe, die unmittelbar zu einem Torschuss führen, pro 90 Minuten.",
        source=("passes", "key"),
    ),
    "tackles_per90": _metric(
        "tackles_per90", "Tacklings pro 90", KIND_PER90, HIGHER_BETTER,
        "Erfolgreiche Zweikampfaktionen gegen den ballführenden Gegner, pro 90 Minuten.",
        source=("tackles", "total"),
    ),
    "interceptions_per90": _metric(
        "interceptions_per90", "Abgefangene Bälle pro 90", KIND_PER90, HIGHER_BETTER,
        "Abgefangene gegnerische Pässe pro 90 Minuten.",
        source=("tackles", "interceptions"),
    ),
    "blocks_per90": _metric(
        "blocks_per90", "Blocks pro 90", KIND_PER90, HIGHER_BETTER,
        "Geblockte Schüsse und Pässe pro 90 Minuten.",
        source=("tackles", "blocks"),
    ),
    "dribbles_success_per90": _metric(
        "dribbles_success_per90", "Gelungene Dribblings pro 90", KIND_PER90, HIGHER_BETTER,
        "Erfolgreich abgeschlossene Dribblings pro 90 Minuten.",
        source=("dribbles", "success"),
    ),
    "fouls_committed_per90": _metric(
        "fouls_committed_per90", "Fouls pro 90", KIND_PER90, LOWER_BETTER,
        "Begangene Fouls pro 90 Minuten. Niedriger ist meist besser, "
        "hängt aber stark von Position und Spielweise ab.",
        source=("fouls", "committed"),
    ),
    "fouls_drawn_per90": _metric(
        "fouls_drawn_per90", "Gezogene Fouls pro 90", KIND_PER90, HIGHER_BETTER,
        "Vom Gegner erlittene Fouls pro 90 Minuten.",
        source=("fouls", "drawn"),
    ),
    "saves_per90": _metric(
        "saves_per90", "Paraden pro 90", KIND_PER90, HIGHER_BETTER,
        "Gehaltene Bälle pro 90 Minuten. Ein hoher Wert kann auch "
        "auf eine stark belastete Mannschaft hindeuten.",
        source=("goals", "saves"),
    ),
    "conceded_per90": _metric(
        "conceded_per90", "Gegentore pro 90", KIND_PER90, LOWER_BETTER,
        "Kassierte Tore pro 90 Minuten.",
        source=("goals", "conceded"),
    ),

    # --- Quoten ------------------------------------------------------------
    "duels_won_pct": _metric(
        "duels_won_pct", "Zweikampfquote", KIND_RATE, HIGHER_BETTER,
        "Anteil gewonnener Zweikämpfe an allen geführten Zweikämpfen.",
        numerator=("duels", "won"), denominator=("duels", "total"),
    ),
    "dribbles_success_pct": _metric(
        "dribbles_success_pct", "Dribbelquote", KIND_RATE, HIGHER_BETTER,
        "Anteil erfolgreicher Dribblings an allen Dribbelversuchen.",
        numerator=("dribbles", "success"), denominator=("dribbles", "attempts"),
    ),
    "shot_accuracy_pct": _metric(
        "shot_accuracy_pct", "Schussgenauigkeit", KIND_RATE, HIGHER_BETTER,
        "Anteil der Schüsse, die aufs Tor gingen.",
        numerator=("shots", "on"), denominator=("shots", "total"),
    ),
    "pass_accuracy_pct": _metric(
        "pass_accuracy_pct", "Passquote", KIND_RATE, HIGHER_BETTER,
        "Anteil angekommener Pässe. Hinweis: API-Sports liefert dieses Feld "
        "je nach Liga uneinheitlich, deshalb wird es auf Plausibilität geprüft.",
        source=("passes", "accuracy"),
    ),
    "penalties_saved": _metric(
        "penalties_saved", "Gehaltene Elfmeter", KIND_TOTAL, HIGHER_BETTER,
        "In der Saison parierte Strafstöße.",
        source=("penalty", "saved"),
    ),
}


# ---------------------------------------------------------------------------
# Radar-Profile je Positionsgruppe
# ---------------------------------------------------------------------------
#
# Bewusst 6 bis 8 Achsen. Mehr Achsen machen ein Radar auf dem Smartphone
# unlesbar und verbessern den Vergleich nicht.
#
# Auswahlkriterium war nicht "was liefert die API", sondern
# "was hilft beim Vergleich dieser Position wirklich".

RADAR_PROFILES = {
    POSITION_GK: [
        "saves_per90",
        "conceded_per90",
        "penalties_saved",
        "pass_accuracy_pct",
        "passes_per90",
        "rating",
    ],
    POSITION_DEF: [
        "tackles_per90",
        "interceptions_per90",
        "blocks_per90",
        "duels_won_pct",
        "pass_accuracy_pct",
        "passes_per90",
        "fouls_committed_per90",
    ],
    POSITION_MID: [
        "passes_per90",
        "pass_accuracy_pct",
        "key_passes_per90",
        "assists_per90",
        "tackles_per90",
        "interceptions_per90",
        "duels_won_pct",
        "goals_per90",
    ],
    POSITION_ATT: [
        "goals_per90",
        "shots_per90",
        "shot_accuracy_pct",
        "assists_per90",
        "key_passes_per90",
        "dribbles_success_per90",
        "dribbles_success_pct",
        "duels_won_pct",
    ],
}


# Allgemeiner Vergleich: gilt fuer beliebige Positionskombinationen.
# Hier wird bewusst KEIN Radar gebaut, weil ein gemeinsames Radar ueber
# Torwart und Stuermer fachlich irrefuehrend waere.
GENERAL_METRICS = [
    "appearances",
    "lineups",
    "minutes",
    "goals",
    "assists",
    "rating",
    "pass_accuracy_pct",
    "duels_won_pct",
    "cards_yellow",
]


# ---------------------------------------------------------------------------
# Berechnung
# ---------------------------------------------------------------------------

def _dig(stats, path):
    """Liest einen verschachtelten Wert, z. B. ("tackles", "total")."""
    if not path:
        return None
    node = stats
    for part in path:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _to_number(value):
    """
    Wandelt API-Werte in Zahlen um.

    API-Sports liefert je nach Feld int, float, numerischen String
    ("7.25", "82%") oder None. None bleibt None und wird NIE zu 0.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def per90(value, minutes):
    """
    Hochrechnung auf 90 Minuten.

    Gibt None zurueck, wenn der Wert fehlt oder keine Einsatzzeit vorliegt.
    Ohne Minuten gibt es keinen sinnvollen Per-90-Wert.
    """
    value = _to_number(value)
    minutes = _to_number(minutes)
    if value is None or not minutes or minutes <= 0:
        return None
    return round(value / minutes * 90.0, 2)


def rate(numerator, denominator):
    """
    Quote in Prozent.

    Gibt None zurueck, wenn Zaehler oder Nenner fehlen oder der Nenner 0 ist.
    Ein Spieler ohne Dribbelversuche hat keine Dribbelquote von 0 Prozent,
    sondern gar keine.
    """
    numerator = _to_number(numerator)
    denominator = _to_number(denominator)
    if numerator is None or not denominator or denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 1)


def _plausible_percentage(value):
    """
    Plausibilitaetspruefung fuer passes.accuracy.

    API-Sports liefert dieses Feld uneinheitlich: in manchen Ligen als
    Prozentwert (0 bis 100), in anderen als absolute Zahl angekommener
    Paesse. Werte ausserhalb von 0 bis 100 sind daher keine Quote und
    werden verworfen, statt eine falsche Prozentzahl anzuzeigen.
    """
    number = _to_number(value)
    if number is None:
        return None
    if number < 0 or number > 100:
        return None
    return round(number, 1)


def compute_metric(metric_key, stats, minutes):
    """
    Berechnet eine einzelne Kennzahl aus einem normalisierten stats-Dict.

    stats:   zusammengefasste Rohwerte eines Spielers (siehe player_stats_loader)
    minutes: Einsatzminuten, Basis fuer alle Per-90-Werte

    Rueckgabe: Zahl oder None. Niemals 0 als Ersatz fuer "unbekannt".
    """
    metric = METRICS.get(metric_key)
    if metric is None:
        return None

    kind = metric["kind"]

    if kind == KIND_RATE:
        if metric["numerator"] and metric["denominator"]:
            return rate(
                _dig(stats, metric["numerator"]),
                _dig(stats, metric["denominator"]),
            )
        # Sonderfall passes.accuracy: kommt bereits als Quote, aber unzuverlaessig
        return _plausible_percentage(_dig(stats, metric["source"]))

    raw = _dig(stats, metric["source"])

    if kind == KIND_PER90:
        return per90(raw, minutes)

    if kind == KIND_TOTAL:
        number = _to_number(raw)
        return None if number is None else int(number)

    if kind == KIND_VALUE:
        number = _to_number(raw)
        return None if number is None else round(number, 2)

    return None


def metrics_for_position(position):
    """Radar-Kennzahlen einer Positionsgruppe. Unbekannte Position -> []."""
    return list(RADAR_PROFILES.get(position, []))


def same_position_group(position_a, position_b):
    """
    Prueft, ob zwei Spieler ueberhaupt positionsbezogen vergleichbar sind.

    Nur bei identischer Gruppe ist ein gemeinsames Radar fachlich zulaessig.
    Sonst greift der allgemeine Vergleich.
    """
    if not position_a or not position_b:
        return False
    if position_a not in POSITION_GROUPS or position_b not in POSITION_GROUPS:
        return False
    return position_a == position_b


def describe_metric(metric_key):
    """Metadaten einer Kennzahl fuer das Frontend (Label, Typ, Richtung, Erklaerung)."""
    metric = METRICS.get(metric_key)
    if metric is None:
        return None
    return {
        "key": metric["key"],
        "label": metric["label"],
        "kind": metric["kind"],
        "direction": metric["direction"],
        "description": metric["description"],
    }
