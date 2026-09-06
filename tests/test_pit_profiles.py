"""
Die einheitliche Point-in-Time-Profilfabrik (V2-C1).

WAS HIER BEWIESEN WIRD
----------------------
Vor V2-C1 gab es zwei Wege, dieselbe Frage zu beantworten: Der
Trainingsdatensatz baute Profile stichtagsgenau, die Laufzeit blendete
schlicht alle lokal vorliegenden Saisons. Ein Profil fuer die Saison
2024 war zur Laufzeit deshalb identisch mit dem fuer 2025.

Die zentrale Zusicherung dieser Datei ist die Paritaet: Fuer eine echte
Zeile des C1-Datensatzes muss der laufzeitnahe Pfad exakt dasselbe
Teamprofil liefern wie der Datensatzpfad. Nicht ungefaehr - gleich.

KEIN NETZ, KEIN PRIVATER CACHE
------------------------------
Alle Tests hier lesen entweder die im Repository versionierte Historie
unter data/historical/ oder ihre eigenen synthetischen Daten. Kein Test
braucht data/cache/, eine .env oder einen Anbieterschluessel - genau die
Abhaengigkeit, die zuletzt erst auf einem frischen CI-Runner aufgefallen
ist.
"""

import os

import pytest

from src.features import pit_profiles as pp

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Die Saison, an der die Paritaet nachgewiesen wird. Ihre Historie
#: liegt unter data/historical/ und ist versioniert - der Nachweis
#: laeuft damit auch auf einem frischen Runner ohne private Artefakte.
PARITAETS_SAISON = 2025

#: Die Merkmalsfelder eines Profils, die ins Modell gehen. Anzeigefelder
#: (team_name, crest) stehen bewusst nicht drin - sie sind Darstellung.
WERTFELDER = ("attack_home", "attack_away", "defence_home", "defence_away",
              "goals_for_per_game", "goals_against_per_game",
              "points_per_game", "win_rate", "matches_used")


# ---------------------------------------------------------------------------
# Synthetische Bausteine - unabhaengig von jeder echten Datei
# ---------------------------------------------------------------------------

def _spiel(datum, heim, gast, ht, at, uhrzeit=None):
    spiel = {"date": datum, "home_id": heim, "away_id": gast,
             "home_goals": ht, "away_goals": at, "matchday": 1,
             "stage": "LEAGUE_STAGE"}
    if uhrzeit:
        spiel["utc_date"] = f"{datum}T{uhrzeit}Z"
    return spiel


def _payload(matches, teams=None):
    return {"meta": {}, "matches": matches,
            "teams": teams or {1: {"id": 1, "name": "Eins"},
                               2: {"id": 2, "name": "Zwei"}}}


class _StubRepository(pp.PitProfileRepository):
    """
    Eine Fabrik mit vorgegebenen Rohdaten.

    Sie erbt die ECHTE Rechenlogik und ersetzt nur das Laden. Ein
    nachgebauter Zwilling wuerde genau das nicht pruefen, worum es geht.
    """

    def __init__(self, domestic=None, cl=None, **kwargs):
        super().__init__(**kwargs)
        self._stub_domestic = domestic or {}
        self._stub_cl = cl or {}

    def domestic_payload(self, api_code, season):
        return self._stub_domestic.get((api_code, season))

    def cl_payload(self, season):
        return self._stub_cl.get(season)


# ---------------------------------------------------------------------------
# 1. Der Stichtag ist Pflicht
# ---------------------------------------------------------------------------

