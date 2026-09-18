"""
Tests fuer die Champions-League-Zeilen des ML-Datensatzes.

Die CL-Zeilen sind die Grundlage, auf der spaeter gemessen werden soll,
ob sich ein auf Ligaspielen trainiertes Modell auf die Champions League
uebertragen laesst. Ist diese Grundlage undicht, misst der spaetere
Backtest eine Uebertragung, die es nie gab - und das faellt an keiner
Zahl auf.

Deshalb prueft jeder Test hier eine Eigenschaft, die sich verletzen
laesst, und die Leckagetests arbeiten mit Gegenproben statt mit
Zusicherungen.
"""

import pytest

from src.ml import cl_dataset as cl
from src.ml import dataset as ds

TEST_SAISON = 2024


@pytest.fixture(scope="module")
def cl_zeilen():
    zeilen, _, _ = cl.build_cl_dataset([TEST_SAISON])
    return zeilen


@pytest.fixture(scope="module")
def alle_cl():
    zeilen, gesamt, uebersprungen = cl.build_cl_dataset()
    return zeilen, gesamt, uebersprungen


# ---------------------------------------------------------------------------
# 1. Aufbau und Determinismus
# ---------------------------------------------------------------------------

class TestAufbau:

    def test_zwei_builds_liefern_identische_zeilen(self):
        erst, _, _ = cl.build_cl_dataset([TEST_SAISON])
        zweit, _, _ = cl.build_cl_dataset([TEST_SAISON])
        assert erst == zweit

    def test_es_gibt_keine_zufallswerte(self, cl_zeilen):
        """Gegenprobe zum Determinismustest: die Zeilen sind nicht leer."""
        assert cl_zeilen
        assert any(z["baseline_lambda_home"] for z in cl_zeilen)

    def test_jede_zeile_traegt_alle_schemaspalten(self, cl_zeilen):
        erwartet = set(ds.SPALTEN)
        for zeile in cl_zeilen:
            assert set(zeile) == erwartet, (
                f"Abweichung bei {zeile['row_id']}: "
                f"fehlt {sorted(erwartet - set(zeile))}, "
                f"zuviel {sorted(set(zeile) - erwartet)}")

    def test_row_id_ist_eindeutig(self, alle_cl):
        zeilen, _, _ = alle_cl
        ids = [z["row_id"] for z in zeilen]
        assert len(ids) == len(set(ids))

    def test_alle_drei_saisons_liefern_zeilen(self, alle_cl):
        zeilen, _, uebersprungen = alle_cl
        assert uebersprungen == []
        assert {z["season"] for z in zeilen} == set(cl.DEFAULT_CL_SEASONS)

    def test_die_match_id_kommt_aus_der_quelle(self, cl_zeilen):
        """
        Anders als die Ligadateien fuehren die CL-Dateien eine echte
        match_id. Sie darf nicht verlorengehen.
        """
        assert all(isinstance(z["match_id"], int) for z in cl_zeilen)


# ---------------------------------------------------------------------------
# 2. Wettbewerb und Stage
# ---------------------------------------------------------------------------

class TestWettbewerbUndStage:

    def test_das_wettbewerbskennzeichen_ist_stabil(self, alle_cl):
        zeilen, _, _ = alle_cl
        assert {z["competition"] for z in zeilen} == {"CL"}
        assert {z["league"] for z in zeilen} == {"cl"}

    def test_jede_zeile_traegt_eine_stage(self, alle_cl):
        zeilen, _, _ = alle_cl
        assert all(z["stage"] for z in zeilen)

    def test_die_ko_stages_bleiben_erhalten(self, alle_cl):
        """
        Sie werden nicht ausgewertet, aber auch nicht weggeworfen -
        sonst faenge eine spaetere K.-o.-Analyse bei null an.
        """
        zeilen, _, _ = alle_cl
        stages = {z["stage"] for z in zeilen}
        assert "LAST_16" in stages and "FINAL" in stages

    def test_nur_die_regulaere_phase_ist_auswertbar(self, alle_cl):
        zeilen, _, _ = alle_cl
        for zeile in zeilen:
            if zeile["evaluation_eligible"]:
                assert zeile["stage"] in cl.REGULAR_STAGES

    def test_ko_zeilen_tragen_den_ko_grund(self, alle_cl):
        zeilen, _, _ = alle_cl
        ko = [z for z in zeilen if z["stage"] not in cl.REGULAR_STAGES]
        assert ko
        assert all(z["exclusion_reason"] == cl.KNOCKOUT_NOTE for z in ko)

    def test_beide_formate_sind_vertreten(self, alle_cl):
        """2023 war Gruppenphase, ab 2024 Ligaphase."""
        zeilen, _, _ = alle_cl
        stages = {(z["season"], z["stage"]) for z in zeilen}
        assert (2023, "GROUP_STAGE") in stages
        assert (2024, "LEAGUE_STAGE") in stages


