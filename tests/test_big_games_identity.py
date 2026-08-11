"""
Tests fuer die UEFA-Snapshots und die Team-Identitaet (Block F1).

Abgedeckt:
  A) Saisonzuordnung (2021 -> 2021/22), keine Verschiebung um eine Saison
  B) Laden, fehlende Datei, kaputtes JSON, doppelte Raenge/IDs
  C) Vorlaeufige Saison 2026/27
  D) IDENTITAET - der wichtigste Teil: kein Klub darf den Koeffizienten
     eines anderen erben (Barcelona/Espanyol-Regression)
  E) Saisonabhaengigkeit der Gegnerstaerke

Zu den Snapshots: die echten Dateien unter data/big_games/uefa_coefficients/
sind bewusst NICHT im Repository (privat, siehe .gitignore). Tests, die
zwingend echte Daten brauchen, ueberspringen sich selbst, wenn die Dateien
fehlen - damit laeuft die Suite auf jedem Host. Alles Uebrige arbeitet mit
synthetischen Snapshots und ist immer aussagekraeftig.
"""

import json

import pytest

from src.data import uefa_coefficients as uc


@pytest.fixture(autouse=True)
def _clean_cache():
    """Der Snapshot-Cache lebt im Prozess - zwischen Tests leeren."""
    uc.clear_cache()
    yield
    uc.clear_cache()


def _real_snapshots_available():
    return uc.load_snapshot(2021)["available"]


requires_real_data = pytest.mark.skipif(
    not _real_snapshots_available(),
    reason="private UEFA-Snapshots liegen auf diesem Host nicht vor",
)


# ===========================================================================
# A) Saisonzuordnung
# ===========================================================================

class TestSeasonMapping:
    @pytest.mark.parametrize("season,label", [
        (2021, "2021/22"),
        (2022, "2022/23"),
        (2023, "2023/24"),
        (2024, "2024/25"),
        (2025, "2025/26"),
        (2026, "2026/27"),
    ])
    def test_kanonische_zuordnung(self, season, label):
        assert uc.season_label(season) == label

    @pytest.mark.parametrize("season,fragment", [
        (2021, "uefa_coefficients_2021_22.json"),
        (2025, "uefa_coefficients_2025_26.json"),
    ])
    def test_dateiname_folgt_derselben_zuordnung(self, season, fragment):
        assert uc.snapshot_path(season).endswith(fragment)

    def test_keine_verschiebung_um_eine_saison(self):
        """
        Ein Spiel der Saison 2023/24 muss den Snapshot 2023/24 benutzen -
        nicht 2022/23 und nicht 2024/25.
        """
        assert uc.season_label(2023) == "2023/24"
        assert uc.season_label(2023) != uc.season_label(2022)
        assert uc.season_label(2023) != uc.season_label(2024)


# ===========================================================================
# B) Laden und Fehlerfaelle
# ===========================================================================

