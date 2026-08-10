"""
Tests fuer Provenienz und das zeitgestempelte Snapshot-Archiv.

Zwei Anliegen
-------------
1. Provenienz: Jede Staerkeberechnung muss sagen koennen, WORAUF sie
   beruht - Rechenzeitpunkt, juengstes beruecksichtigtes Spiel, Saison,
   Wettbewerb, Quelle, Stichprobengroesse. Ohne diese Angaben laesst sich
   spaeter nicht pruefen, ob ein Feature nur Daten benutzt hat, die zu
   seinem Zeitpunkt bekannt waren.

2. Archiv: Bisher galt ueberall "letzter Schreiber gewinnt". Perzentile
   ueberschreiben sich, Kaderdaten laufen ueber einen Cache mit
   Ablaufzeit. Die Frage "wer fehlte dem FC Bayern am 12. November?"
   ist danach nicht mehr beantwortbar - und rueckwirkend auch nicht von
   der API zu holen, weil beide Anbieter Verletzungen als Momentaufnahme
   liefern.

Wichtig: Es wird nichts rekonstruiert. Fehlende Historie bleibt eine
Luecke. Ein Test haelt das ausdruecklich fest.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.data import snapshot_archive as archive
from tests.conftest import make_standings_table


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# Archiv-Grundverhalten
# ---------------------------------------------------------------------------

def test_archive_writes_file_with_metadata(archive_dir):
    path = archive.archive_snapshot(
        kind="percentiles", key=2025, payload={"a": 1}, source="test",
    )

    assert os.path.exists(path)

    with open(path, encoding="utf-8") as fh:
        entry = json.load(fh)

    assert entry["payload"] == {"a": 1}
    assert entry["meta"]["kind"] == "percentiles"
    assert entry["meta"]["key"] == "2025"
    assert entry["meta"]["source"] == "test"
    assert entry["meta"]["captured_at"]
    assert entry["meta"]["archive_version"] == archive.ARCHIVE_VERSION


def test_archive_never_overwrites(archive_dir):
    """
    Der ganze Zweck des Archivs. Zwei Laeufe in derselben Sekunde
    duerfen sich nicht gegenseitig ausloeschen.
    """
    moment = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    first = archive.archive_snapshot("squad", "bl1", {"v": 1}, captured_at=moment)
    second = archive.archive_snapshot("squad", "bl1", {"v": 2}, captured_at=moment)

    assert first != second
    assert os.path.exists(first)
    assert os.path.exists(second)

    assert archive.load_snapshot_file(first)["payload"] == {"v": 1}
    assert archive.load_snapshot_file(second)["payload"] == {"v": 2}


def test_filenames_are_windows_safe(archive_dir):
    """Doppelpunkte aus ISO-Zeitstempeln sind unter Windows verboten."""
    path = archive.archive_snapshot("squad", "bl1_2025", {"v": 1})

    assert ":" not in os.path.basename(path)


def test_list_snapshots_is_chronological(archive_dir):
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for offset in (2, 0, 1):
        archive.archive_snapshot(
            "squad", "bl1", {"day": offset},
            captured_at=base + timedelta(days=offset),
        )

    entries = archive.list_snapshots("squad")
    stamps = [e["captured_at"] for e in entries]

    assert stamps == sorted(stamps)
    assert len(entries) == 3


def test_list_snapshots_filters_by_key(archive_dir):
    archive.archive_snapshot("squad", "bl1", {"v": 1})
    archive.archive_snapshot("squad", "pl", {"v": 2})

    assert len(archive.list_snapshots("squad", key="bl1")) == 1
    assert len(archive.list_snapshots("squad")) == 2


def test_list_snapshots_on_missing_kind_is_empty(archive_dir):
    assert archive.list_snapshots("gibtsnicht") == []


def test_corrupt_archive_file_is_skipped(archive_dir):
    archive.archive_snapshot("squad", "bl1", {"v": 1})

    bad = os.path.join(archive.archive_dir_for("squad"), "squad__x__kaputt.json")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("{nicht json")

    assert len(archive.list_snapshots("squad")) == 1
    assert archive.load_snapshot_file(bad) is None


# ---------------------------------------------------------------------------
# Point-in-Time-Zugriff aufs Archiv
# ---------------------------------------------------------------------------

def test_snapshot_as_of_returns_the_state_that_was_current_then(archive_dir):
    """
    Fuer ein Trainingsbeispiel vom 12. November wird der Kaderstand
    gebraucht, der an diesem Tag galt - nicht der heutige.
    """
    for day, value in ((1, "anfang"), (10, "mitte"), (20, "ende")):
        archive.archive_snapshot(
            "squad", "bl1", {"stand": value},
            captured_at=datetime(2025, 11, day, tzinfo=timezone.utc),
        )

    result = archive.snapshot_as_of("squad", "2025-11-12", key="bl1")

    assert result["payload"]["stand"] == "mitte"


def test_snapshot_as_of_never_returns_the_future(archive_dir):
    """Der zentrale Leak-Schutz des Archivs."""
    archive.archive_snapshot(
        "squad", "bl1", {"stand": "spaeter"},
        captured_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
    )

    assert archive.snapshot_as_of("squad", "2025-11-12", key="bl1") is None


def test_missing_history_stays_a_gap(archive_dir):
    """
    Was wir nicht gesammelt haben, bleibt unbekannt. Es wird NICHTS
    geschaetzt oder rekonstruiert - erfundene Historie waere im Training
    schlimmer als eine Luecke, weil das Modell ihr vertrauen wuerde.
    """
    assert archive.snapshot_as_of("squad", "2020-01-01", key="bl1") is None
    assert archive.archive_coverage("squad")["snapshots"] == 0


def test_archive_coverage_reports_the_usable_window(archive_dir):
    archive.archive_snapshot(
        "squad", "bl1", {}, captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    archive.archive_snapshot(
        "squad", "pl", {}, captured_at=datetime(2026, 2, 1, tzinfo=timezone.utc))

    coverage = archive.archive_coverage("squad")

    assert coverage["snapshots"] == 2
    assert coverage["keys"] == ["bl1", "pl"]
    assert coverage["earliest"].startswith("2026-01-01")
    assert coverage["latest"].startswith("2026-02-01")


# ---------------------------------------------------------------------------
# Anbindung: Perzentile
# ---------------------------------------------------------------------------

def test_percentile_save_keeps_latest_and_adds_archive(tmp_path, monkeypatch):
    """
    Der schnelle "aktueller Stand"-Zugriff bleibt, wo er war. Bestehende
    Leser duerfen von der Archivierung nichts merken.
    """
    import src.data.percentile_engine as pe

    monkeypatch.setattr(pe, "PERCENTILE_DIR", str(tmp_path / "percentiles"))
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "snapshots"))

    snapshot = {"season": 2025, "leagues": ["bl1"], "min_minutes": 500,
                "scopes": ["club_all"], "distributions": {}}

    path = pe.save_snapshot(snapshot)

    assert os.path.basename(path) == "percentiles_2025.json"
    assert pe.load_snapshot(2025)["season"] == 2025
    assert len(archive.list_snapshots("percentiles", key=2025)) == 1


def test_percentile_archive_keeps_every_run(tmp_path, monkeypatch):
    import src.data.percentile_engine as pe

    monkeypatch.setattr(pe, "PERCENTILE_DIR", str(tmp_path / "percentiles"))
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "snapshots"))

    for run in (1, 2, 3):
        pe.save_snapshot({"season": 2025, "run": run, "distributions": {}})

    entries = archive.list_snapshots("percentiles", key=2025)
    runs = [archive.load_snapshot_file(e["path"])["payload"]["run"] for e in entries]

    assert runs == [1, 2, 3]
    # Der aktuelle Stand ist der letzte.
    assert pe.load_snapshot(2025)["run"] == 3


def test_archive_failure_never_breaks_the_real_write(tmp_path, monkeypatch):
    """
    Der aktuelle Stand ist wichtiger als seine Kopie. Ein kaputtes Archiv
    darf den eigentlichen Schreibvorgang nicht scheitern lassen.
    """
    import src.data.percentile_engine as pe

    monkeypatch.setattr(pe, "PERCENTILE_DIR", str(tmp_path / "percentiles"))

    def boom(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(archive, "archive_snapshot", boom)

    path = pe.save_snapshot({"season": 2025, "distributions": {}})

    assert os.path.exists(path)


def test_archiving_can_be_switched_off(tmp_path, monkeypatch):
    import src.data.percentile_engine as pe

    monkeypatch.setattr(pe, "PERCENTILE_DIR", str(tmp_path / "percentiles"))
    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path / "snapshots"))

    pe.save_snapshot({"season": 2025, "distributions": {}}, archive=False)

    assert archive.list_snapshots("percentiles") == []


# ---------------------------------------------------------------------------
# Anbindung: Kaderstand
# ---------------------------------------------------------------------------

def test_capture_squad_snapshot_archives_current_state(tmp_path, monkeypatch):
    import src.features.squad_impact as si

    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(
        si, "get_squad_impact",
        lambda *a, **k: {10: {"attack_modifier": 0.8, "missing_players": [
            {"player_name": "Star", "reason": "Knie"}]}},
    )

    result = si.capture_squad_snapshot("bl1", season=2025)

    assert result["teams_covered"] == 1
    assert result["captured_at"]
    assert result["archived_to"] and os.path.exists(result["archived_to"])

    stored = archive.load_snapshot_file(result["archived_to"])
    assert stored["meta"]["source"] == "api-sports"

    # JSON kennt nur Zeichenketten als Objektschluessel. Aus dem Archiv
    # gelesen ist die Team-ID deshalb "10", nicht 10. Siehe den Kommentar
    # im naechsten Test - genau diese Falle hat schon einmal ein Feature
    # still ausser Kraft gesetzt.
    assert stored["payload"]["impact"]["10"]["attack_modifier"] == 0.8


def test_archived_team_ids_come_back_as_strings(tmp_path, monkeypatch):
    """
    Festgehaltener Vertrag, kein Schoenheitsfehler.

    Genau diese Eigenschaft von JSON hat den Kaderwirkungs-Bug erzeugt:
    Frisch berechnet lagen numerische Team-IDs vor, aus dem Cache gelesen
    Zeichenketten - und der Abgleich mit der Tabelle lief ins Leere,
    waehrend das Feature weiterhin "angewandt" meldete.

    Wer dieses Archiv spaeter fuer Training ausliest, MUSS die IDs
    zurueckwandeln. squad_impact._normalize_team_keys tut genau das.
    """
    import src.features.squad_impact as si

    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(
        si, "get_squad_impact",
        lambda *a, **k: {10: {"attack_modifier": 0.8}, 11: {"attack_modifier": 1.0}},
    )

    result = si.capture_squad_snapshot("bl1", season=2025)
    stored = archive.load_snapshot_file(result["archived_to"])

    assert all(isinstance(k, str) for k in stored["payload"]["impact"])

    # Und so bekommt man sie zurueck:
    restored = si._normalize_team_keys(stored["payload"]["impact"])
    assert restored[10]["attack_modifier"] == 0.8


def test_capture_squad_snapshot_skips_archive_when_no_data(tmp_path, monkeypatch):
    """Ein leerer Stand ist keine Information und wird nicht archiviert."""
    import src.features.squad_impact as si

    monkeypatch.setattr(archive, "ARCHIVE_DIR", str(tmp_path))
    monkeypatch.setattr(si, "get_squad_impact", lambda *a, **k: {})

    result = si.capture_squad_snapshot("bl1", season=2025)

    assert result["archived_to"] is None
    assert archive.list_snapshots("squad") == []


# ---------------------------------------------------------------------------
# Provenienz in den Feature-Ausgaben
# ---------------------------------------------------------------------------

def test_league_strengths_carry_provenance(monkeypatch):
    import src.features.strength_provider as sp
    from tests.conftest import make_historical_payload

    payload = make_historical_payload([10, 11, 12, 13], season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, payload)])

    result = sp.get_league_strengths(
        "bl1", make_standings_table([10, 11, 12, 13]),
        use_squad_data=False, current_season=2026,
    )
    prov = result["summary"]["provenance"]

    assert prov["competition"] == "BL1"
    assert prov["season"] == 2026
    assert prov["computed_at"]
    assert prov["source"]
    assert "matches_through_date" in prov
    assert "sample_size" in prov
    assert prov["historical_seasons_used"] == [2025]


def test_provenance_reports_actual_data_basis(monkeypatch):
    """
    matches_through_date ist der wichtigste Eintrag: Er zeigt, worauf die
    Berechnung TATSAECHLICH beruhte, nicht was erlaubt gewesen waere.
    """
    import src.features.strength_provider as sp
    from tests.conftest import make_historical_payload

    payload = make_historical_payload([10, 11, 12, 13], season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, payload)])

    current = [
        {"date": "2026-08-15", "home_id": 10, "away_id": 11,
         "home_goals": 2, "away_goals": 1},
        {"date": "2026-08-22", "home_id": 12, "away_id": 13,
         "home_goals": 0, "away_goals": 0},
    ]

    result = sp.get_league_strengths(
        "bl1", make_standings_table([10, 11, 12, 13], played=1),
        current_matches=current, use_squad_data=False, current_season=2026,
    )
    prov = result["summary"]["provenance"]

    assert prov["matches_through_date"] == "2026-08-22"
    assert prov["sample_size"] == 2


def test_cl_strengths_carry_provenance(monkeypatch):
    import src.features.strength_provider as sp

    monkeypatch.setattr(sp, "_blend_top5_league_history_by_id", lambda *a, **k: {})
    monkeypatch.setattr(sp, "get_all_matches", lambda *a, **k: [])

    result = sp.get_cl_team_strengths(2026)
    prov = result["provenance"]

    assert prov["competition"] == "CL"
    assert prov["season"] == 2026
    assert prov["computed_at"]
    assert prov["league_avg_from_real_matches"] is False


def test_provenance_does_not_change_computation(monkeypatch):
    """
    Provenienz sind reine Zusatzangaben. Die berechneten Profile muessen
    identisch bleiben.
    """
    import src.features.strength_provider as sp
    from tests.conftest import make_historical_payload

    payload = make_historical_payload([10, 11, 12, 13], season=2025)
    monkeypatch.setattr(sp, "load_available_seasons", lambda *a, **k: [(2025, payload)])

    standings = make_standings_table([10, 11, 12, 13])
    first = sp.get_league_strengths("bl1", standings, use_squad_data=False)
    second = sp.get_league_strengths("bl1", standings, use_squad_data=False)

    assert first["profiles"] == second["profiles"]
    assert first["league_avg"] == second["league_avg"]
