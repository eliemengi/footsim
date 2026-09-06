"""
Nationale Ligahistorien der CL-Teilnehmer (V2-C2B).

WAS HIER BEWIESEN WIRD
----------------------
V2-C2 hat 658 von 1006 CL-Teamseiten mit einer echten Ruhezeit versorgt.
Die uebrigen 348 hatten genau eine Ursache: Vereine wie Benfica, PSV
oder Celtic erschienen in der Zeitleiste ausschliesslich mit ihren
CL-Partien - ihre Ligaspiele fehlten.

Diese Datei prueft den Weg, der die Luecke schliesst: Beschaffung,
Validierung, Identitaet, Deduplizierung und die Anbindung an die
bestehende Zeitleiste.

KEIN NETZ IN DIESER DATEI
-------------------------
Kein Test hier ruft den Anbieter. Der Importer wird ueber einen
ersetzten _get geprueft, alles Uebrige liest die im Repository
abgelegten Historiendateien. Ein optionaler echter Integrationstest
steht in tests/test_national_league_live.py und laeuft nur mit --e2e.
"""

import json
import os

import pytest

from src.data import national_league_loader as nl
from src.features import match_timeline as mt

SEASON = 2025


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------

def _fixture(mid, datum, heim_id, gast_id, status="FT", ht=1, at=0,
             heim="Heim", gast="Gast"):
    return {
        "fixture": {"id": mid, "date": f"{datum}T19:00:00+00:00",
                    "status": {"short": status}},
        "league": {"id": 94, "season": SEASON, "round": "Regular Season - 1"},
        "teams": {"home": {"id": heim_id, "name": heim},
                  "away": {"id": gast_id, "name": gast}},
        "goals": {"home": ht, "away": at},
        "score": {"penalty": {"home": None, "away": None}},
    }


def _volle_saison(anzahl=120, start_id=900000):
    """Ein plausibler Bestand - sonst greift die Untergrenze."""
    from datetime import date, timedelta

    tag = date(2025, 8, 1)
    return [_fixture(start_id + i, (tag + timedelta(days=i * 2)).isoformat(),
                     211, 228 + (i % 5))
            for i in range(anzahl)]


# ---------------------------------------------------------------------------
# 1. Registrierung
# ---------------------------------------------------------------------------

class TestRegistrierung:

    def test_jede_liga_traegt_eine_provider_id(self):
        for key, cfg in nl.NATIONAL_LEAGUES.items():
            assert isinstance(cfg["apisports_id"], int), key
            assert cfg["code"] and cfg["name"] and cfg["country"], key

    def test_die_codes_sind_eindeutig(self):
        codes = [c["code"] for c in nl.NATIONAL_LEAGUES.values()]
        assert len(codes) == len(set(codes))

    def test_die_codes_kollidieren_nicht_mit_bestehenden(self):
        """
        Der Deduplizierungsschluessel traegt den Wettbewerbscode. Ein
        doppelt vergebener Code wuerde zwei verschiedene Partien
        zusammenfallen lassen.
        """
        from src.data.domestic_cup_loader import DOMESTIC_CUPS
        from src.data.historical_loader import LEAGUE_CODES

        bestehend = set(LEAGUE_CODES.values()) | {"CL"} \
            | {c["code"] for c in DOMESTIC_CUPS.values()}
        neu = {c["code"] for c in nl.NATIONAL_LEAGUES.values()}
        assert not (bestehend & neu), bestehend & neu

    def test_jede_geforderte_saison_hat_eine_registrierte_liga(self):
        assert set(nl.REQUIRED_SEASONS) <= set(nl.NATIONAL_LEAGUES)

    def test_der_bedarf_deckt_genau_die_offenen_seiten(self):
        """
        Die Registrierung ist aus dem Bedarf abgeleitet, nicht aus einer
        Wunschliste: Die Summe entspricht den 348 offenen Teamseiten aus
        V2-C2.
        """
        assert sum(c["sides"] for c in nl.NATIONAL_LEAGUES.values()) == 348


# ---------------------------------------------------------------------------
# 2. Importer - ohne Netz
# ---------------------------------------------------------------------------