# ---------------------------------------------------------------------------
# 3. Point-in-Time - der Kern
# ---------------------------------------------------------------------------

class TestPointInTime:

    def test_das_zielspiel_steckt_nicht_im_eigenen_profil(self):
        """
        Die Profiltiefe einer Partie darf die Partie selbst nicht
        mitzaehlen. Gegenprobe ueber denselben Stichtag mit
        inclusive=True waere groesser.
        """
        from src.features.point_in_time import matches_known_at

        quellen = cl._Quellen()
        payload = quellen.cl_payload(TEST_SAISON)
        partien = [m for m in payload["matches"]
                   if m.get("stage") == "LEAGUE_STAGE"]
        ziel = sorted(partien, key=lambda m: m["date"])[-1]

        ohne, _, _ = quellen.cl_history(TEST_SAISON, ziel["date"])
        bekannt = matches_known_at([ziel], ziel["date"])
        assert bekannt == [], "das Zielspiel gilt am Stichtag als bekannt"

        for team_id in (ziel["home_id"], ziel["away_id"]):
            profil = ohne.get(team_id)
            if profil is None:
                continue
            eigene = [m for m in partien
                      if team_id in (m["home_id"], m["away_id"])
                      and m["date"] < ziel["date"]]
            assert profil["matches_used"] >= len(eigene)

    def test_ein_zukuenftiges_ergebnis_veraendert_die_zeile_nicht(self,
                                                                 monkeypatch):
        """
        Die harte Gegenprobe: Ein spaeteres Spiel wird kuenstlich
        veraendert. Eine frueher datierte Zeile darf sich davon nicht
        ruehren.
        """
        from src.data import historical_loader

        echt = historical_loader.load_cl_season

        vorher, _ = cl.build_cl_season(TEST_SAISON, cl._Quellen())
        vorher = sorted(vorher, key=lambda z: (z["date"], z["row_id"]))
        grenze = vorher[len(vorher) // 3]["date"]

        def manipuliert(season):
            payload = echt(season)
            if season != TEST_SAISON:
                return payload
            kopie = dict(payload)
            kopie["matches"] = [
                dict(m, home_goals=9, away_goals=0) if m.get("date", "") > grenze
                else m
                for m in payload["matches"]]
            return kopie

        monkeypatch.setattr(historical_loader, "load_cl_season", manipuliert)
        nachher, _ = cl.build_cl_season(TEST_SAISON, cl._Quellen())
        nachher = {z["row_id"]: z for z in nachher}

        geprueft = 0
        for zeile in vorher:
            if zeile["date"] > grenze:
                continue
            neu = nachher[zeile["row_id"]]
            for spalte in ("baseline_lambda_home", "baseline_lambda_away",
                           "home_attack_home", "away_defence_away",
                           "home_profile_matches", "away_profile_matches"):
                assert neu[spalte] == zeile[spalte], (
                    f"{zeile['row_id']}.{spalte} haengt an einem "
                    f"spaeteren Ergebnis")
            geprueft += 1

        assert geprueft > 0, "kein einziger Vergleich - Test waere wertlos"

    def test_die_manipulation_wirkt_ueberhaupt(self, monkeypatch):
        """
        Gegenprobe zur Gegenprobe: Ohne diesen Test koennte der Test
        oben auch dann gruen sein, wenn der Monkeypatch gar nicht
        greift.
        """
        from src.data import historical_loader

        echt = historical_loader.load_cl_season
        vorher, _ = cl.build_cl_season(TEST_SAISON, cl._Quellen())
        vorher = sorted(vorher, key=lambda z: (z["date"], z["row_id"]))
        grenze = vorher[len(vorher) // 3]["date"]

        def manipuliert(season):
            payload = echt(season)
            if season != TEST_SAISON:
                return payload
            kopie = dict(payload)
            kopie["matches"] = [
                dict(m, home_goals=9, away_goals=0) if m.get("date", "") > grenze
                else m
                for m in payload["matches"]]
            return kopie

        monkeypatch.setattr(historical_loader, "load_cl_season", manipuliert)
        nachher, _ = cl.build_cl_season(TEST_SAISON, cl._Quellen())
        nachher = {z["row_id"]: z for z in nachher}

        spaeter = [z for z in vorher if z["date"] > grenze]
        assert spaeter
        assert any(nachher[z["row_id"]]["home_goals"] != z["home_goals"]
                   for z in spaeter), "der Monkeypatch hat nichts veraendert"

    def test_der_ligaschnitt_waechst_monoton(self):
        """
        Die Zahl der bekannten CL-Partien darf ueber die Saison nur
        zunehmen. Ein Rueckgang hiesse, dass ein Stichtag Partien
        verliert, die er kennen muesste.
        """
        quellen = cl._Quellen()
        payload = quellen.cl_payload(TEST_SAISON)
        daten = sorted({m["date"] for m in payload["matches"]})

        # cl_history liefert seit V2-C1 die LISTE der benutzten Partien
        # (der Aufrufer baut daraus seine Herkunftsangabe), nicht nur
        # ihre Anzahl. Die Zusicherung bleibt dieselbe.
        vorher = -1
        for datum in daten:
            _, _, bekannt = quellen.cl_history(TEST_SAISON, datum)
            assert len(bekannt) >= vorher
            vorher = len(bekannt)


# ---------------------------------------------------------------------------
# 4. Profilkaskade und Herkunft
# ---------------------------------------------------------------------------

class TestProfilkaskade:

    def test_die_herkunft_ist_maschinenlesbar(self, alle_cl):
        zeilen, _, _ = alle_cl
        erlaubt = set(cl.PROFILE_SOURCES)
        for zeile in zeilen:
            assert zeile["home_profile_source"] in erlaubt
            assert zeile["away_profile_source"] in erlaubt

    def test_auf_echten_daten_traegt_nur_noch_die_erste_stufe(
            self, alle_cl):
        """
        GEAENDERT IN V2-C13, und die Aenderung ist das Ergebnis.

        Vorher forderte dieser Test, dass ALLE drei Stufen in echten
        Daten vorkommen. Das war damals eine sinnvolle Gegenprobe:
        Kaeme eine Stufe nie vor, pruefte der Test darueber nur eine
        leere Menge.

        Inzwischen ist das Vorkommen der Stufen zwei und drei kein
        Gesundheitszeichen mehr, sondern ein Symptom. Sie traten auf,
        weil der Profilpfad nur fuenf der 23 vorhandenen Ligadateien
        las. 321 von 1006 Teamseiten bekamen daraufhin ein Profil aus
        ihren eigenen CL-Partien, im Extremfall aus einer einzigen. In
        V2-C12 kostete genau diese Gruppe die Freigabe.

        Seit der Reparatur hat jede Teamseite ein nationales Profil.
        Die Kaskade ist deswegen nicht tot: Dass jede ihrer Stufen
        funktioniert, zeigen die drei Tests darunter an gebauten
        Eingaben, unabhaengig davon, was gerade auf der Platte liegt.
        Ein Test, der die Stufen in echten Daten ERZWINGT, wuerde
        dagegen verlangen, dass die Datenluecke bestehen bleibt.
        """
        zeilen, _, _ = alle_cl
        vorhanden = {z["home_profile_source"] for z in zeilen}
        vorhanden |= {z["away_profile_source"] for z in zeilen}
        assert vorhanden == {cl.SOURCE_DOMESTIC}, vorhanden

    def test_jede_stufe_der_kaskade_bleibt_erreichbar(self):
        """
        Die Gegenprobe an ihrem neuen Ort.

        Sie haengt jetzt an gebauten Eingaben statt an der Datenlage.
        Damit bleibt sie aussagekraeftig, egal wie vollstaendig die
        Ligadateien gerade sind - und sie faellt sofort auf, wenn
        jemand eine Stufe aus resolve_profile entfernt.
        """
        stufen = {
            cl.resolve_profile(7, "Test", {7: {"matches_used": 30}},
                               {7: {"matches_used": 99}})[1],
            cl.resolve_profile(7, "Test", {},
                               {7: {"matches_used": 12}})[1],
            cl.resolve_profile(7, "Test", {}, {})[1],
        }
        assert stufen == set(cl.PROFILE_SOURCES)

    def test_die_ligahistorie_hat_vorrang(self):
        domestic = {7: {"matches_used": 30, "attack_home": 1.2}}
        cl_profile = {7: {"matches_used": 99, "attack_home": 0.5}}
        profil, quelle, tiefe = cl.resolve_profile(7, "Test", domestic,
                                                   cl_profile)
        assert quelle == cl.SOURCE_DOMESTIC
        assert tiefe == 30

    def test_cl_historie_ist_die_zweite_stufe(self):
        cl_profile = {7: {"matches_used": 12, "attack_home": 0.9}}
        profil, quelle, tiefe = cl.resolve_profile(7, "Test", {}, cl_profile)
        assert quelle == cl.SOURCE_CL_HISTORY
        assert tiefe == 12

    def test_neutral_ist_der_letzte_ausweg(self):
        profil, quelle, tiefe = cl.resolve_profile(7, "Test", {}, {})
        assert quelle == cl.SOURCE_NEUTRAL
        assert tiefe == 0
        assert profil["team_id"] == 7

    def test_die_profiltiefe_passt_zur_herkunft(self, alle_cl):
        zeilen, _, _ = alle_cl
        for zeile in zeilen:
            for seite in ("home", "away"):
                quelle = zeile[f"{seite}_profile_source"]
                tiefe = zeile[f"{seite}_profile_matches"]
                if quelle == cl.SOURCE_NEUTRAL:
                    assert tiefe == 0
                else:
                    assert tiefe > 0

    def test_neutrale_profile_werden_nie_ausgewertet(self, alle_cl):
        zeilen, _, _ = alle_cl
        for zeile in zeilen:
            if cl.SOURCE_NEUTRAL in (zeile["home_profile_source"],
                                     zeile["away_profile_source"]):
                assert not zeile["evaluation_eligible"]

    def test_die_cl_historie_bleibt_als_rueckfall_funktionsfaehig(self):
        """
        GEAENDERT IN V2-C13.

        Vorher verlangte dieser Test, dass die CL-Vorgeschichte in
        Saison 2025 wirklich als Quelle auftaucht. Seit alle 23
        nationalen Ligen gelesen werden, tut sie das nicht mehr, und
        das ist die Verbesserung, nicht der Fehler.

        Wofuer die Stufe weiterhin da ist: einen Verein, dessen
        nationale Liga nicht vorliegt. Genau dieser Fall wird hier
        gebaut, statt darauf zu warten, dass er in den Daten steht.
        """
        profil, quelle, tiefe = cl.resolve_profile(
            7, "Verein ohne Ligadatei", {}, {7: {"matches_used": 12}})
        assert quelle == cl.SOURCE_CL_HISTORY
        assert tiefe == 12
        assert profil is not None

    def test_kein_verein_braucht_den_rueckfall_noch(self, alle_cl):
        """
        Die positive Aussage von C13 an derselben Stelle: Es gibt
        keinen CL-Verein mehr ohne nationale Historie.
        """
        zeilen, _, _ = alle_cl
        ohne = [(z["season"], z["date"], z[seite + "_id"])
                for z in zeilen for seite in ("home", "away")
                if z[seite + "_profile_source"] != cl.SOURCE_DOMESTIC]
        assert ohne == [], ohne[:5]


# ---------------------------------------------------------------------------
# 5. Eligibility und Ausschlussgruende
# ---------------------------------------------------------------------------

class TestEligibility:

    def test_jede_nicht_auswertbare_zeile_nennt_einen_grund(self, alle_cl):
        zeilen, _, _ = alle_cl
        for zeile in zeilen:
            if zeile["evaluation_eligible"]:
                assert zeile["exclusion_reason"] is None
            else:
                assert zeile["exclusion_reason"]

    def test_zu_duenne_profile_werden_ausgeschlossen(self, alle_cl):
        zeilen, _, _ = alle_cl
        for zeile in zeilen:
            if not zeile["evaluation_eligible"]:
                continue
            assert min(zeile["home_profile_matches"],
                       zeile["away_profile_matches"]) >= cl.MIN_PROFILE_MATCHES

    def test_die_gruende_sind_reproduzierbar(self):
        """Feste Pruefreihenfolge - sonst haengt der Grund am Zufall."""
        grund = cl._ausschlussgrund(
            "LAST_16", (cl.SOURCE_NEUTRAL, cl.SOURCE_DOMESTIC), (0, 30), 6)
        assert grund == cl.KNOCKOUT_NOTE

        grund = cl._ausschlussgrund(
            "LEAGUE_STAGE", (cl.SOURCE_NEUTRAL, cl.SOURCE_DOMESTIC), (0, 30), 6)
        assert "neutral_profile" in grund

        grund = cl._ausschlussgrund(
            "LEAGUE_STAGE", (cl.SOURCE_DOMESTIC, cl.SOURCE_DOMESTIC), (3, 30), 6)
        assert "Profiltiefe" in grund

        assert cl._ausschlussgrund(
            "LEAGUE_STAGE", (cl.SOURCE_DOMESTIC,) * 2, (30, 30), 6) is None


# ---------------------------------------------------------------------------
# 6. Was CL-Zeilen bewusst NICHT tragen
# ---------------------------------------------------------------------------

class TestFehlendeBelastung:

    def test_die_belastung_wird_berechnet_wo_sie_ehrlich_moeglich_ist(
            self, cl_zeilen):
        """
        Bis V2-C2 blieb JEDE Seite leer. Der Grund galt aber nur fuer
        Mannschaften ausserhalb der Top-5-Ligen - fuer die uebrigen
        rund zwei Drittel lag die Belastung sauber vor.
        """
        gefuellt = sum(1 for z in cl_zeilen for seite in ("home", "away")
                       if z.get(f"{seite}_rest_days") is not None)
        assert gefuellt > 0

    def test_eine_luecke_traegt_ihre_ursache_statt_eines_sammelvermerks(
            self, cl_zeilen):
        """
        "not_computed_for_cl" verbarg vier verschiedene Faelle unter
        einem Namen. Jetzt steht dort, WARUM nichts berechnet wurde.
        """
        from src.features import match_timeline as mt

        erlaubt = {mt.COVERAGE_NO_BASE_COMPETITION, mt.COVERAGE_STALE,
                   "unavailable", "complete", "partial"}
        for zeile in cl_zeilen:
            for seite in ("home", "away"):
                vermerk = zeile[f"{seite}_data_quality"]
                assert vermerk != "not_computed_for_cl"
                assert vermerk in erlaubt, vermerk
                if zeile.get(f"{seite}_rest_days") is None:
                    assert vermerk != "complete"

    def test_die_gerechneten_ruhezeiten_sind_plausibel(self, cl_zeilen):
        """
        Der Qualitaetsnachweis: Ohne die Abdeckungspruefung laege der
        Median bei 15 Tagen statt bei drei.
        """
        werte = sorted(z[f"{seite}_rest_days"] for z in cl_zeilen
                       for seite in ("home", "away")
                       if z.get(f"{seite}_rest_days") is not None)
        assert werte
        assert 2 <= werte[len(werte) // 2] <= 5

    def test_der_cl_kandidat_braucht_keine_dieser_spalten(self, cl_zeilen):
        """
        Die Gegenprobe zur Luecke: Der vorgesehene Merkmalssatz muss
        vollstaendig berechenbar sein.
        """
        from src.ml import feature_groups as fg

        for spalte in fg.columns_for(fg.CL_PRIMARY_CANDIDATE):
            fehlend = [z for z in cl_zeilen if z.get(spalte) is None]
            assert not fehlend, f"{spalte} fehlt in {len(fehlend)} Zeilen"


# ---------------------------------------------------------------------------
# 7. Nur getrackte Quellen
# ---------------------------------------------------------------------------

class TestNurGetrackteQuellen:

    def test_es_wird_nur_aus_data_historical_gelesen(self, monkeypatch):
        import builtins

        original = builtins.open
        gelesen = []

        def beobachtet(pfad, *args, **kwargs):
            text = str(pfad).replace("\\", "/")
            if "/data/" in text or text.startswith("data/"):
                gelesen.append(text)
            return original(pfad, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", beobachtet)
        cl.build_cl_dataset([TEST_SAISON])

        fremd = [p for p in gelesen if "/data/historical/" not in p]
        assert not fremd, f"Zugriff ausserhalb data/historical: {fremd[:5]}"
        assert gelesen, "gar kein Lesezugriff - der Test waere wertlos"