class TestStichtagIstPflicht:

    def test_ohne_stichtag_gibt_es_kein_profil(self):
        repo = _StubRepository()
        with pytest.raises(pp.MissingCutoff):
            repo.domestic_profiles(2025, None)

    def test_auch_die_cl_historie_verlangt_ihn(self):
        repo = _StubRepository()
        with pytest.raises(pp.MissingCutoff):
            repo.cl_history(2025, None)

    def test_der_einstieg_verlangt_ihn(self):
        with pytest.raises(pp.MissingCutoff):
            pp.cl_profile_sources(2025, None, repository=_StubRepository())

    @pytest.mark.parametrize("unbrauchbar", ["", "2025", "x", 5])
    def test_unbrauchbare_stichtage_werden_abgewiesen(self, unbrauchbar):
        with pytest.raises(pp.MissingCutoff):
            pp.require_cutoff(unbrauchbar)

    @pytest.mark.parametrize("mit_zone", [
        "2025-10-01T20:00:00Z",
        "2025-10-01T20:00:00+02:00",
        "2025-10-01T20:00:00-03:00",
    ])
    def test_zeitzonen_werden_nicht_still_vermischt(self, mit_zone):
        """
        Die lokale Historie traegt naive Zeitstempel. Ein Vergleich
        gegen einen zonenbehafteten Stichtag waere stillschweigend
        falsch - deshalb Abbruch statt Abschneiden.
        """
        with pytest.raises(pp.MissingCutoff):
            pp.require_cutoff(mit_zone)

    def test_datum_und_datetime_sind_erlaubt(self):
        from datetime import date, datetime

        assert pp.require_cutoff(date(2025, 10, 1)) == "2025-10-01"
        assert pp.require_cutoff(datetime(2025, 10, 1, 20, 0)) \
            == "2025-10-01T20:00:00"
        assert pp.require_cutoff("2025-10-01") == "2025-10-01"

    def test_der_laufzeitstichtag_kommt_vom_rand(self):
        """
        runtime_cutoff ist die EINE Stelle, an der "jetzt" entsteht -
        und sie ist steuerbar. Ein datetime.now() tief in der Rechnung
        waere in Tests nicht fassbar.
        """
        from datetime import datetime

        fest = datetime(2026, 3, 1, 12, 0)
        assert pp.runtime_cutoff(fest) == "2026-03-01T12:00:00"

    def test_ohne_argument_ist_er_der_heutige_mittag(self):
        from datetime import date

        heute = pp.runtime_cutoff()
        assert heute.startswith(date.today().isoformat())
        assert heute.endswith("T12:00:00"), (
            "eine laufende Uhrzeit machte dieselbe Simulation "
            "unreproduzierbar")


# ---------------------------------------------------------------------------
# 2. Die Grenze am Stichtag
# ---------------------------------------------------------------------------

class TestStichtagsgrenze:

    def _repo(self):
        return _StubRepository(cl={2025: _payload([
            _spiel("2025-09-10", 1, 2, 2, 0),
            _spiel("2025-10-01", 2, 1, 1, 1),
            _spiel("2025-11-05", 1, 2, 3, 1),
        ])})

    def test_ein_spiel_vor_dem_stichtag_zaehlt(self):
        _, _, bekannt = self._repo().cl_history(2025, "2025-09-20")
        assert len(bekannt) == 1

    def test_ein_spiel_nach_dem_stichtag_zaehlt_nicht(self):
        _, _, bekannt = self._repo().cl_history(2025, "2025-10-15")
        assert len(bekannt) == 2
        assert all(m["date"] <= "2025-10-15" for m in bekannt)

    def test_am_stichtag_selbst_gilt_es_als_unbekannt(self):
        """
        Die leak-sichere Regel: Ohne Uhrzeiten auf beiden Seiten zaehlt
        ein Spiel am Stichtag NICHT mit. Sonst traege ein zu
        prognostizierendes Spiel zu seiner eigenen Vorhersage bei.
        """
        _, _, bekannt = self._repo().cl_history(2025, "2025-10-01")
        assert len(bekannt) == 1
        assert pp.CUTOFF_INCLUSIVE is False

    def test_mit_uhrzeiten_entscheidet_die_uhrzeit(self):
        repo = _StubRepository(cl={2025: _payload([
            _spiel("2025-10-01", 1, 2, 2, 0, uhrzeit="18:45:00"),
            _spiel("2025-10-01", 2, 1, 1, 1, uhrzeit="21:00:00"),
        ])})
        _, _, bekannt = repo.cl_history(2025, "2025-10-01T20:00:00")
        assert len(bekannt) == 1
        assert bekannt[0]["home_id"] == 1

    def test_ohne_spiele_vor_dem_stichtag_bleibt_alles_leer(self):
        profile, avg, bekannt = self._repo().cl_history(2025, "2025-01-01")
        assert profile == {}
        assert bekannt == []
        assert (avg or {}).get("matches") in (0, None)