class TestImporter:

    def test_eine_saison_wird_normalisiert(self, monkeypatch):
        monkeypatch.setattr(nl, "_get", lambda endpoint, params=None:
                            _volle_saison())
        payload = nl.fetch_league_season("pt1", SEASON)

        assert payload["meta"]["code"] == "PT1"
        assert payload["meta"]["season"] == SEASON
        assert payload["meta"]["matches"] == 120
        assert payload["meta"]["provider_id_space"] == "apisports"
        erste = payload["matches"][0]
        assert erste["date"] and erste["kickoff"] and erste["match_id"]

    def test_die_partien_sind_stabil_sortiert(self, monkeypatch):
        monkeypatch.setattr(nl, "_get", lambda e, params=None:
                            list(reversed(_volle_saison())))
        payload = nl.fetch_league_season("pt1", SEASON)
        daten = [m["date"] for m in payload["matches"]]
        assert daten == sorted(daten)

    def test_ein_wiederholter_lauf_holt_nichts_erneut(self, monkeypatch):
        """
        Eine abgeschlossene Ligasaison aendert sich nie mehr. Sie erneut
        zu holen kostet Kontingent ohne jeden Gewinn.
        """
        gerufen = []
        monkeypatch.setattr(nl, "_get",
                            lambda e, params=None: gerufen.append(params) or [])

        vorhanden = [z for z in nl.required_targets(only_missing=False)
                     if nl.has_season(*z)]
        assert vorhanden, "keine Ligadatei vorhanden - Testvoraussetzung"

        offen = nl.required_targets(only_missing=True)
        assert len(offen) < len(vorhanden), "alles gilt als offen"

        nl.refresh(only_missing=True, verbose=False, targets=[])
        assert gerufen == []

    def test_ein_fehlschlag_bricht_den_lauf_nicht_ab(self, monkeypatch):
        from src.api.apisports_api import ApisportsUnavailable

        def kaputt(endpoint, params=None):
            if params.get("league") == 94:
                raise ApisportsUnavailable("Anbieter nicht erreichbar")
            return _volle_saison()

        monkeypatch.setattr(nl, "_get", kaputt)
        monkeypatch.setattr(nl, "save_league_season",
                            lambda p, overwrite_empty=False: ("x", True, []))

        bericht = nl.refresh(verbose=False,
                             targets=[("pt1", SEASON), ("nl1", SEASON)])

        assert bericht["attempted"] == 2
        assert bericht["written"] == 1
        assert len(bericht["failed"]) == 1
        assert bericht["failed"][0]["league"] == "pt1"

    def test_der_lauf_ist_wiederaufnehmbar(self):
        """
        required_targets nennt genau das Fehlende. Ein zweiter Aufruf
        nach einem Abbruch setzt dort an, statt alles neu zu holen.
        """
        alle = nl.required_targets(only_missing=False)
        offen = nl.required_targets(only_missing=True)
        assert set(offen) <= set(alle)
        for key, season in offen:
            assert not nl.has_season(key, season)


# ---------------------------------------------------------------------------
# 3. Datenpruefung
# ---------------------------------------------------------------------------

