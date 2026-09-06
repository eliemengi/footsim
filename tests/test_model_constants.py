"""
Tests fuer die zentralisierten Modellkonstanten.

Zwei Anliegen
-------------
1. Der Fallback-Torschnitt stand doppelt im Code (team_profile und
   strength_provider). Zwei Stellen mit demselben Zweck driften
   auseinander, sobald jemand anfaengt zu kalibrieren.

2. Es war nicht erkennbar, welche Zahl im Modell was ist. Ein
   Heimvorteil-Schaetzwert und die Anzahl der Spieltage sind beides
   "hartkodierte Zahlen", aber nur die erste gehoert spaeter empirisch
   bestimmt. Ein Optimierer, der ZONE_CONFIGS anfasst, wuerde
   Wettbewerbsregeln erfinden.

Der wichtigste Test hier ist test_no_numeric_value_changed: Die
Zentralisierung war ein reines Refactoring. Aendert sich dabei ein Wert,
aendert sich das Modell - und das darf in diesem Schritt nicht passieren.
"""

import pytest

from src.features import model_constants as mc


# Die Werte, wie sie VOR der Zentralisierung im Code standen. Bewusst als
# Literale festgeschrieben und nicht aus dem Code importiert: Sonst wuerde
# der Test jede Aenderung mitmachen, statt sie zu melden.
BASELINE_VALUES = {
    "DEFAULT_K": 8.0,
    "SEASON_DECAY": 0.55,
    "DEFAULT_SHRINKAGE_K": 5.0,
    "FALLBACK_PROMOTED_ATTACK": 0.88,
    "FALLBACK_PROMOTED_DEFENCE": 1.14,
    "PROMOTED_SAMPLE_TARGET": 3,
    "REPLACEMENT_FACTOR": 0.5,
    "RATING_MIN": 0.35,
    "RATING_MAX": 2.20,
    "XG_MIN": 0.15,
    "XG_MAX": 4.5,
    "MAX_ATTACK_PENALTY": 0.25,
    "NEUTRAL_RATING": 1.0,
    "CL_ZONE_DIRECT_LAST": 8,
    "CL_ZONE_PLAYOFF_LAST": 24,
    "CURRENT_LEAGUE_AVG_MIN_MATCHES": 20,
}


def test_no_numeric_value_changed():
    """
    Die Zentralisierung war ein Refactoring, kein Modellwechsel.

    Schlaegt dieser Test fehl, wurde ein Modellwert veraendert. Das ist
    nur mit Belegen aus einem Backtest zulaessig - dann gehoert der
    Baseline-Wert hier bewusst mit angepasst.
    """
    actual = {c["name"]: c["value"] for c in mc.describe_constants()}

    for name, expected in BASELINE_VALUES.items():
        assert name in actual, f"{name} fehlt in describe_constants()"
        assert actual[name] == pytest.approx(expected), (
            f"{name} hat sich geaendert: {actual[name]} statt {expected}"
        )


def test_league_average_fallbacks_unchanged():
    assert mc.DOMESTIC_LEAGUE_AVG_FALLBACK == {
        "home_goals": 1.5, "away_goals": 1.2, "total_goals": 2.7, "matches": 0,
    }
    assert mc.CL_LEAGUE_AVG_FALLBACK == {
        "home_goals": 1.55, "away_goals": 1.25, "total_goals": 2.80, "matches": 0,
    }


def test_domestic_and_cl_stay_separate():
    """
    Beide beschreiben denselben Sachverhalt fuer unterschiedliche
    Wettbewerbe. Sie zusammenzufassen waere kein Aufraeumen, sondern ein
    stiller Modellwechsel: Die CL hat ein anderes Torniveau.
    """
    assert mc.DOMESTIC_LEAGUE_AVG_FALLBACK != mc.CL_LEAGUE_AVG_FALLBACK
    assert (mc.CL_LEAGUE_AVG_FALLBACK["total_goals"]
            > mc.DOMESTIC_LEAGUE_AVG_FALLBACK["total_goals"])


def test_accessors_return_fresh_copies():
    """
    Aufrufer legen den Ligaschnitt in ihren Ergebnisdicts ab und
    veraendern ihn dort teils weiter. Ohne Kopie wuerde das auf den
    globalen Wert durchschlagen und alle spaeteren Simulationen
    desselben Prozesses verfaelschen.
    """
    first = mc.domestic_league_avg_fallback()
    first["home_goals"] = 99.0

    assert mc.domestic_league_avg_fallback()["home_goals"] == 1.5
    assert mc.DOMESTIC_LEAGUE_AVG_FALLBACK["home_goals"] == 1.5

    cl_first = mc.cl_league_avg_fallback()
    cl_first["home_goals"] = 99.0
    assert mc.cl_league_avg_fallback()["home_goals"] == 1.55


# ---------------------------------------------------------------------------
# Single Source of Truth
# ---------------------------------------------------------------------------

def test_team_profile_uses_central_fallback():
    from src.features.team_profile import league_averages

    assert league_averages([]) == mc.DOMESTIC_LEAGUE_AVG_FALLBACK


