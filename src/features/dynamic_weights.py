"""
Dynamische Gewichtung zwischen Historie und laufender Saison.

Das Problem
-----------
An Spieltag 0 gibt es keine Daten der neuen Saison. Die Prognose muss sich
vollstaendig auf die Historie stuetzen. An Spieltag 30 ist die Historie
weitgehend irrelevant: Was dieses Team in DIESER Saison tut, zaehlt.
Dazwischen braucht es einen gleitenden Uebergang.

Ein naiver linearer Uebergang (Gewicht = gespielte / gesamte Spiele) hat
zwei Fehler:

1. Er gibt den ersten Spielen zu viel Gewicht. Nach 2 von 34 Spieltagen
   bekaeme die aktuelle Saison bereits 6 % - klingt wenig, aber der
   Sprung von 0 auf 6 % passiert auf Basis von zwei Ergebnissen, die
   fast reines Rauschen sind.
2. Er erreicht am Saisonende 100 % und wirft die Historie komplett weg.
   Damit verliert man die Stabilisierung genau dann, wenn einzelne
   Ausreisser (Rotation, bedeutungslose Spiele) am haeufigsten sind.

Die Loesung: Shrinkage
----------------------
    w_aktuell = n / (n + k)
    w_historie = 1 - w_aktuell

n = Anzahl gespielter Spiele, k = Regularisierungskonstante.

Diese Form stammt aus dem empirischen Bayes-Ansatz: Die Historie ist der
Prior, die laufende Saison die Evidenz. Je mehr Evidenz vorliegt, desto
weiter loest man sich vom Prior - aber nie vollstaendig.

Mit k = 8 ergibt sich:

    Spieltag  0 ->   0 % aktuell   (reine Historie)
    Spieltag  3 ->  27 %
    Spieltag  5 ->  38 %
    Spieltag 10 ->  56 %
    Spieltag 15 ->  65 %
    Spieltag 25 ->  76 %
    Spieltag 34 ->  81 %           (Historie bleibt als Prior erhalten)

Die Kurve ist anfangs flach genug, dass ein einzelnes 5:0 die Bewertung
nicht kippt, und erreicht nie 100 %.

Warum k = 8?
------------
k ist der Punkt, an dem beide Quellen gleich viel zaehlen (n = k -> 50 %).
Acht Spiele sind etwa ein Viertel einer Hinrunde: genug, um einen echten
Trend von einer Zufallsserie zu unterscheiden, aber nicht so viel, dass
das Modell bis Weihnachten an veralteten Annahmen festhaelt.

Der Wert ist bewusst EIN einzelner, erklaerbarer Parameter statt einer
Tabelle handgesetzter Prozentwerte. Er laesst sich spaeter per Backtesting
kalibrieren, ohne dass die Modelllogik angefasst werden muss.
"""


# Regularisierungskonstante: bei so vielen gespielten Spielen zaehlen
# Historie und laufende Saison gleich viel.
DEFAULT_K = 8.0

# Ab so vielen gespielten Spielen gilt die Datenlage als belastbar.
# Darunter zeigt das Frontend einen Hinweis.
RELIABLE_AFTER_MATCHES = 5


def current_season_weight(matches_played, k=DEFAULT_K):
    """
    Gewicht der laufenden Saison zwischen 0.0 und knapp unter 1.0.

    matches_played: Anzahl bereits gespielter Spiele des Teams
                    (nicht der Liga-Spieltag, denn Teams koennen wegen
                    Nachholspielen unterschiedlich viele absolviert haben)
    """
    n = max(0, matches_played or 0)
    if n == 0:
        return 0.0
    return n / (n + k)


def weight_split(matches_played, k=DEFAULT_K):
    """Beide Gewichte als Paar, immer summierend zu 1.0."""
    w_current = current_season_weight(matches_played, k=k)
    return {
        "current": w_current,
        "historical": 1.0 - w_current,
        "matches_played": max(0, matches_played or 0),
        "k": k,
    }


def blend_value(historical_value, current_value, matches_played, k=DEFAULT_K):
    """
    Mischt einen historischen mit einem aktuellen Wert.

    Ist kein aktueller Wert vorhanden (None, z. B. Spieltag 0), wird der
    historische unveraendert zurueckgegeben. Das ist wichtig: Ohne diese
    Pruefung wuerde ein fehlender Wert als 0 interpretiert und das Team
    kuenstlich schwaechen.
    """
    if current_value is None:
        return historical_value
    if historical_value is None:
        return current_value

    w = current_season_weight(matches_played, k=k)
    return (1.0 - w) * historical_value + w * current_value