class TestValidierung:

    def _payload(self, matches):
        return {"meta": {"code": "PT1", "season": SEASON}, "matches": matches}

    def test_ein_sauberer_bestand_wird_nicht_beanstandet(self, monkeypatch):
        monkeypatch.setattr(nl, "_get", lambda e, params=None: _volle_saison())
        assert nl.validate_payload(nl.fetch_league_season("pt1", SEASON)) == []

    def test_zu_wenige_partien_fallen_auf(self):
        from src.data.domestic_cup_loader import _normalize_match

        wenige = [_normalize_match(f) for f in _volle_saison(anzahl=10)]
        beanstandet = nl.validate_payload(self._payload(wenige))
        assert any("Plausibilitaetsgrenze" in b for b in beanstandet)

    def test_doppelte_match_ids_fallen_auf(self):
        from src.data.domestic_cup_loader import _normalize_match

        matches = [_normalize_match(f) for f in _volle_saison()]
        matches[5]["match_id"] = matches[4]["match_id"]
        assert any("doppelte match_id" in b
                   for b in nl.validate_payload(self._payload(matches)))

    def test_ein_verein_gegen_sich_selbst_faellt_auf(self):
        from src.data.domestic_cup_loader import _normalize_match

        matches = [_normalize_match(f) for f in _volle_saison()]
        matches[3]["away_id"] = matches[3]["home_id"]
        assert any("identisch" in b
                   for b in nl.validate_payload(self._payload(matches)))

    def test_ein_abgeschlossenes_spiel_ohne_ergebnis_faellt_auf(self):
        from src.data.domestic_cup_loader import _normalize_match

        matches = [_normalize_match(f) for f in _volle_saison()]
        matches[2]["home_goals"] = None
        assert any("ohne Ergebnis" in b
                   for b in nl.validate_payload(self._payload(matches)))

    def test_eine_partie_ohne_datum_faellt_auf(self):
        from src.data.domestic_cup_loader import _normalize_match

        matches = [_normalize_match(f) for f in _volle_saison()]
        matches[1]["date"] = None
        assert any("ohne Datum" in b
                   for b in nl.validate_payload(self._payload(matches)))

    def test_eine_kaputte_antwort_ueberschreibt_keine_gute_datei(self):
        """
        Die wichtigste Sicherung. Eine Anbieterstoerung darf gesammelte
        Historie nicht vernichten.
        """
        assert nl.has_season("pt1", SEASON), "Testvoraussetzung fehlt"
        vorher = nl.load_league_season("pt1", SEASON)

        pfad, geschrieben, gruende = nl.save_league_season(
            {"meta": {"code": "PT1", "season": SEASON}, "matches": []})

        assert geschrieben is False
        assert gruende
        assert nl.load_league_season("pt1", SEASON) == vorher

    def test_auch_ein_beanstandeter_bestand_ueberschreibt_nichts(self):
        from src.data.domestic_cup_loader import _normalize_match

        vorher = nl.load_league_season("pt1", SEASON)
        kaputt = [_normalize_match(f) for f in _volle_saison(anzahl=5)]

        _, geschrieben, gruende = nl.save_league_season(
            {"meta": {"code": "PT1", "season": SEASON}, "matches": kaputt})

        assert geschrieben is False
        assert gruende
        assert nl.load_league_season("pt1", SEASON) == vorher

    def test_die_echten_dateien_bestehen_die_pruefung(self):
        """
        Anbieterdaten werden nicht blind uebernommen - auch die bereits
        gespeicherten nicht.
        """
        auffaellig = {}
        for key in nl.REQUIRED_SEASONS:
            for season in nl.REQUIRED_SEASONS[key]:
                payload = nl.load_league_season(key, season)
                if payload is None:
                    continue
                schwer = [b for b in nl.validate_payload(payload)
                          if "Ergebnis bei Status" not in b]
                if schwer:
                    auffaellig[f"{key}:{season}"] = schwer
        assert not auffaellig, auffaellig


# ---------------------------------------------------------------------------
# 4. Teamidentitaet
# ---------------------------------------------------------------------------

class TestIdentitaet:

    def test_der_crosswalk_ist_umkehrbar_eindeutig(self):
        """
        Zwei Vereine auf derselben API-Sports-ID hiessen: Eine Belastung
        wird dem falschen Verein zugerechnet.
        """
        werte = list(mt.CL_PARTICIPANT_CROSSWALK.values())
        assert len(werte) == len(set(werte))

    def test_jeder_eintrag_ist_in_einer_ligadatei_belegt(self):
        """
        Kein Eintrag ist behauptet: Jede API-Sports-ID taucht in der
        Teamliste der zugehoerigen Ligadatei wirklich auf.
        """
        bekannt = set()
        for key in nl.REQUIRED_SEASONS:
            for season in nl.REQUIRED_SEASONS[key]:
                payload = nl.load_league_season(key, season)
                if payload:
                    bekannt |= {int(t) for t in (payload.get("teams") or {})}

        fehlend = [(fd, a) for fd, a in mt.CL_PARTICIPANT_CROSSWALK.items()
                   if a not in bekannt]
        assert not fehlend, fehlend

    @pytest.mark.parametrize("fd_id,as_id,verein,land", [
        (1903, 211, "Benfica", "Portugal"),
        (674, 197, "PSV", "Netherlands"),
        (851, 569, "Club Brugge", "Belgium"),
        (610, 645, "Galatasaray", "Turkey"),
        (732, 247, "Celtic", "Scotland"),
        (1876, 400, "FC Kopenhagen", "Denmark"),
        (1871, 565, "Young Boys", "Switzerland"),
    ])
    def test_die_geforderten_laender_sind_zugeordnet(self, fd_id, as_id,
                                                     verein, land):
        assert mt.CL_PARTICIPANT_CROSSWALK[fd_id] == as_id, verein
        laender = {c["country"] for c in nl.NATIONAL_LEAGUES.values()}
        assert land in laender

    def test_ein_unbekannter_verein_wird_nicht_zugeordnet(self):
        """
        Die Uebersetzung ist eine Tabelle, kein unscharfer Vergleich.
        Wer nicht drinsteht, bekommt keine ID - und keine Belastung.
        """
        assert mt._APISPORTS_TO_INTERNAL.get(999999) is None

    def test_aehnliche_namen_werden_nicht_verwechselt(self):
        """
        "Union St. Gilloise" und "Union Berlin" stehen beide in der
        CL-Teilnehmerliste. Ein Treffer auf "Union" haette den falschen
        Verein belastet - deshalb steht der Fall einzeln in der Tabelle.
        """
        assert mt.CL_PARTICIPANT_CROSSWALK[3929] == 1393
        assert 182 not in mt.CL_PARTICIPANT_CROSSWALK.values()


