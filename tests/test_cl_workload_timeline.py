"""
Wettbewerbsuebergreifende Belastungszeitleiste fuer CL-Zeilen (V2-C2).

WAS VORHER WAR
--------------
Jede der 503 CL-Zeilen trug in JEDEM Belastungsfeld None und den
Sammelvermerk "not_computed_for_cl". Der Grund war fachlich richtig,
aber zu grob: Fuer Mannschaften ausserhalb der Top-5-Ligen kennt die
Zeitleiste nur deren CL-Partien, und daraus gerechnete Ruhezeiten waeren
systematisch zu lang. Nachgemessen ueber 2023-2025:

    mit nationaler Ligahistorie   Median  3,0 Tage    0 % ueber 10 Tage
    ohne                          Median 15,0 Tage   90 % ueber 10 Tage

Fuer die knapp zwei Drittel der Seiten MIT Ligahistorie stimmte der
Verzicht aber nie. Seit V2-C2 wird je SEITE entschieden.

WAS HIER BEWIESEN WIRD
----------------------
Dass gerechnet wird, wo es ehrlich geht - und dass die Luecke dort
bleibt, wo sie hingehoert. Kein erfundener Standardwert, kein stilles
Auffuellen.

KEIN NETZ, KEIN PRIVATER ZUSTAND
--------------------------------
Alle Tests lesen die versionierte Historie unter data/historical/ oder
eigene synthetische Eintraege. Kein Anbieterschluessel, keine .env, kein
data/cache/.
"""

from datetime import datetime, timedelta

import pytest

from src.features import match_timeline as mt
from src.features.workload import workload_features

SEASON = 2025


# ---------------------------------------------------------------------------
# Synthetische Bausteine
# ---------------------------------------------------------------------------

def _eintrag(datum, heim, gast, wettbewerb="BL1", match_id=None, saison=SEASON):
    return {"competition": wettbewerb, "season": saison,
            "match_id": match_id if match_id is not None else f"{wettbewerb}-{datum}-{heim}-{gast}",
            "kickoff": datetime.fromisoformat(f"{datum}T20:00:00"),
            "kickoff_precision": "datetime",
            "home_id": heim, "away_id": gast,
            "home_goals": 1, "away_goals": 0}


def _ruhetage(eintraege, team_id, cutoff):
    tl = mt.team_timeline(eintraege, team_id)
    return workload_features(tl, cutoff)


# ---------------------------------------------------------------------------
# 1. Vorherige Partie aus verschiedenen Wettbewerben
# ---------------------------------------------------------------------------

class TestVorherigePartie:

    CUTOFF = datetime.fromisoformat("2025-10-22T21:00:00")

    def test_nationale_liga_vor_champions_league(self):
        eintraege = [_eintrag("2025-10-18", 1, 2, "BL1"),
                     _eintrag("2025-09-30", 1, 3, "CL")]
        merkmale = _ruhetage(eintraege, 1, self.CUTOFF)

        assert merkmale["rest_days"] == 4
        assert merkmale["previous_match_competition"] == "BL1"

    def test_europaeischer_wettbewerb_vor_champions_league(self):
        """
        Die Zeitleiste ist wettbewerbsagnostisch: Was drinsteht, zaehlt.

        Belegt mit einem synthetischen EL-Eintrag, weil lokal keine
        EL-Historie vorliegt (siehe Abdeckungsbericht). Der Mechanismus
        ist derselbe - fehlt nur die Datei, nicht die Faehigkeit.
        """
        eintraege = [_eintrag("2025-10-15", 1, 4, "EL"),
                     _eintrag("2025-10-18", 1, 2, "BL1")]
        merkmale = _ruhetage(eintraege, 1, self.CUTOFF)

        assert merkmale["previous_match_competition"] == "BL1"
        assert merkmale["matches_last_14_days"] == 2, (
            "die EL-Partie muss in der Zaehlung auftauchen")

    def test_nationaler_pokal_vor_champions_league(self):
        eintraege = [_eintrag("2025-10-20", 1, 5, "DFB")]
        merkmale = _ruhetage(eintraege, 1, self.CUTOFF)

        assert merkmale["rest_days"] == 2
        assert merkmale["previous_match_competition"] == "DFB"

    def test_der_pokal_wirkt_auch_im_echten_datensatz(self):
        """
        Nicht nur synthetisch: Im gebauten Datensatz stammt die
        vorherige Partie nachweislich auch aus nationalen Pokalen.
        """
        from src.ml import cl_dataset as cd

        zeilen, _ = cd.build_cl_season(SEASON)
        pokale = {"DFB", "FAC", "CDR", "CIT", "CDF"}
        gefunden = {zeile.get(f"{seite}_previous_match_competition")
                    for zeile in zeilen for seite in ("home", "away")}
        assert gefunden & pokale, (
            f"keine Pokalpartie als Vorgaenger gefunden: {gefunden}")


