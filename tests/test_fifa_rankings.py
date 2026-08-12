"""Focused contract tests for private FIFA Top-20 ranking snapshots."""

import json

import pytest

from src.data import fifa_rankings as fr


@pytest.fixture(autouse=True)
def _clean_cache():
    fr.clear_cache()
    yield
    fr.clear_cache()


def _real_snapshots_available():
    return all(fr.load_snapshot(year)["available"] for year in range(2021, 2027))


requires_real_data = pytest.mark.skipif(
    not _real_snapshots_available(),
    reason="private FIFA snapshots liegen auf diesem Host nicht vollstaendig vor",
)


def _valid_snapshot(year=2021):
    return {
        "year": year,
        "snapshot_date": f"{year}-12-22",
        "ranking_type": "fifa_mens_world_ranking_top20",
        "status": "final",
        "source": "FIFA Men's World Ranking",
        "notes": None,
        "team_identity": {
            "id_scheme": "API-Football numeric team id",
            "id_source": "test fixture",
            "resolution_rule": "Exact numeric identity only",
            "unresolved_teams": [],
        },
        "teams": [
            {
                "rank": rank,
                "team_name": f"Team {rank}",
                "team_name_en": f"Team {rank}",
                "points": 2000.0 - rank,
                "apisports_team_id": 1000 + rank,
                "apisports_resolution_confidence": "high",
                "apisports_resolution_method": "exact test identity",
            }
            for rank in range(1, 21)
        ],
    }


def _write_snapshot(directory, raw, year=2021):
    (directory / f"fifa_rankings_{year}.json").write_text(
        json.dumps(raw), encoding="utf-8")


class TestLoading:
    @pytest.mark.parametrize("year", range(2021, 2027))
    @requires_real_data
    def test_private_snapshots_2021_bis_2026_sind_vollstaendig_validiert(self, year):
        snapshot = fr.load_snapshot(year)
        assert snapshot["available"] is True
        assert snapshot["year"] == year
        assert snapshot["team_count"] == fr.FIFA_TOP_RANK
        assert set(entry["rank"] for entry in snapshot["by_team_id"].values()) == set(range(1, 21))

    @requires_real_data
    def test_2022_hat_korrekte_metadaten_und_grenzen(self):
        snapshot = fr.load_snapshot(2022)
        assert snapshot["snapshot_date"] == "2022-12-22"
        assert snapshot["status"] == "final"
        assert fr.lookup_team(2022, 6)["rank"] == 1
        assert fr.lookup_team(2022, 12)["rank"] == 20

    def test_fehlendes_jahr_faellt_neutral_aus(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        fr.clear_cache()

        snapshot = fr.load_snapshot(2022)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "missing_file"
        assert fr.lookup_team(2022, 6) is None
        assert fr.is_top20(2022, 6) is False

    def test_malformedes_json_faellt_neutral_aus(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        (tmp_path / "fifa_rankings_2022.json").write_text("{kaputt", encoding="utf-8")
        fr.clear_cache()

        snapshot = fr.load_snapshot(2022)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "unreadable"

    def test_doppelte_raenge_verwerfen_den_gesamten_snapshot(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        raw = _valid_snapshot()
        raw["teams"][-1]["rank"] = 19
        _write_snapshot(tmp_path, raw)
        fr.clear_cache()

        snapshot = fr.load_snapshot(2021)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "duplicate_rank"
        assert snapshot["by_team_id"] == {}

    def test_doppelte_team_ids_verwerfen_den_gesamten_snapshot(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        raw = _valid_snapshot()
        raw["teams"][-1]["apisports_team_id"] = raw["teams"][0]["apisports_team_id"]
        _write_snapshot(tmp_path, raw)
        fr.clear_cache()

        snapshot = fr.load_snapshot(2021)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "duplicate_team_id"

    def test_unaufgeloeste_teamidentitaet_verwirft_den_snapshot(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        raw = _valid_snapshot()
        raw["team_identity"]["unresolved_teams"] = ["Team 3"]
        _write_snapshot(tmp_path, raw)
        fr.clear_cache()

        snapshot = fr.load_snapshot(2021)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "unresolved_team_identity"


class TestLookup:
    def test_exakte_top20_grenze_und_keine_namensaufloesung(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        _write_snapshot(tmp_path, _valid_snapshot())
        fr.clear_cache()

        assert fr.lookup_team(2021, 1001)["rank"] == 1
        assert fr.lookup_team(2021, 1020)["rank"] == 20
        assert fr.is_top20(2021, 1001) is True
        assert fr.is_top20(2021, 1020) is True
        # Es gibt bewusst keinen Namen-Fallback fuer ein vermeintliches #21-Team.
        assert fr.lookup_team(2021, 1021) is None
        assert fr.is_top20(2021, 1021) is False
        assert fr.lookup_team(2021, "Team 1") is None

    def test_jahresbindung_hat_keinen_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        _write_snapshot(tmp_path, _valid_snapshot(2021), year=2021)
        fr.clear_cache()

        assert fr.lookup_team(2021, 1001) is not None
        assert fr.lookup_team(2022, 1001) is None
        assert fr.load_snapshot(2022)["reason"] == "missing_file"

    def test_verfuegbare_jahre_sind_nur_validierte_jahre(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fr, "FIFA_RANKING_DIR", str(tmp_path))
        _write_snapshot(tmp_path, _valid_snapshot(2021), year=2021)
        _write_snapshot(tmp_path, _valid_snapshot(2023), year=2023)
        fr.clear_cache()

        assert fr.available_years(2021, 2024) == [2021, 2023]
        assert fr.available_years(2024, 2021) == []