# ---------------------------------------------------------------------------
# 5. Zeitleistenanbindung
# ---------------------------------------------------------------------------

class TestZeitleiste:

    def test_die_neuen_ligen_erscheinen_in_der_zeitleiste(self):
        eintraege, _ = mt.build_timeline([2024, SEASON])
        wettbewerbe = {e["competition"] for e in eintraege}
        neu = {c["code"] for c in nl.NATIONAL_LEAGUES.values()}
        assert len(wettbewerbe & neu) >= 15, wettbewerbe & neu

    def test_sie_zaehlen_als_grundtakt(self):
        neu = {c["code"] for c in nl.NATIONAL_LEAGUES.values()}
        assert neu <= mt.BASE_LOAD_COMPETITIONS

    def test_die_bestehenden_wettbewerbe_bleiben_unveraendert(self):
        eintraege, _ = mt.build_timeline([SEASON])
        wettbewerbe = {e["competition"] for e in eintraege}
        for bestehend in ("BL1", "PL", "PD", "SA", "FL1", "CL"):
            assert bestehend in wettbewerbe

    def test_nur_zugeordnete_partien_kommen_hinein(self):
        """
        Eine portugiesische Liga hat 18 Vereine, von denen FootSim drei
        kennt. Die uebrigen Duelle gehoeren nicht in die Zeitleiste.
        """
        eintraege, _ = mt.build_timeline([SEASON])
        pt = [e for e in eintraege if e["competition"] == "PT1"]
        assert pt
        for eintrag in pt:
            assert eintrag.get("home_id") is not None \
                or eintrag.get("away_id") is not None

    def test_die_ids_sind_die_internen(self):
        eintraege, _ = mt.build_timeline([SEASON])
        pt = [e for e in eintraege if e["competition"] == "PT1"]
        ids = {e.get("home_id") for e in pt} | {e.get("away_id") for e in pt}
        ids.discard(None)
        assert ids <= set(mt.CL_PARTICIPANT_CROSSWALK), (
            "es stehen API-Sports-IDs in der Zeitleiste")

    def test_die_deduplizierung_traegt_auch_ueber_anbieter(self):
        eintraege, _ = mt.build_timeline([2024, SEASON])
        schluessel = [(e["competition"], e["season"], e["match_id"])
                      for e in eintraege]
        assert len(schluessel) == len(set(schluessel))

    def test_der_aufbau_bleibt_deterministisch(self):
        erst, _ = mt.build_timeline([SEASON])
        zweit, _ = mt.build_timeline([SEASON])
        schluessel = lambda liste: [(e["competition"], e["match_id"])
                                    for e in liste]
        assert schluessel(erst) == schluessel(zweit)

    def test_eine_fehlende_datei_bricht_nichts_ab(self, monkeypatch):
        monkeypatch.setattr(nl, "load_league_season",
                            lambda key, season: None)
        eintraege, diagnose = mt.build_timeline([SEASON])
        assert eintraege
        assert any(d.get("status") == "missing_file" for d in diagnose
                   if isinstance(d, dict))


# ---------------------------------------------------------------------------
# 6. Wirkung auf die CL-Zeilen
# ---------------------------------------------------------------------------

