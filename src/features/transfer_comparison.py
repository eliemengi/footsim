"""
Vergleichslogik fuer den Liga-zu-Liga-Transfervergleich.

Dieses Modul enthaelt AUSSCHLIESSLICH reine Logik:
    - keine API-Zugriffe
    - keine UI-Logik
    - kein kuenstlicher Gesamtsieger und kein Liga-Score

Verglichen werden zwei Transfergruppen unter denselben Bedingungen
(gemeinsame Zielliga, gleicher Saisonwechsel). Pro Kennzahl wird nur
markiert, welche Seite den besseren Wert hat. Die Schlussfolgerung
zieht der Nutzer selbst.
"""

# Zentrale Mindestspielzeit. Nur hier definiert, nirgendwo hardcodiert.
MIN_QUALIFYING_MINUTES = 300

# Unterhalb dieser Zahl qualifizierter Spieler gilt die Aussagekraft
# als eingeschraenkt und es wird ein neutraler Hinweis ausgegeben.
SMALL_SAMPLE_THRESHOLD = 5

# Kennzahlen der Hauptansicht. "higher_is_better" gilt fuer alle.
AVERAGE_METRICS = ("minutes", "goals", "assists", "scorer_points", "rating")

POSITION_GROUPS = ("Goalkeeper", "Defender", "Midfielder", "Attacker")


def _round(value, digits=1):
    if value is None:
        return None
    return round(value, digits)


def split_players(players, min_minutes=MIN_QUALIFYING_MINUTES):
    """
    Teilt eine Spielerliste in drei Toepfe:
        qualified    - Daten vorhanden und Minuten >= Schwelle
        low_minutes  - Daten vorhanden, aber Minuten < Schwelle
        missing_data - keine abrufbaren Zielliga-Daten

    Spieler mit exakt min_minutes Minuten gelten als qualifiziert.
    """
    qualified = []
    low_minutes = []
    missing_data = []

    for player in players:
        if not player.get("data_available"):
            missing_data.append(player)
            continue

        minutes = player.get("minutes") or 0
        if minutes >= min_minutes:
            qualified.append(player)
        else:
            low_minutes.append(player)

    return qualified, low_minutes, missing_data


def _average(players, field):
    """
    Durchschnitt einer Kennzahl ueber Spieler mit BEKANNTEM Wert.
    None-Werte (unbekannt) verzerren den Schnitt nicht und werden
    auch nicht als 0 gezaehlt.
    """
    values = [p[field] for p in players if p.get(field) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def build_group(league_code, league_label, players,
                min_minutes=MIN_QUALIFYING_MINUTES):
    """
    Baut die komplette Auswertung einer Transfergruppe.

    players: Liste von Transfer-Dicts, jeweils bereits um die
    normalisierten Statistikfelder ergaenzt (minutes, goals, ...).
    """
    qualified, low_minutes, missing_data = split_players(players, min_minutes)

    averages = {}
    for metric in AVERAGE_METRICS:
        digits = 2 if metric == "rating" else 1
        averages[metric] = _round(_average(qualified, metric), digits)

    # Wie viele qualifizierte Spieler hatten fuer eine Kennzahl gar
    # keinen bekannten Wert? Fuer die Transparenz im Frontend.
    unknown_counts = {}
    for metric in AVERAGE_METRICS:
        unknown_counts[metric] = sum(
            1 for p in qualified if p.get(metric) is None
        )

    positions = {}
    for group_name in POSITION_GROUPS:
        members = [p for p in qualified if p.get("position") == group_name]
        positions[group_name] = {
            "count": len(members),
            "averages": {
                metric: _round(_average(members, metric),
                               2 if metric == "rating" else 1)
                for metric in AVERAGE_METRICS
            },
        }
    unknown_position = [p for p in qualified if p.get("position") not in POSITION_GROUPS]
    positions["Unknown"] = {"count": len(unknown_position), "averages": {}}

    return {
        "league": league_code,
        "league_label": league_label,
        "sample": {
            "transfers_total": len(players),
            "qualified": len(qualified),
            "low_minutes": len(low_minutes),
            "missing_data": len(missing_data),
        },
        "averages": averages,
        "unknown_counts": unknown_counts,
        "positions": positions,
        "players": {
            "qualified": qualified,
            "low_minutes": low_minutes,
            "missing_data": missing_data,
        },
    }


def compare_metric_winners(group_a, group_b):
    """
    Pro Kennzahl: welche Seite hat den hoeheren Wert?

    Rueckgabe: {"minutes": "a" | "b" | None, ...}
    None bedeutet: gleichauf oder mindestens eine Seite ohne Wert.
    KEIN Gesamtsieger, keine Punktevergabe.
    """
    result = {}
    for metric in AVERAGE_METRICS:
        value_a = group_a["averages"].get(metric)
        value_b = group_b["averages"].get(metric)

        if value_a is None or value_b is None or value_a == value_b:
            result[metric] = None
        elif value_a > value_b:
            result[metric] = "a"
        else:
            result[metric] = "b"

    return result


def build_warnings(group_a, group_b):
    """Neutrale, transparente Hinweise. Keine dramatischen Fehler."""
    warnings = []

    for group in (group_a, group_b):
        sample = group["sample"]
        label = group["league_label"]

        if sample["transfers_total"] == 0:
            warnings.append(
                f"Fuer {label} wurden keine passenden Sommertransfers gefunden."
            )
        elif sample["qualified"] < SMALL_SAMPLE_THRESHOLD:
            warnings.append(
                f"Die Aussagekraft fuer {label} ist wegen der kleinen "
                f"Transfergruppe eingeschraenkt "
                f"({sample['qualified']} qualifizierte Spieler)."
            )

        if sample["missing_data"] > 0:
            plural = "Spieler" if sample["missing_data"] != 1 else "Spieler"
            warnings.append(
                f"Fuer {sample['missing_data']} {plural} aus {label} waren "
                f"keine vollstaendigen Leistungsdaten verfuegbar."
            )

    return warnings


def build_comparison_result(source_a, source_b, target, season,
                            label_a, label_b, label_target,
                            players_a, players_b,
                            min_minutes=MIN_QUALIFYING_MINUTES):
    """
    Setzt die komplette API-Antwort zusammen (reine Logik).
    """
    group_a = build_group(source_a, label_a, players_a, min_minutes)
    group_b = build_group(source_b, label_b, players_b, min_minutes)

    return {
        "query": {
            "source_a": source_a,
            "source_b": source_b,
            "target": target,
            "season": season,
            "season_label": f"{season} \u2192 {season + 1}",
            "source_a_label": label_a,
            "source_b_label": label_b,
            "target_label": label_target,
            "minimum_minutes": min_minutes,
        },
        "group_a": group_a,
        "group_b": group_b,
        "comparison": compare_metric_winners(group_a, group_b),
        "warnings": build_warnings(group_a, group_b),
    }