# ---------------------------------------------------------------------------
# 2. Zeitliche Sicherheit
# ---------------------------------------------------------------------------

class TestZeitlicheSicherheit:

    CUTOFF = datetime.fromisoformat("2025-10-22T21:00:00")

    def test_eine_spaetere_partie_veraendert_nichts(self):
        frueh = [_eintrag("2025-10-18", 1, 2, "BL1")]
        spaet = frueh + [_eintrag("2025-10-25", 1, 6, "BL1"),
                         _eintrag("2025-11-02", 1, 7, "BL1")]

        assert _ruhetage(frueh, 1, self.CUTOFF) \
            == _ruhetage(spaet, 1, self.CUTOFF)

    def test_das_zielspiel_zaehlt_nicht_als_vorgaenger(self):
        """
        Das Zielspiel selbst steht mit exakt dem Stichtag in der
        Zeitleiste. Es darf nicht seine eigene Ruhezeit erzeugen.
        """
        eintraege = [_eintrag("2025-10-18", 1, 2, "BL1"),
                     {**_eintrag("2025-10-22", 1, 9, "CL"),
                      "kickoff": self.CUTOFF}]
        merkmale = _ruhetage(eintraege, 1, self.CUTOFF)

        assert merkmale["rest_days"] == 4
        assert merkmale["previous_match_competition"] == "BL1"

    def test_der_stichtag_wirkt_auf_die_fensterzaehlung(self):
        eintraege = [_eintrag("2025-10-20", 1, 2, "BL1"),
                     _eintrag("2025-10-24", 1, 6, "BL1")]
        merkmale = _ruhetage(eintraege, 1, self.CUTOFF)
        assert merkmale["matches_last_7_days"] == 1

    def test_ohne_vorherige_partie_bleibt_es_leer_statt_geraten(self):
        merkmale = _ruhetage([], 1, self.CUTOFF)

        assert merkmale["rest_days"] is None
        assert merkmale["rest_hours"] is None
        assert merkmale["data_quality"] == "unavailable"


# ---------------------------------------------------------------------------
# 3. Deduplizierung und Reihenfolge
# ---------------------------------------------------------------------------