# ---------------------------------------------------------------------------
# 3. Kein Zukunftsleck
# ---------------------------------------------------------------------------

class TestKeinZukunftsleck:

    def test_spaetere_partien_aendern_ein_historisches_profil_nicht(self):
        """
        Der Kern von V2-C1. Vorher enthielt der Laufzeitpfad ALLE lokal
        vorliegenden Saisons, unabhaengig vom simulierten Zeitpunkt -
        ein Profil fuer 2024 war identisch mit dem fuer 2025.
        """
        frueh = [_spiel("2025-09-10", 1, 2, 2, 0)]
        spaet = frueh + [_spiel("2025-11-05", 1, 2, 5, 0),
                         _spiel("2025-12-01", 1, 2, 4, 0)]

        ohne = _StubRepository(cl={2025: _payload(frueh)})
        mit = _StubRepository(cl={2025: _payload(spaet)})

        a, _, _ = ohne.cl_history(2025, "2025-10-01")
        b, _, _ = mit.cl_history(2025, "2025-10-01")

        assert a == b, ("Partien nach dem Stichtag haben das historische "
                        "Profil veraendert")

    def test_eine_spaetere_saison_dringt_nicht_ein(self):
        """
        Die zweite zeitliche Grenze. Der Stichtag allein reicht nicht:
        Ohne Saisonobergrenze kaeme die komplette Folgesaison mit.
        """
        repo = _StubRepository(domestic={
            ("BL1", 2024): _payload([_spiel("2024-09-01", 1, 2, 1, 0)]),
            ("BL1", 2025): _payload([_spiel("2025-09-01", 1, 2, 9, 0)]),
        })
        profile_2024 = repo.domestic_profiles(2024, "2026-01-01")
        profile_2025 = repo.domestic_profiles(2025, "2026-01-01")

        assert profile_2024 != profile_2025, (
            "die Saisonobergrenze wirkt nicht - genau der alte Fehler")
        assert profile_2024[1]["matches_used"] == 1

    def test_die_livequelle_wird_ebenso_gefiltert(self):
        """
        Die Anbieterantwort war der letzte Weg, auf dem Zukunftsdaten
        haetten hereinkommen koennen.
        """
        repo = _StubRepository(cl={2025: _payload([])})
        _, _, bekannt = repo.cl_history(
            2025, "2025-10-01",
            extra_matches=[_spiel("2025-09-01", 1, 2, 1, 0),
                           _spiel("2025-12-01", 1, 2, 7, 0)])
        assert len(bekannt) == 1
        assert bekannt[0]["date"] == "2025-09-01"


# ---------------------------------------------------------------------------
# 4. Cache: Stichtag im Schluessel, Reihenfolge ohne Wirkung
# ---------------------------------------------------------------------------