class TestLoading:
    def test_fehlende_datei_faellt_sauber_aus(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()

        snapshot = uc.load_snapshot(2021)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "missing_file"
        assert snapshot["by_team_id"] == {}

    def test_kaputtes_json_crasht_nicht(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text("{kaputt", encoding="utf-8")

        snapshot = uc.load_snapshot(2021)
        assert snapshot["available"] is False
        assert snapshot["reason"] == "unreadable"

    def test_leere_klubliste_gilt_als_nicht_verfuegbar(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text(
            json.dumps({"season": "2021/22", "clubs": []}), encoding="utf-8")

        assert uc.load_snapshot(2021)["available"] is False

    def test_doppelte_raenge_werden_abgewehrt(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text(json.dumps({
            "season": "2021/22",
            "clubs": [
                {"rank": 1, "total_coefficient": 100.0, "apisports_team_id": 111},
                {"rank": 1, "total_coefficient": 90.0, "apisports_team_id": 222},
            ],
        }), encoding="utf-8")

        snapshot = uc.load_snapshot(2021)
        # Der zweite Eintrag mit demselben Rang wird verworfen.
        assert snapshot["club_count"] == 1
        assert 111 in snapshot["by_team_id"]
        assert 222 not in snapshot["by_team_id"]

    def test_doppelte_team_ids_werden_abgewehrt(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text(json.dumps({
            "season": "2021/22",
            "clubs": [
                {"rank": 1, "total_coefficient": 100.0, "apisports_team_id": 111},
                {"rank": 2, "total_coefficient": 90.0, "apisports_team_id": 111},
            ],
        }), encoding="utf-8")

        snapshot = uc.load_snapshot(2021)
        # Der bessere (erste) Rang gewinnt, der zweite wird nicht ueberschrieben.
        assert snapshot["by_team_id"][111]["rank"] == 1

    def test_unaufgeloeste_klubs_werden_nicht_zugeordnet(self, monkeypatch, tmp_path):
        """
        Ein Klub ohne vertrauenswuerdige ID bekommt KEINE Zuordnung. Er
        gilt spaeter schlicht als "nicht in den Top 40" - er darf unter
        keinen Umstaenden den Rang eines anderen Klubs erben.
        """
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text(json.dumps({
            "season": "2021/22",
            "clubs": [
                {"rank": 1, "total_coefficient": 100.0, "apisports_team_id": 111},
                {"rank": 2, "total_coefficient": 90.0, "apisports_team_id": None},
            ],
        }), encoding="utf-8")

        snapshot = uc.load_snapshot(2021)
        assert len(snapshot["by_team_id"]) == 1
        # Der Koeffizient des unaufgeloesten Klubs zaehlt fuer die
        # Spannweite weiterhin mit - er ist ja real vorhanden.
        assert snapshot["min_coefficient"] == 90.0

    def test_unbekannte_team_id_ergibt_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2021_22.json").write_text(json.dumps({
            "season": "2021/22",
            "clubs": [{"rank": 1, "total_coefficient": 100.0, "apisports_team_id": 111}],
        }), encoding="utf-8")

        assert uc.lookup_team(2021, 999999) is None
        assert uc.lookup_team(2021, None) is None


# ===========================================================================
# C) Vorlaeufige Saison
# ===========================================================================

class TestProvisional:
    def test_provisorischer_status_wird_uebernommen(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        (tmp_path / "uefa_coefficients_2026_27.json").write_text(json.dumps({
            "season": "2026/27",
            "status": "provisional",
            "clubs": [{"rank": 1, "total_coefficient": 120.0, "apisports_team_id": 157}],
        }), encoding="utf-8")

        snapshot = uc.load_snapshot(2026)
        assert snapshot["available"] is True
        assert snapshot["provisional"] is True

    @requires_real_data
    def test_echte_saison_2026_ist_vorlaeufig_aber_nutzbar(self):
        snapshot = uc.load_snapshot(2026)
        assert snapshot["provisional"] is True
        assert snapshot["available"] is True
        # Ein Saisonanteil von 0.000 bedeutet NICHT, dass die Klubs schwach
        # sind - der rollierende Gesamtkoeffizient ist weiterhin gueltig.
        assert snapshot["max_coefficient"] > 0

    @requires_real_data
    def test_fruehere_saisons_sind_nicht_vorlaeufig(self):
        for season in (2021, 2022, 2023, 2024, 2025):
            assert uc.load_snapshot(season)["provisional"] is False


# ===========================================================================
# D) Identitaet - Barcelona/Espanyol-Regression
# ===========================================================================
#
# Diese IDs sind gegen echte API-Football-Antworten geprueft.

BARCELONA = 529
ESPANYOL = 540
MAN_CITY = 50
MAN_UNITED = 33
REAL_MADRID = 541
REAL_SOCIEDAD = 548
REAL_BETIS = 543


class TestIdentity:
    @requires_real_data
    def test_barcelona_wird_gefunden(self):
        assert uc.lookup_team(2021, BARCELONA) is not None

    @requires_real_data
    def test_espanyol_erbt_niemals_barcelonas_ranking(self):
        """
        Der reale Vorfall im Projekt: "Barcelona" loeste ueber
        Teilstring-Suche auf "RCD Espanyol de Barcelona" auf. Hier wird
        ausschliesslich ueber stabile IDs aufgeloest - Espanyol war nie
        unter den UEFA-Top-40 und darf deshalb NICHTS zurueckliefern.
        """
        for season in range(2021, 2027):
            assert uc.lookup_team(season, ESPANYOL) is None

    @requires_real_data
    def test_city_und_united_bleiben_getrennt(self):
        city = uc.lookup_team(2021, MAN_CITY)
        united = uc.lookup_team(2021, MAN_UNITED)
        assert city is not None and united is not None
        assert city["rank"] != united["rank"]

    @requires_real_data
    def test_real_familie_bleibt_getrennt(self):
        """Real Madrid, Real Sociedad und Real Betis sind drei Klubs."""
        madrid = uc.lookup_team(2024, REAL_MADRID)
        sociedad = uc.lookup_team(2024, REAL_SOCIEDAD)
        betis = uc.lookup_team(2024, REAL_BETIS)

        assert madrid is not None
        assert sociedad is not None
        assert betis is not None

        ranks = {madrid["rank"], sociedad["rank"], betis["rank"]}
        assert len(ranks) == 3

    @requires_real_data
    def test_keine_doppelten_ids_in_den_echten_snapshots(self):
        for season in range(2021, 2027):
            snapshot = uc.load_snapshot(season)
            if not snapshot["available"]:
                continue
            ids = list(snapshot["by_team_id"].keys())
            assert len(ids) == len(set(ids))

    def test_aufloesung_ausschliesslich_ueber_ids(self):
        """
        Vertragstest: das Modul darf keine Namensaufloesung enthalten.
        Ein Teilstring-Vergleich auf Klubnamen waere genau die Rueckkehr
        des Barcelona/Espanyol-Fehlers.
        """
        import inspect
        source = inspect.getsource(uc)
        assert "club_name.lower()" not in source
        assert ".startswith(" not in source
        # lookup_team nimmt eine ID entgegen, keinen Namen.
        signature = inspect.signature(uc.lookup_team)
        assert "apisports_team_id" in signature.parameters
        assert "name" not in signature.parameters


# ===========================================================================
# E) Saisonabhaengigkeit
# ===========================================================================

class TestSeasonSpecificStrength:
    @requires_real_data
    def test_derselbe_klub_kann_je_saison_anders_stark_sein(self):
        """
        Kernanforderung: es gibt KEINEN dauerhaften Klubwert. Manchester
        United war 2021/22 unter den besten zehn und spaeter deutlich
        schlechter platziert.
        """
        early = uc.lookup_team(2021, MAN_UNITED)
        late = uc.lookup_team(2024, MAN_UNITED)
        assert early is not None and late is not None
        assert early["rank"] != late["rank"]

    @requires_real_data
    def test_snapshots_haben_eigene_spannweiten(self):
        """
        Die Normalisierung erfolgt innerhalb der jeweiligen Saison. Deshalb
        muss jede Saison ihre eigene Spannweite mitbringen.
        """
        a = uc.load_snapshot(2021)
        b = uc.load_snapshot(2024)
        assert a["max_coefficient"] != b["max_coefficient"]

    def test_fehlende_saison_liefert_keine_staerke(self, monkeypatch, tmp_path):
        monkeypatch.setattr(uc, "COEFFICIENT_DIR", str(tmp_path))
        uc.clear_cache()
        assert uc.lookup_team(2020, BARCELONA) is None

    @requires_real_data
    def test_2020_hat_keinen_snapshot(self):
        """
        Ehrliche Untergrenze: API-Football hat Daten fuer 2020/21, aber
        ohne Snapshot gibt es keine Gegnerstaerke - und dann wird hier
        nichts erfunden.
        """
        assert uc.has_season(2020) is False
        assert uc.load_snapshot(2020)["reason"] == "missing_file"

    @requires_real_data
    def test_verfuegbare_saisons_beginnen_2021(self):
        seasons = uc.available_seasons(2018, 2026)
        assert min(seasons) == uc.EARLIEST_COEFFICIENT_SEASON == 2021