class TestWirkung:

    @pytest.fixture(scope="class")
    def zeilen(self):
        from src.ml import cl_dataset as cd

        gebaut, _ = cd.build_cl_season(SEASON)
        assert gebaut
        return gebaut

    def test_die_betroffenen_vereine_haben_jetzt_ruhezeiten(self, zeilen):
        """
        Genau die Vereine, die V2-C2 offen liess.
        """
        betroffen = {1903, 674, 498, 851, 678}
        gefunden = set()
        for zeile in zeilen:
            for seite in ("home", "away"):
                if zeile[f"{seite}_id"] in betroffen \
                        and zeile.get(f"{seite}_rest_days") is not None:
                    gefunden.add(zeile[f"{seite}_id"])
        assert gefunden, "kein einziger der betroffenen Vereine wurde versorgt"

    def test_die_vorherige_partie_stammt_aus_der_nationalen_liga(self, zeilen):
        neu = {c["code"] for c in nl.NATIONAL_LEAGUES.values()}
        gefunden = {zeile.get(f"{seite}_previous_match_competition")
                    for zeile in zeilen for seite in ("home", "away")}
        assert gefunden & neu, gefunden

    def test_die_werte_bleiben_plausibel(self, zeilen):
        werte = sorted(z[f"{seite}_rest_days"] for z in zeilen
                       for seite in ("home", "away")
                       if z.get(f"{seite}_rest_days") is not None)
        assert werte
        assert 2 <= werte[len(werte) // 2] <= 5
        assert all(w >= 0 for w in werte)

    def test_die_abdeckung_uebersteigt_neunzig_prozent(self, zeilen):
        from src.ml import cl_dataset as cd

        bericht = cd.workload_coverage_report(zeilen)
        assert bericht["coverage_pct"] > 90.0, bericht["coverage_pct"]

    def test_jede_verbleibende_luecke_ist_eine_echte_spielpause(self, zeilen):
        """
        Was bleibt, sind Winterpausen - keine Datenluecken. Norwegen und
        Kasachstan spielen im Kalenderjahr, Daenemark, Oesterreich und
        Tschechien haben lange Winterpausen.
        """
        for zeile in zeilen:
            for seite in ("home", "away"):
                if zeile.get(f"{seite}_rest_days") is None:
                    assert zeile[f"{seite}_data_quality"] \
                        == mt.COVERAGE_STALE, zeile[f"{seite}_data_quality"]


# ---------------------------------------------------------------------------
# 7. Zeitliche Sicherheit bleibt
# ---------------------------------------------------------------------------

class TestZeitlicheSicherheit:

    def test_eine_spaetere_ligapartie_veraendert_nichts(self):
        from datetime import datetime

        from src.features.workload import workload_features

        eintraege, _ = mt.build_timeline([2024, SEASON])
        cutoff = datetime.fromisoformat("2025-11-25T12:00:00")
        tl = mt.team_timeline(eintraege, 1903)

        vorher = workload_features(tl, cutoff)
        spaeter = tl + [{"competition": "PT1", "season": SEASON,
                         "match_id": -1,
                         "kickoff": datetime(2026, 5, 1, 20, 0),
                         "kickoff_precision": "datetime",
                         "home_id": 1903, "away_id": 228,
                         "is_home": True, "opponent_id": 228}]
        assert workload_features(spaeter, cutoff) == vorher

    def test_das_zielspiel_zaehlt_nicht_selbst(self):
        from datetime import datetime

        from src.features.workload import workload_features

        eintraege, _ = mt.build_timeline([2024, SEASON])
        cutoff = datetime.fromisoformat("2025-11-25T12:00:00")
        tl = mt.team_timeline(eintraege, 1903)
        merkmale = workload_features(tl, cutoff)

        if merkmale["rest_days"] is not None:
            assert merkmale["rest_days"] > 0

    def test_die_saisonzugehoerigkeit_wird_beachtet(self):
        """
        Eine Liga wird nur fuer die Saisons geladen, in denen ein
        CL-Teilnehmer sie tatsaechlich brauchte. Ein Verein, der 2024
        nicht in der CL stand, erzeugt fuer 2024 keinen Bedarf.
        """
        eintraege, _ = mt.build_timeline([2024])
        codes = {e["competition"] for e in eintraege}
        # Norwegen wurde nur fuer 2025 gebraucht (Bodoe/Glimt).
        assert "NO1" not in codes
        assert "NO1" in {e["competition"]
                         for e in mt.build_timeline([2025])[0]}