def blend_profile(historical_profile, current_profile, matches_played, k=DEFAULT_K):
    """
    Mischt ein komplettes Teamprofil.

    Gemischt werden nur die vier Ratings plus die abgeleiteten Kennzahlen.
    Stammdaten (Name, Wappen) kommen bevorzugt aus dem aktuellen Profil,
    weil sich Vereinsnamen aendern koennen.

    Das Ergebnis traegt die verwendeten Gewichte in 'weights' mit, damit
    im Debug nachvollziehbar bleibt, woraus sich ein Wert zusammensetzt.
    """
    if historical_profile is None and current_profile is None:
        return None

    if historical_profile is None:
        merged = dict(current_profile)
        merged["weights"] = {"current": 1.0, "historical": 0.0,
                             "matches_played": matches_played, "k": k}
        return merged

    if current_profile is None:
        merged = dict(historical_profile)
        merged["weights"] = {"current": 0.0, "historical": 1.0,
                             "matches_played": matches_played or 0, "k": k}
        return merged

    keys = ("attack_home", "attack_away", "defence_home", "defence_away",
            "points_per_game", "goals_for_per_game", "goals_against_per_game",
            "win_rate")

    merged = dict(historical_profile)

    # Stammdaten aus der aktuellen Saison bevorzugen.
    for field in ("team_name", "short_name", "crest"):
        if current_profile.get(field):
            merged[field] = current_profile[field]

    for key in keys:
        merged[key] = blend_value(
            historical_profile.get(key),
            current_profile.get(key),
            matches_played,
            k=k,
        )

    split = weight_split(matches_played, k=k)
    merged["weights"] = split
    merged["matches_used"] = (
        (historical_profile.get("matches_used") or 0)
        + (current_profile.get("matches_used") or 0)
    )

    return merged


def weight_table(total_matchdays=34, k=DEFAULT_K, steps=None):
    """
    Erzeugt eine Uebersicht der Gewichtung ueber die Saison.

    Reine Diagnosehilfe: zeigt auf einen Blick, wie sich das Verhaeltnis
    entwickelt. Wird im Diagnose-Skript ausgegeben.
    """
    steps = steps or [0, 1, 3, 5, 8, 10, 15, 20, 25, 30, total_matchdays]
    rows = []

    for n in steps:
        if n > total_matchdays:
            continue
        split = weight_split(n, k=k)
        rows.append({
            "matches_played": n,
            "current_pct": round(split["current"] * 100, 1),
            "historical_pct": round(split["historical"] * 100, 1),
        })

    return rows


def confidence_level(matches_played, has_history, fallback_level=0):
    """
    Schaetzt, wie belastbar die Prognose fuer ein Team ist.

    Ergebnis zwischen 0.0 und 1.0 plus eine grobe Stufe fuer die Anzeige.

    Drei Einflussgroessen:
      - Wie viele Spiele der laufenden Saison sind bekannt?
      - Liegen historische Saisondaten vor?
      - Ueber wie viele Fallback-Stufen musste das Team aufgeloest werden?

    Ein Aufsteiger ohne Historie an Spieltag 0 landet damit korrekt bei
    niedriger Confidence, ein etabliertes Team mit zwei Vorsaisons und
    20 gespielten Partien bei hoher.
    """
    n = max(0, matches_played or 0)

    # Anteil aus der laufenden Saison: waechst mit der Spielzahl.
    current_part = min(1.0, n / 15.0) * 0.5

    # Anteil aus der Historie.
    history_part = 0.4 if has_history else 0.0

    # Grundvertrauen, wenn ueberhaupt Daten da sind.
    base = 0.1 if (has_history or n > 0) else 0.0

    score = base + current_part + history_part

    # Jede Fallback-Stufe kostet Vertrauen.
    score -= 0.12 * max(0, fallback_level)
    score = max(0.0, min(1.0, score))

    if score >= 0.7:
        level = "hoch"
    elif score >= 0.4:
        level = "mittel"
    else:
        level = "niedrig"

    return {"score": round(score, 2), "level": level}