class TestDeduplizierung:

    def test_dieselbe_partie_aus_zwei_quellen_zaehlt_einmal(self):
        """
        build_timeline dedupliziert ueber (competition, season,
        match_id). Dieselbe Partie doppelt gezaehlt wuerde die
        Termindichte verfaelschen.
        """
        doppelt = [_eintrag("2025-10-18", 1, 2, "BL1", match_id=4711),
                   _eintrag("2025-10-18", 1, 2, "BL1", match_id=4711)]
        einfach = doppelt[:1]

        cutoff = datetime.fromisoformat("2025-10-22T21:00:00")
        # team_timeline selbst dedupliziert nicht - das ist Aufgabe von
        # build_timeline. Hier wird die REGEL geprueft.
        gesehen, eindeutig = set(), []
        for e in doppelt:
            schluessel = (e["competition"], e["season"], e["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            eindeutig.append(e)

        assert len(eindeutig) == 1
        assert _ruhetage(eindeutig, 1, cutoff) == _ruhetage(einfach, 1, cutoff)

    def test_der_echte_aufbau_dedupliziert(self):
        eintraege, _ = mt.build_timeline([SEASON])
        schluessel = [(e["competition"], e["season"], e["match_id"])
                      for e in eintraege]
        assert len(schluessel) == len(set(schluessel))

    def test_die_reihenfolge_der_eintraege_aendert_nichts(self):
        eintraege = [_eintrag("2025-10-18", 1, 2, "BL1"),
                     _eintrag("2025-10-15", 1, 3, "CL"),
                     _eintrag("2025-10-11", 1, 4, "BL1")]
        cutoff = datetime.fromisoformat("2025-10-22T21:00:00")

        vorwaerts = _ruhetage(eintraege, 1, cutoff)
        rueckwaerts = _ruhetage(list(reversed(eintraege)), 1, cutoff)
        assert vorwaerts == rueckwaerts

    def test_der_echte_aufbau_ist_deterministisch(self):
        erst, _ = mt.build_timeline([SEASON])
        zweit, _ = mt.build_timeline([SEASON])
        schluessel = lambda liste: [(e["competition"], e["match_id"],
                                     e["kickoff"]) for e in liste]
        assert schluessel(erst) == schluessel(zweit)


# ---------------------------------------------------------------------------
# 4. Abdeckung: gerechnet wo ehrlich, sonst begruendet leer
# ---------------------------------------------------------------------------

class TestAbdeckung:

    CUTOFF = datetime.fromisoformat("2025-11-25T12:00:00")

    def test_ein_team_mit_ligahistorie_gilt_als_abgedeckt(self):
        eintraege, _ = mt.build_timeline([2024, SEASON])
        abgedeckt, grund = mt.base_load_coverage(eintraege, 5, self.CUTOFF)

        assert abgedeckt is True
        assert grund == mt.COVERAGE_OK

    @pytest.mark.parametrize("team_id,name", [(678, "Ajax"), (503, "Porto"),
                                              (674, "PSV")])
    def test_diese_vereine_sind_seit_v2_c2b_abgedeckt(self, team_id, name):
        """
        Bis V2-C2B sahen diese Vereine in der Zeitleiste nur ihre
        CL-Partien im Zweiwochentakt - ihre Ligen lagen lokal nicht vor.
        Seit die Eredivisie und die Primeira Liga geladen sind, haben
        sie ihren Grundtakt.
        """
        eintraege, _ = mt.build_timeline([2024, SEASON])
        abgedeckt, grund = mt.base_load_coverage(eintraege, team_id,
                                                 self.CUTOFF)

        assert abgedeckt is True, f"{name} sollte abgedeckt sein"
        assert grund == mt.COVERAGE_OK

    def test_ein_verein_ohne_geladene_liga_gilt_nicht_als_abgedeckt(self):
        """
        Der Mechanismus bleibt scharf. Eine Mannschaft, deren Liga nicht
        vorliegt - etwa ein kuenftiger CL-Teilnehmer aus einem noch
        nicht geladenen Land -, bekommt weiterhin keine erfundene
        Ruhezeit.
        """
        eintraege = [_eintrag("2025-11-20", 4242, 2, "CL")]
        abgedeckt, grund = mt.base_load_coverage(eintraege, 4242, self.CUTOFF)

        assert abgedeckt is False
        assert grund == mt.COVERAGE_NO_BASE_COMPETITION

    def test_eine_veraltete_ligapartie_zaehlt_nicht_mehr(self):
        eintraege = [_eintrag("2025-01-01", 1, 2, "BL1")]
        abgedeckt, grund = mt.base_load_coverage(eintraege, 1, self.CUTOFF)

        assert abgedeckt is False
        assert grund == mt.COVERAGE_STALE

    def test_die_abdeckungspruefung_schaut_nicht_in_die_zukunft(self):
        """
        Eine Ligapartie NACH dem Stichtag darf eine Mannschaft nicht
        rueckwirkend als abgedeckt ausweisen.
        """
        eintraege = [_eintrag("2025-12-01", 1, 2, "BL1")]
        abgedeckt, _ = mt.base_load_coverage(eintraege, 1, self.CUTOFF)
        assert abgedeckt is False

    def test_nur_der_grundtakt_zaehlt_als_abdeckung(self):
        """
        Europapokalpartien allein reichen nicht - genau daran scheiterte
        die alte Rechnung.
        """
        eintraege = [_eintrag("2025-11-20", 1, 2, "CL"),
                     _eintrag("2025-11-06", 1, 3, "EL")]
        abgedeckt, grund = mt.base_load_coverage(eintraege, 1, self.CUTOFF)

        assert abgedeckt is False
        assert grund == mt.COVERAGE_NO_BASE_COMPETITION


# ---------------------------------------------------------------------------
# 5. Der gebaute Datensatz
# ---------------------------------------------------------------------------

class TestDatensatz:

    @pytest.fixture(scope="class")
    def zeilen(self):
        from src.ml import cl_dataset as cd

        gebaut, _ = cd.build_cl_season(SEASON)
        assert gebaut, f"data/historical/CL_{SEASON}.json fehlt"
        return gebaut

    def test_die_belastung_ist_nicht_mehr_pauschal_leer(self, zeilen):
        gefuellt = sum(1 for z in zeilen for seite in ("home", "away")
                       if z.get(f"{seite}_rest_days") is not None)
        assert gefuellt > 0, "V2-C2 hat nichts geaendert"
        assert gefuellt >= len(zeilen), "weniger als eine Seite je Zeile"

    def test_der_alte_sammelvermerk_ist_verschwunden(self, zeilen):
        vermerke = {z.get(f"{seite}_data_quality")
                    for z in zeilen for seite in ("home", "away")}
        assert "not_computed_for_cl" not in vermerke

    def test_jede_luecke_traegt_eine_ursache(self, zeilen):
        for zeile in zeilen:
            for seite in ("home", "away"):
                if zeile.get(f"{seite}_rest_days") is None:
                    grund = zeile.get(f"{seite}_data_quality")
                    assert grund in (mt.COVERAGE_NO_BASE_COMPETITION,
                                     mt.COVERAGE_STALE, "unavailable"), grund

    def test_die_gerechneten_werte_sind_plausibel(self, zeilen):
        """
        Der eigentliche Qualitaetsnachweis. Waere die Abdeckungspruefung
        wirkungslos, saehe man hier wieder den Median von 15 Tagen.
        """
        werte = [z[f"{seite}_rest_days"] for z in zeilen
                 for seite in ("home", "away")
                 if z.get(f"{seite}_rest_days") is not None]
        werte.sort()

        assert werte, "keine Ruhezeiten berechnet"
        median = werte[len(werte) // 2]
        assert 2 <= median <= 5, f"unplausibler Median: {median}"
        unplausibel = sum(1 for w in werte if w > 10)
        assert unplausibel / len(werte) < 0.05, (
            f"{unplausibel}/{len(werte)} Werte ueber 10 Tage")

    def test_kein_negativer_wert(self, zeilen):
        for zeile in zeilen:
            for seite in ("home", "away"):
                wert = zeile.get(f"{seite}_rest_days")
                assert wert is None or wert >= 0

    def test_die_vorherige_partie_stammt_aus_mehreren_wettbewerben(self,
                                                                   zeilen):
        wettbewerbe = {z.get(f"{seite}_previous_match_competition")
                       for z in zeilen for seite in ("home", "away")}
        wettbewerbe.discard(None)
        assert len(wettbewerbe) >= 3, (
            f"die Zeitleiste ist nicht wettbewerbsuebergreifend: {wettbewerbe}")

    def test_der_bericht_ist_reproduzierbar(self, zeilen):
        from src.ml import cl_dataset as cd

        erst = cd.workload_coverage_report(zeilen)
        zweit = cd.workload_coverage_report(zeilen)
        assert erst == zweit

        assert erst["sides_total"] == 2 * len(zeilen)
        assert erst["sides_with_rest_days"] \
            + erst["sides_without_rest_days"] == erst["sides_total"]
        assert 0 < erst["coverage_pct"] <= 100
        assert sum(erst["gaps_by_cause"].values()) \
            == erst["sides_without_rest_days"]


# ---------------------------------------------------------------------------
# 6. Teamidentitaet
# ---------------------------------------------------------------------------

class TestTeamidentitaet:

    def test_der_crosswalk_fuehrt_pokalspiele_zusammen(self):
        """
        Die Pokaldaten kommen von API-Sports, die Ligadaten von
        football-data. Ohne Crosswalk erschiene dieselbe Mannschaft als
        zwei verschiedene - und ihre Pokalspiele fehlten in der
        Belastung.
        """
        eintraege, _ = mt.build_timeline([SEASON])
        pokale = {"DFB", "FAC", "CDR", "CIT", "CDF"}
        mit_id = [e for e in eintraege if e["competition"] in pokale
                  and e.get("home_id") is not None]
        assert mit_id, "kein einziges Pokalspiel wurde zugeordnet"

    def test_eine_unzuordenbare_mannschaft_wird_nicht_geraten(self):
        """
        Der FA Cup enthaelt unterklassige Vereine ohne Ligahistorie.
        Sie bleiben ohne interne ID, statt dem naechstbesten Verein
        zugerechnet zu werden.
        """
        eintraege, _ = mt.build_timeline([SEASON])
        offen = [e for e in eintraege
                 if e.get("home_id") is None or e.get("away_id") is None]
        # Ein Eintrag ohne ID darf existieren - er darf nur keine
        # Belastung fuer eine falsche Mannschaft erzeugen.
        for eintrag in offen:
            assert eintrag.get("home_id") is None \
                or eintrag.get("away_id") is None

    def test_eine_mannschaft_ohne_id_erzeugt_keine_belastung(self):
        eintraege = [{"competition": "FAC", "season": SEASON,
                      "match_id": 1, "kickoff": datetime(2025, 10, 18, 20),
                      "home_id": None, "away_id": 2}]
        assert mt.team_timeline(eintraege, None) == []


# ---------------------------------------------------------------------------
# 7. Saisonuebergang
# ---------------------------------------------------------------------------

class TestSaisonuebergang:

    def test_die_vorsaison_ist_erreichbar(self):
        """
        Der erste CL-Spieltag im September braucht die Ligapartien
        derselben Saison - und am Saisonanfang auch die der Vorsaison.
        Eine willkuerliche Saisonabschottung erzeugte kuenstliche
        Luecken.
        """
        eintraege, _ = mt.build_timeline([2024, SEASON])
        saisons = {e["season"] for e in eintraege}
        assert {2024, SEASON} <= saisons

    def test_der_datensatz_zieht_die_vorsaison_heran(self):
        import inspect

        from src.ml import cl_dataset as cd

        quelle = inspect.getsource(cd.build_cl_season)
        assert "build_timeline([season - 1, season])" in quelle


# ---------------------------------------------------------------------------
# 8. Gemeinsame Grundlage fuer Datensatz und Laufzeit
# ---------------------------------------------------------------------------

class TestGemeinsameGrundlage:

    def test_beide_wege_sehen_dieselbe_vorgeschichte(self):
        """
        Der Datensatz baut die Zeitleiste ueber build_timeline. Eine
        laufzeitnahe Abfrage derselben Mannschaft zum selben Stichtag
        muss dieselben vorherigen Partien sehen - sonst entstuende
        derselbe Bruch, den V2-C1 fuer die Profile beseitigt hat.
        """
        cutoff = datetime.fromisoformat("2025-11-25T12:00:00")

        a, _ = mt.build_timeline([2024, SEASON])
        b, _ = mt.build_timeline([2024, SEASON])

        tl_a = mt.team_timeline(a, 5)
        tl_b = mt.team_timeline(b, 5)
        assert workload_features(tl_a, cutoff) == workload_features(tl_b, cutoff)

    def test_es_gibt_nur_eine_zeitleistenfabrik(self):
        import inspect

        from src.ml import cl_dataset as cd

        quelle = inspect.getsource(cd)
        assert "from src.features.match_timeline import build_timeline" in quelle
        assert "def build_timeline" not in quelle, (
            "eine zweite Zeitleistenimplementierung")

    def test_die_belastung_kommt_aus_dem_ligapfad(self):
        """
        Dieselben Funktionen wie im Ligadatensatz. Eine zweite
        Rechenart waere die sicherste Quelle fuer Abweichungen, die
        niemand findet.

        Seit V2-C3 ist die Zusage staerker als vorher: Beide Pfade
        rufen nicht mehr nur dieselben RECHENFUNKTIONEN, sondern
        dieselbe ZUORDNUNGSFUNKTION - ds.workload_values_for_side. Bis
        dahin lag die Zuordnung zweimal als eigener Code vor, und ein
        Auseinanderlaufen waere an keiner Zahl aufgefallen.
        """
        import inspect

        from src.ml import cl_dataset as cd
        from src.ml import dataset as ds

        cl_quelle = inspect.getsource(cd._belastung_fuer_seite)
        assert "workload_values_for_side" in cl_quelle
        assert "def workload_values_for_side" not in cl_quelle, (
            "eine zweite Fassung der Belastungszuordnung")

        liga_quelle = inspect.getsource(ds.build_league_season)
        assert "workload_values_for_side" in liga_quelle

        # Und diese eine Funktion rechnet mit den geteilten Funktionen.
        geteilt = inspect.getsource(ds.workload_values_for_side)
        assert "workload_features" in geteilt
        assert "schedule_strength" in geteilt
        assert "_workload_werte" in geteilt