class TestCache:

    def _repo(self):
        return _StubRepository(cl={2025: _payload([
            _spiel("2025-09-10", 1, 2, 2, 0),
            _spiel("2025-11-05", 1, 2, 3, 1),
        ])}, domestic={
            ("BL1", 2025): _payload([_spiel("2025-08-01", 1, 2, 1, 0),
                                     _spiel("2025-12-01", 2, 1, 4, 0)]),
        })

    def test_verschiedene_stichtage_ergeben_getrennte_eintraege(self):
        repo = self._repo()
        frueh, _, _ = repo.cl_history(2025, "2025-10-01")
        spaet, _, _ = repo.cl_history(2025, "2025-12-01")
        assert frueh != spaet
        assert len(repo._cl) == 2

    def test_derselbe_stichtag_ist_deterministisch(self):
        repo = self._repo()
        erst, _, _ = repo.cl_history(2025, "2025-10-01")
        zweit, _, _ = repo.cl_history(2025, "2025-10-01")
        assert erst == zweit

    def test_ein_spaeter_aufruf_verdirbt_den_frueheren_nicht(self):
        """
        Erst spaet, dann frueh - und danach umgekehrt. Ein auf die
        Saison allein verschluesselter Speicher haette hier das
        Profil zum 01.03. fuer den 01.10. ausgeliefert.
        """
        repo = self._repo()
        spaet_zuerst, _, _ = repo.cl_history(2025, "2025-12-01")
        frueh_danach, _, _ = repo.cl_history(2025, "2025-10-01")

        repo2 = self._repo()
        frueh_zuerst, _, _ = repo2.cl_history(2025, "2025-10-01")
        spaet_danach, _, _ = repo2.cl_history(2025, "2025-12-01")

        assert frueh_danach == frueh_zuerst
        assert spaet_zuerst == spaet_danach

    def test_das_gilt_auch_fuer_die_nationalen_profile(self):
        repo = self._repo()
        spaet = repo.domestic_profiles(2025, "2026-01-01")
        frueh = repo.domestic_profiles(2025, "2025-09-01")
        assert frueh[1]["matches_used"] == 1
        assert spaet[1]["matches_used"] == 2

    def test_zusatzpartien_verderben_den_speicher_nicht(self):
        """
        Live geholte Partien sind je Aufruf verschieden. Wuerden sie
        unter demselben Schluessel abgelegt, bekaeme der naechste
        Aufruf ohne sie ein falsches Ergebnis.
        """
        repo = self._repo()
        _, _, mit = repo.cl_history(2025, "2025-10-01",
                                    extra_matches=[_spiel("2025-09-20", 2, 1, 5, 0)])
        _, _, ohne = repo.cl_history(2025, "2025-10-01")
        assert len(mit) == 2
        assert len(ohne) == 1


# ---------------------------------------------------------------------------
# 5. Fehlende und defekte Daten
# ---------------------------------------------------------------------------

class TestFehlendeDaten:

    def test_ohne_jede_quelle_bleibt_es_leer_statt_zu_brechen(self):
        quellen = pp.cl_profile_sources(2025, "2025-10-01",
                                        repository=_StubRepository())
        assert quellen["domestic_by_id"] == {}
        assert quellen["cl_history_by_id"] == {}
        assert quellen["league_avg"] is None

    def test_eine_leere_saisondatei_wird_uebersprungen(self):
        repo = _StubRepository(domestic={("BL1", 2025): None,
                                         ("BL1", 2024): _payload(
                                             [_spiel("2024-09-01", 1, 2, 1, 0)])})
        profile = repo.domestic_profiles(2025, "2026-01-01")
        assert profile[1]["matches_used"] == 1

    def test_partien_ohne_ergebnis_zaehlen_nicht(self):
        repo = _StubRepository(cl={2025: _payload([
            {"date": "2025-09-01", "home_id": 1, "away_id": 2,
             "home_goals": None, "away_goals": None},
            _spiel("2025-09-10", 1, 2, 2, 0),
        ])})
        _, _, bekannt = repo.cl_history(2025, "2025-10-01")
        assert len(bekannt) == 1

    def test_partien_ohne_datum_gelten_als_unbekannt(self):
        repo = _StubRepository(cl={2025: _payload([
            {"home_id": 1, "away_id": 2, "home_goals": 2, "away_goals": 0},
        ])})
        _, _, bekannt = repo.cl_history(2025, "2025-10-01")
        assert bekannt == []

    def test_unbrauchbare_teamkennungen_brechen_nicht_ab(self):
        repo = _StubRepository(cl={2025: _payload(
            [_spiel("2025-09-01", 1, 2, 1, 0)],
            teams={"kaputt": {"name": "X"}, 1: {"id": 1, "name": "Eins"}})})
        profile, _, _ = repo.cl_history(2025, "2025-10-01")
        assert 1 in profile

    def test_die_kaskade_faellt_sauber_auf_neutral(self):
        profil, quelle, tiefe = pp.resolve_profile(999, "Unbekannt", {}, {})
        assert quelle == pp.SOURCE_NEUTRAL
        assert tiefe == 0
        assert profil["attack_home"] == 1.0

    def test_die_kaskade_bevorzugt_die_nationale_historie(self):
        domestic = {7: {"team_id": 7, "matches_used": 30}}
        cl = {7: {"team_id": 7, "matches_used": 90}}
        _, quelle, tiefe = pp.resolve_profile(7, "X", domestic, cl)
        assert quelle == pp.SOURCE_DOMESTIC
        assert tiefe == 30