def test_strength_provider_uses_central_cl_fallback(monkeypatch):
    """
    Ohne CL-Ergebnisse muss exakt der zentrale CL-Schaetzwert greifen.
    """
    import src.features.strength_provider as sp

    # V2-C1: _blend_top5_league_history_by_id ist entfallen. Die
    # Profilfabrik laedt ueber historical_loader - dort wird geleert.
    from src.data import historical_loader

    monkeypatch.setattr(historical_loader, "load_season",
                        lambda api_code, season: None)
    monkeypatch.setattr(historical_loader, "load_cl_season", lambda s: None)
    monkeypatch.setattr(sp, "get_all_matches", lambda *a, **k: [])

    result = sp.get_cl_team_strengths(2026, cutoff="2026-08-01")

    assert result["league_avg"] == mc.CL_LEAGUE_AVG_FALLBACK


def test_no_duplicate_league_average_literals_remain():
    """
    Die alten Literale duerfen nicht zurueckkehren. Ein zweiter Ort mit
    denselben Zahlen war genau das Problem.
    """
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    suspicious = []

    for rel in ("src/features/team_profile.py", "src/features/strength_provider.py"):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                code = line.split("#")[0]
                if '"home_goals"' in code and ("1.5" in code or "1.55" in code):
                    suspicious.append(f"{rel}:{lineno}")

    assert not suspicious, (
        f"Fallback-Torschnitt wieder inline definiert: {suspicious}"
    )


# ---------------------------------------------------------------------------
# Klassifikation
# ---------------------------------------------------------------------------

def test_registry_values_are_live_not_copied():
    """
    Die Uebersicht importiert die echten Konstanten, statt ihre Werte zu
    wiederholen. Nur so kann sie nicht von der Wirklichkeit abweichen.
    """
    from src.features import dynamic_weights, team_profile

    by_name = {c["name"]: c for c in mc.describe_constants()}

    assert by_name["DEFAULT_K"]["value"] is dynamic_weights.DEFAULT_K
    assert by_name["SEASON_DECAY"]["value"] is team_profile.SEASON_DECAY
    assert by_name["RATING_MAX"]["value"] is team_profile.RATING_MAX


def test_every_entry_is_fully_classified():
    valid = {
        mc.CATEGORY_MODEL_PARAMETER,
        mc.CATEGORY_GUARDRAIL,
        mc.CATEGORY_COMPETITION_RULE,
        mc.CATEGORY_DATA_POLICY,
    }

    for entry in mc.describe_constants():
        assert entry["category"] in valid, entry
        assert entry["note"].strip(), f"{entry['name']} ohne Begruendung"
        assert entry["module"].startswith("src."), entry


def test_competition_rules_are_not_calibratable():
    """
    Der Kern der Klassifikation: Ein spaeterer Parameter-Sweep darf
    Verbandsregeln nicht anfassen. Spieltage und CL-Zonen sind keine
    Hyperparameter.
    """
    calibratable = {c["name"] for c in mc.calibratable_constants()}

    for forbidden in ("MATCHDAYS_TOTAL", "ZONE_CONFIGS", "CL_ZONE_DIRECT_LAST",
                      "CL_ZONE_PLAYOFF_LAST", "TIEBREAK_CRITERIA"):
        assert forbidden not in calibratable, (
            f"{forbidden} ist eine Wettbewerbsregel und darf nicht "
            f"kalibriert werden"
        )


def test_guardrails_are_not_calibratable():
    calibratable = {c["name"] for c in mc.calibratable_constants()}

    for forbidden in ("RATING_MIN", "RATING_MAX", "XG_MIN", "XG_MAX",
                      "MAX_ATTACK_PENALTY", "NEUTRAL_RATING"):
        assert forbidden not in calibratable


def test_the_three_central_levers_are_marked_calibratable():
    """
    DEFAULT_K, SEASON_DECAY und DEFAULT_SHRINKAGE_K tragen das gesamte
    Modell. Sie muessen als kalibrierbar gefuehrt sein, sonst wuerde ein
    spaeterer Sweep an ihnen vorbeilaufen.
    """
    calibratable = {c["name"] for c in mc.calibratable_constants()}

    assert {"DEFAULT_K", "SEASON_DECAY", "DEFAULT_SHRINKAGE_K"} <= calibratable


def test_xg_clamp_uses_named_guardrails():
    """Der xG-Deckel darf kein anonymes Literal mehr sein."""
    from src.features.team_profile import expected_goals, XG_MIN, XG_MAX

    huge = {"attack_home": 50.0, "attack_away": 50.0,
            "defence_home": 50.0, "defence_away": 50.0}
    tiny = {"attack_home": 0.001, "attack_away": 0.001,
            "defence_home": 0.001, "defence_away": 0.001}
    avg = {"home_goals": 1.5, "away_goals": 1.2}

    high_home, high_away = expected_goals(huge, huge, avg)
    low_home, low_away = expected_goals(tiny, tiny, avg)

    assert high_home == XG_MAX and high_away == XG_MAX
    assert low_home == XG_MIN and low_away == XG_MIN
