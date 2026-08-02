"""
Tests fuer die Datenschicht des Spielervergleichs (Phase 3, Etappe 1).

Alle Tests laufen ohne Netzwerk. Getestet werden ausschliesslich die
reinen Funktionen: Metrikberechnung, Ligawahl, Aggregation, Vergleichsaufbau.

Schwerpunkt der Tests ist die Regel, die im gesamten Feature am wichtigsten
ist: ein fehlender Wert ist None und wird niemals stillschweigend zu 0.
"""

import pytest

from src.data.player_metrics import (
    per90,
    rate,
    compute_metric,
    metrics_for_position,
    same_position_group,
    describe_metric,
    POSITION_GK,
    POSITION_DEF,
    POSITION_MID,
    POSITION_ATT,
    RADAR_PROFILES,
    METRICS,
    GENERAL_METRICS,
)

from src.data.player_compare_loader import (
    pick_primary_league_entries,
    aggregate_statistics,
    build_player_profile,
    build_comparison,
    COMPARE_LEAGUE_IDS,
)


# ---------------------------------------------------------------------------
# Hilfsdaten
# ---------------------------------------------------------------------------

BUNDESLIGA_ID = 78
PREMIER_LEAGUE_ID = 39
CHAMPIONS_LEAGUE_ID = 2


def _stats_entry(league_id, minutes, **overrides):
    """Baut einen realistischen statistics-Block wie ihn API-Sports liefert."""
    entry = {
        "league": {"id": league_id, "name": "Test League"},
        "team": {"id": 1, "name": "Test FC", "logo": "logo.png"},
        "games": {
            "appearences": 10,
            "lineups": 8,
            "minutes": minutes,
            "position": "Midfielder",
            "rating": "7.00",
        },
        "shots": {"total": 20, "on": 8},
        "goals": {"total": 4, "conceded": None, "assists": 3, "saves": None},
        "passes": {"total": 500, "key": 15, "accuracy": 85},
        "tackles": {"total": 25, "blocks": 3, "interceptions": 12},
        "duels": {"total": 100, "won": 55},
        "dribbles": {"attempts": 30, "success": 18},
        "fouls": {"drawn": 14, "committed": 11},
        "cards": {"yellow": 3, "red": 0},
        "penalty": {"saved": None, "scored": 1, "missed": 0},
    }
    for section, values in overrides.items():
        entry.setdefault(section, {}).update(values)
    return entry


# ---------------------------------------------------------------------------
# per90
# ---------------------------------------------------------------------------

def test_per90_berechnet_korrekt():
    # 4 Tore in 900 Minuten = 0.4 Tore pro 90
    assert per90(4, 900) == 0.4


def test_per90_ohne_minuten_ist_none():
    """Ohne Einsatzzeit gibt es keinen sinnvollen Per-90-Wert."""
    assert per90(4, 0) is None
    assert per90(4, None) is None


def test_per90_ohne_wert_ist_none():
    assert per90(None, 900) is None


def test_per90_akzeptiert_string_werte():
    """API-Sports liefert Zahlen teils als String."""
    assert per90("4", "900") == 0.4


def test_per90_negative_minuten_ist_none():
    assert per90(4, -90) is None


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------

def test_rate_berechnet_prozent():
    assert rate(55, 100) == 55.0


def test_rate_ohne_nenner_ist_none():
    """Ein Spieler ohne Dribbelversuche hat keine Quote von 0, sondern keine."""
    assert rate(0, 0) is None
    assert rate(5, None) is None


def test_rate_ohne_zaehler_ist_none():
    assert rate(None, 100) is None


def test_rate_null_zaehler_ist_null_prozent():
    """0 gewonnene von 10 Duellen ist eine echte 0-Prozent-Quote, kein None."""
    assert rate(0, 10) == 0.0


# ---------------------------------------------------------------------------
# compute_metric
# ---------------------------------------------------------------------------

def test_compute_metric_per90():
    stats = {"goals": {"total": 9}}
    assert compute_metric("goals_per90", stats, 900) == 0.9


def test_compute_metric_rate():
    stats = {"duels": {"total": 200, "won": 110}}
    assert compute_metric("duels_won_pct", stats, 900) == 55.0