# ---------------------------------------------------------------------------
# 6. Die zentrale Invariante: Training und Laufzeit sind identisch
# ---------------------------------------------------------------------------

class TestTrainingLaufzeitParitaet:
    """
    Der eigentliche Nachweis von V2-C1.

    Was der Datensatzbau als Merkmalswert in eine Zeile schreibt, muss
    der laufzeitnahe Pfad zum selben Stichtag exakt wieder herstellen.

    DIE ZEILEN ENTSTEHEN HIER, STATT AUS EINER PRIVATEN DATEI ZU KOMMEN
    data/ml/dataset_with_cl_2023-2025.json ist ein lokales
    Analyseartefakt und nicht versioniert. Haenge dieser Nachweis daran,
    wuerde er sich auf einem frischen CI-Runner ueberspringen - und
    genau die Kerninvariante von V2-C1 waere dort unbelegt. Gebaut wird
    deshalb aus data/historical/, das im Repository liegt.
    """

    @pytest.fixture(scope="class")
    def zeilen(self):
        from src.ml import cl_dataset as cd

        gebaut, _ = cd.build_cl_season(PARITAETS_SAISON)
        auswertbar = [z for z in (gebaut or []) if z.get("evaluation_eligible")]
        assert auswertbar, (
            f"keine auswertbaren CL-Zeilen fuer {PARITAETS_SAISON} - "
            f"fehlt data/historical/CL_{PARITAETS_SAISON}.json?")
        # Ueber die Saison streuen, nicht nur den Anfang nehmen.
        return auswertbar[::13][:12]

    def test_die_merkmalswerte_stimmen_exakt_ueberein(self, zeilen):
        from src.features import strength_provider as sp
        from src.ml import feature_groups as fg

        merkmale = set(fg.columns_for(fg.CL_PRIMARY_CANDIDATE))
        geprueft = 0

        for zeile in zeilen:
            strengths = sp.get_cl_team_strengths(season=zeile["season"],
                                                 cutoff=zeile["date"])
            for seite, tid in (("home", zeile["home_id"]),
                               ("away", zeile["away_id"])):
                profil, _, _ = pp.resolve_profile(
                    tid, None,
                    strengths["domestic_by_id"], strengths["cl_current_by_id"])
                for feld in WERTFELDER:
                    spalte = f"{seite}_{feld}"
                    if spalte not in merkmale:
                        continue
                    geprueft += 1
                    assert profil.get(feld) == zeile.get(spalte), (
                        f"{zeile['row_id']} {spalte}: Datensatz "
                        f"{zeile.get(spalte)!r} != Laufzeit "
                        f"{profil.get(feld)!r}")

        assert geprueft >= 100, f"zu wenige Werte geprueft: {geprueft}"

    def test_auch_die_profilherkunft_stimmt_ueberein(self, zeilen):
        """
        Nicht nur die Zahlen: Auch WOHER das Profil kam, muss gleich
        sein. Eine abweichende Stufe hiesse, dass die Kaskade im
        Betrieb anders greift als im Training.
        """
        from src.features import strength_provider as sp

        for zeile in zeilen:
            strengths = sp.get_cl_team_strengths(season=zeile["season"],
                                                 cutoff=zeile["date"])
            for seite, tid in (("home", zeile["home_id"]),
                               ("away", zeile["away_id"])):
                _, quelle, _ = pp.resolve_profile(
                    tid, None,
                    strengths["domestic_by_id"], strengths["cl_current_by_id"])
                assert quelle == zeile[f"{seite}_profile_source"], (
                    f"{zeile['row_id']} {seite}: Herkunft weicht ab")

    def test_ein_anderer_stichtag_ergibt_ein_anderes_profil(self, zeilen):
        """
        Die Gegenprobe. Waere der Stichtag wirkungslos - der alte
        Zustand -, lieferte jeder Zeitpunkt dasselbe, und der Test
        oben waere wertlos.
        """
        from src.features import strength_provider as sp

        zeile = zeilen[-1]
        echt = sp.get_cl_team_strengths(season=zeile["season"],
                                        cutoff=zeile["date"])
        frueh = sp.get_cl_team_strengths(season=zeile["season"],
                                         cutoff=f"{zeile['season']}-08-01")

        assert echt["provenance"]["cl_matches_known_at_cutoff"] \
            > frueh["provenance"]["cl_matches_known_at_cutoff"]

    def test_die_herkunft_nennt_den_verwendeten_stichtag(self, zeilen):
        from src.features import strength_provider as sp

        zeile = zeilen[0]
        prov = sp.get_cl_team_strengths(
            season=zeile["season"], cutoff=zeile["date"])["provenance"]

        assert prov["pit_cutoff"] == zeile["date"]
        assert prov["pit_season_ceiling"] == zeile["season"]
        assert prov["cutoff_inclusive"] is False
        # Die Herkunft darf nicht den Rohbestand der Datei melden,
        # sondern nur, was zum Stichtag benutzt wurde.
        assert prov["matches_through_date"] < zeile["date"]