def test_compute_metric_total_bleibt_absolut():
    stats = {"goals": {"total": 12}}
    assert compute_metric("goals", stats, 900) == 12


def test_compute_metric_rating_ist_wert():
    stats = {"games": {"rating": "7.42"}}
    assert compute_metric("rating", stats, 900) == 7.42


def test_compute_metric_fehlendes_feld_ist_none():
    """Kein stiller Nullwert bei fehlenden Daten."""
    stats = {"goals": {"total": None}}
    assert compute_metric("goals_per90", stats, 900) is None
    assert compute_metric("goals", stats, 900) is None


def test_compute_metric_unbekannter_key_ist_none():
    assert compute_metric("gibt_es_nicht", {}, 900) is None


def test_pass_accuracy_ueber_100_wird_verworfen():
    """
    API-Sports liefert passes.accuracy je nach Liga als Prozent oder als
    absolute Zahl. Werte ausserhalb 0-100 sind keine Quote.
    """
    stats = {"passes": {"accuracy": 431}}
    assert compute_metric("pass_accuracy_pct", stats, 900) is None


def test_pass_accuracy_plausibel_wird_uebernommen():
    stats = {"passes": {"accuracy": 87}}
    assert compute_metric("pass_accuracy_pct", stats, 900) == 87.0


# ---------------------------------------------------------------------------
# Positionslogik
# ---------------------------------------------------------------------------

def test_alle_positionsgruppen_haben_radar_profil():
    for position in (POSITION_GK, POSITION_DEF, POSITION_MID, POSITION_ATT):
        assert len(RADAR_PROFILES[position]) >= 6


def test_radar_profile_haben_hoechstens_acht_achsen():
    """Mehr als acht Achsen sind auf dem Smartphone nicht mehr lesbar."""
    for position, keys in RADAR_PROFILES.items():
        assert len(keys) <= 8, f"{position} hat {len(keys)} Achsen"


def test_alle_radar_metriken_existieren_im_katalog():
    """Kein Radar darf auf eine Kennzahl zeigen, die es nicht gibt."""
    for position, keys in RADAR_PROFILES.items():
        for key in keys:
            assert key in METRICS, f"{position}: {key} fehlt im Katalog"


def test_alle_allgemeinen_metriken_existieren_im_katalog():
    for key in GENERAL_METRICS:
        assert key in METRICS


def test_jede_metrik_hat_eine_datenquelle():
    """Keine Kennzahl ohne nachweisbares API-Feld."""
    for key, metric in METRICS.items():
        has_source = metric["source"] is not None
        has_ratio = metric["numerator"] is not None and metric["denominator"] is not None
        assert has_source or has_ratio, f"{key} hat keine Datenquelle"


def test_jede_metrik_quelle_wird_auch_aggregiert():
    """
    Schutz vor einem stillen Fehler: Eine Kennzahl kann im Katalog stehen und
    trotzdem immer None liefern, wenn ihr Quellfeld in player_compare_loader
    weder summiert noch gemittelt wird.
    """
    from src.data.player_compare_loader import SUMMABLE_FIELDS, WEIGHTED_FIELDS

    aggregated = set(SUMMABLE_FIELDS) | set(WEIGHTED_FIELDS)

    for key, metric in METRICS.items():
        paths = []
        if metric["source"]:
            paths.append(tuple(metric["source"]))
        if metric["numerator"]:
            paths.append(tuple(metric["numerator"]))
        if metric["denominator"]:
            paths.append(tuple(metric["denominator"]))

        for path in paths:
            assert path in aggregated, (
                f"{key} liest {path}, aber dieses Feld wird nie aggregiert"
            )


def test_same_position_group():
    assert same_position_group(POSITION_ATT, POSITION_ATT) is True
    assert same_position_group(POSITION_ATT, POSITION_GK) is False
    assert same_position_group(None, POSITION_ATT) is False
    assert same_position_group("Wing", "Wing") is False


def test_metrics_for_unbekannte_position_ist_leer():
    assert metrics_for_position("Sweeper") == []


def test_describe_metric_liefert_metadaten():
    meta = describe_metric("goals_per90")
    assert meta["label"]
    assert meta["kind"] == "per90"
    assert meta["direction"] == "higher_better"
    assert meta["description"]


def test_negative_metriken_sind_als_lower_better_markiert():
    for key in ("conceded_per90", "fouls_committed_per90", "cards_yellow"):
        assert METRICS[key]["direction"] == "lower_better"


# ---------------------------------------------------------------------------
# Ligawahl
# ---------------------------------------------------------------------------

def test_primaerliga_ist_die_mit_den_meisten_minuten():
    entries = [
        _stats_entry(BUNDESLIGA_ID, 1800),
        _stats_entry(PREMIER_LEAGUE_ID, 400),
    ]
    selected, league_id, code = pick_primary_league_entries(entries)
    assert league_id == BUNDESLIGA_ID
    assert code == "bl1"
    assert len(selected) == 1


def test_champions_league_wird_ignoriert():
    """
    Pokal- und Europapokalminuten fliessen nicht ein, weil der spaetere
    Perzentil-Pool aus Ligaspielern besteht.
    """
    entries = [
        _stats_entry(BUNDESLIGA_ID, 900),
        _stats_entry(CHAMPIONS_LEAGUE_ID, 1200),
    ]
    selected, league_id, code = pick_primary_league_entries(entries)
    assert league_id == BUNDESLIGA_ID
    assert code == "bl1"


def test_ohne_vergleichsliga_kein_ergebnis():
    entries = [_stats_entry(CHAMPIONS_LEAGUE_ID, 900)]
    selected, league_id, code = pick_primary_league_entries(entries)
    assert selected == []
    assert league_id is None
    assert code is None


def test_leere_eingabe_ist_unkritisch():
    assert pick_primary_league_entries(None) == ([], None, None)
    assert pick_primary_league_entries([]) == ([], None, None)


def test_alle_vergleichsligen_sind_bekannt():
    assert len(COMPARE_LEAGUE_IDS) == 5


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def test_vereinswechsel_innerhalb_der_liga_wird_summiert():
    """Winterwechsel innerhalb derselben Liga: Werte gehoeren zusammen."""
    entries = [
        _stats_entry(BUNDESLIGA_ID, 900, goals={"total": 5}),
        _stats_entry(BUNDESLIGA_ID, 600, goals={"total": 3}),
    ]
    result = aggregate_statistics(entries)
    assert result["goals"]["total"] == 8
    assert result["games"]["minutes"] == 1500


def test_rating_wird_minutengewichtet_gemittelt():
    """Ratings duerfen nicht addiert werden."""
    entries = [
        _stats_entry(BUNDESLIGA_ID, 900, games={"rating": "8.00"}),
        _stats_entry(BUNDESLIGA_ID, 300, games={"rating": "6.00"}),
    ]
    result = aggregate_statistics(entries)
    # (8.0*900 + 6.0*300) / 1200 = 7.5
    assert result["games"]["rating"] == 7.5


def test_fehlende_werte_bleiben_none():
    entries = [
        _stats_entry(BUNDESLIGA_ID, 900, goals={"total": None, "assists": None}),
    ]
    result = aggregate_statistics(entries)
    assert result["goals"]["total"] is None
    assert result["goals"]["assists"] is None


def test_teilweise_bekannte_werte_werden_summiert():
    """Ein bekannter Wert genuegt, damit das Feld nicht None bleibt."""
    entries = [
        _stats_entry(BUNDESLIGA_ID, 900, goals={"total": 5}),
        _stats_entry(BUNDESLIGA_ID, 600, goals={"total": None}),
    ]
    result = aggregate_statistics(entries)
    assert result["goals"]["total"] == 5


def test_aggregation_ohne_eintraege_liefert_none_geruest():
    result = aggregate_statistics([])
    assert result["goals"]["total"] is None
    assert result["games"]["minutes"] is None
    assert result["games"]["position"] is None


def test_position_kommt_aus_eintrag_mit_meisten_minuten():
    entries = [
        _stats_entry(BUNDESLIGA_ID, 300, games={"position": "Attacker"}),
        _stats_entry(BUNDESLIGA_ID, 1500, games={"position": "Midfielder"}),
    ]
    result = aggregate_statistics(entries)
    assert result["games"]["position"] == "Midfielder"


def test_unbekannte_position_wird_verworfen():
    entries = [_stats_entry(BUNDESLIGA_ID, 900, games={"position": "Libero"})]
    result = aggregate_statistics(entries)
    assert result["games"]["position"] is None


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