# ---------------------------------------------------------------------------
# 7. Es gibt nur noch einen Pfad
# ---------------------------------------------------------------------------

class TestNurEinPfad:

    def test_der_alte_parallelpfad_ist_entfallen(self):
        from src.features import strength_provider as sp

        assert not hasattr(sp, "_blend_top5_league_history_by_id"), (
            "der zweite, stichtagslose Profilpfad existiert wieder")

    def test_der_datensatz_benutzt_die_fabrik(self):
        from src.ml import cl_dataset as cd

        assert cd._Quellen is pp.PitProfileRepository
        assert cd.resolve_profile is pp.resolve_profile

    def test_die_laufzeit_verlangt_einen_stichtag(self):
        import inspect

        from src.features import strength_provider as sp

        parameter = inspect.signature(sp.get_cl_team_strengths).parameters
        assert "cutoff" in parameter
        assert parameter["cutoff"].default is inspect.Parameter.empty, (
            "ein Standardwert waere ein stiller Stichtag")

    def test_die_simulation_nimmt_den_stichtag_in_den_cacheschluessel(self):
        import inspect

        from src.predict import cl_match_sim

        quelle = inspect.getsource(cl_match_sim.simulate_cl_league_phase_match)
        assert 'f"cl_strengths:{season}:{cutoff}"' in quelle
        # Der Stichtag entsteht am Rand: ausdruecklicher kickoff, sonst
        # der aufgeloeste Anstoss der Begegnung, sonst "jetzt".
        assert "runtime_cutoff(" in quelle
        assert "fixture_cutoff(season, home_id, away_id" in quelle