def _raw_player(position="Midfielder", minutes=1800, league_id=BUNDESLIGA_ID):
    return {
        "player": {
            "id": 42,
            "name": "Test Spieler",
            "firstname": "Test",
            "lastname": "Spieler",
            "photo": "photo.png",
            "age": 26,
            "nationality": "Germany",
            "height": "180 cm",
            "weight": "75 kg",
            "birth": {"date": "2000-01-01"},
        },
        "statistics": [
            _stats_entry(league_id, minutes, games={"position": position}),
        ],
    }


def test_profil_enthaelt_stammdaten():
    profile = build_player_profile(_raw_player(), 2024)
    assert profile["player_id"] == 42
    assert profile["name"] == "Test Spieler"
    assert profile["season"] == 2024
    assert profile["league_code"] == "bl1"
    assert profile["league_label"] == "Bundesliga"
    assert profile["position"] == "Midfielder"
    assert profile["minutes"] == 1800
    assert profile["data_available"] is True


def test_profil_ohne_daten_ist_ehrlich():
    profile = build_player_profile({}, 2024)
    assert profile["data_available"] is False
    assert profile["position"] is None
    assert profile["minutes"] is None


def test_profil_ohne_vergleichsliga_ist_nicht_verfuegbar():
    raw = _raw_player(league_id=CHAMPIONS_LEAGUE_ID)
    profile = build_player_profile(raw, 2024)
    assert profile["data_available"] is False


# ---------------------------------------------------------------------------
# Vergleich
# ---------------------------------------------------------------------------

def test_gleiche_position_erlaubt_radar():
    a = build_player_profile(_raw_player("Attacker"), 2024)
    b = build_player_profile(_raw_player("Attacker"), 2024)
    result = build_comparison(a, b)
    assert result["mode"] == "position"
    assert result["radar_enabled"] is True
    assert result["position"] == POSITION_ATT
    assert len(result["metrics"]) == len(RADAR_PROFILES[POSITION_ATT])


def test_unterschiedliche_position_erzwingt_allgemeinen_vergleich():
    """
    Torwart gegen Stuermer darf kein gemeinsames Radar ergeben,
    das waere fachlich irrefuehrend.
    """
    a = build_player_profile(_raw_player("Goalkeeper"), 2024)
    b = build_player_profile(_raw_player("Attacker"), 2024)
    result = build_comparison(a, b)
    assert result["mode"] == "general"
    assert result["radar_enabled"] is False
    assert result["position"] is None


def test_unbekannte_position_erzwingt_allgemeinen_vergleich():
    a = build_player_profile(_raw_player("Libero"), 2024)
    b = build_player_profile(_raw_player("Libero"), 2024)
    result = build_comparison(a, b)
    assert result["mode"] == "general"
    assert result["radar_enabled"] is False


def test_vergleich_liefert_metadaten_pro_kennzahl():
    a = build_player_profile(_raw_player("Midfielder"), 2024)
    b = build_player_profile(_raw_player("Midfielder"), 2024)
    result = build_comparison(a, b)
    for metric in result["metrics"]:
        assert metric["key"]
        assert metric["label"]
        assert metric["kind"] in ("per90", "rate", "total", "value")
        assert metric["direction"] in ("higher_better", "lower_better")
        assert metric["description"]
        assert "value_a" in metric
        assert "value_b" in metric


def test_perzentile_sind_in_etappe1_noch_nicht_verfuegbar():
    """
    Solange kein vollstaendiger Referenzpool existiert, meldet der Vergleich
    ausdruecklich, dass keine Perzentile vorliegen. Keine erfundenen Werte.
    """
    a = build_player_profile(_raw_player("Midfielder"), 2024)
    b = build_player_profile(_raw_player("Midfielder"), 2024)
    result = build_comparison(a, b)
    assert result["percentiles_available"] is False


def test_vergleich_mit_leerem_profil_bricht_nicht():
    a = build_player_profile(_raw_player("Attacker"), 2024)
    b = build_player_profile({}, 2024)
    result = build_comparison(a, b)
    assert result["mode"] == "general"
    for metric in result["metrics"]:
        assert metric["value_b"] is None
