"""
V2-C19: Bundleabdeckung und vollstaendige Laufzeitparitaet.

DER BEFUND, DEN DIESE DATEI FESTHAELT
-------------------------------------
C18 verglich Evaluation und Laufzeit auf den 283 Standardpartien und
konnte nur 92 davon vergleichen. Die uebrigen 191 scheiterten nicht an
der Rechnung, sondern an der KARTE: Die Messung schlug in allen 146
Vereinen der lokalen Ligadateien nach, das Bundle trug nur die 63, die
in den Trainings-CL-Partien vorkamen. Auf 188 dieser Partien wandte die
Evaluation einen Faktor an, den die Laufzeit gar nicht anwenden konnte.

Seit C19 bauen Messung und Bundle ihre Karte ueber dieselbe Funktion,
mit derselben zeitlichen Obergrenze. Diese Datei prueft, dass davon
nichts mehr abweicht - und zwar ueber den echten Produktionspfad, nicht
ueber vorbereitete Profile.
"""

import json
import os
import tempfile

import pytest

from src.ml import c19_league_map as c19

#: Vorab festgelegt, nicht nachtraeglich an das Ergebnis angepasst.
#: Beide Seiten rechnen dieselbe Formel auf denselben Gleitkommazahlen;
#: eine echte Uebereinstimmung ist hier bitgleich. Die Schranke laesst
#: nur die Umordnung einzelner Multiplikationen zu.
TOLERANZ = 1e-9

AKTIVES_BUNDLE = "data/ml/models/clm-3475c9aacef6fec9-lsa165be9c.json"


@pytest.fixture(scope="module")
def zeilen():
    from src.ml import dataset as ds
    daten, _diagnose = ds.build_dataset(include_cl=True)
    return daten


@pytest.fixture(scope="module")
def artefakt():
    with open("data/ml/c16_damped_league_strength_evaluation.json",
              encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def neues_bundle(zeilen, artefakt):
    from src.ml import c16_release as rel
    from src.ml import persist as ps
    karte, _d = c19.build_team_league_map(max(ps.DEFAULT_TRAINING_SEASONS))
    bundle, _diag = rel.build_final_bundle(zeilen, karte, artefakt)
    return bundle


# ---------------------------------------------------------------------------
# 1. Das Bundle traegt die ganze Karte
# ---------------------------------------------------------------------------

class TestBundleAbdeckung:

    def test_das_bundle_traegt_die_volle_karte(self, neues_bundle):
        from src.ml import persist as ps
        karte, _d = c19.build_team_league_map(
            max(ps.DEFAULT_TRAINING_SEASONS))
        assert (neues_bundle["league_strength"]["team_leagues"]
                == c19.bundle_map(karte))

    def test_die_karte_ist_groesser_als_vor_c19(self, neues_bundle):
        with open(AKTIVES_BUNDLE, encoding="utf-8") as datei:
            alt = json.load(datei)
        alte = alt["league_strength"]["team_leagues"]
        neue = neues_bundle["league_strength"]["team_leagues"]
        assert len(neue) > len(alte)
        # Nichts entfaellt und nichts wird umgehaengt: reine Ergaenzung.
        assert set(alte) <= set(neue)
        assert all(neue[tid] == liga for tid, liga in alte.items())

    def test_die_provenienz_steht_im_bundle(self, neues_bundle):
        spur = neues_bundle["league_strength"]["team_leagues_provenance"]
        assert spur["contract_fingerprint"] == c19.contract_fingerprint()
        assert spur["upto_season"] == 2025
        assert spur["teams"] == len(
            neues_bundle["league_strength"]["team_leagues"])

    def test_der_kartenfingerabdruck_stimmt(self, neues_bundle):
        from src.ml import persist as ps
        karte, _d = c19.build_team_league_map(
            max(ps.DEFAULT_TRAINING_SEASONS))
        spur = neues_bundle["league_strength"]["team_leagues_provenance"]
        assert spur["map_fingerprint"] == c19.map_fingerprint(
            karte, max(ps.DEFAULT_TRAINING_SEASONS))

    def test_das_bundle_besteht_die_ladevalidierung(self, neues_bundle):
        from src.ml import c17_bundle_contract as c17
        from src.ml import persist as ps
        with tempfile.TemporaryDirectory() as tmp:
            pfad = os.path.join(tmp, neues_bundle["model_id"] + ".json")
            with open(pfad, "w", encoding="utf-8") as datei:
                json.dump(neues_bundle, datei, ensure_ascii=False)
            geladen, modelle = ps.load_bundle(pfad)
        assert c17.validate_bundle(geladen) == []
        assert set(modelle) == {"home", "away"}

    def test_nur_die_zuordnung_hat_sich_geaendert(self, neues_bundle):
        """
        Der strukturelle Beweis, dass dies eine Metadatenreparatur ist
        und keine Modelleaenderung.

        GEAENDERT IN V2-C22: In der Referenzumgebung bitgleich wie
        bisher. In jeder anderen numerischen Umgebung gilt der
        eingefrorene Aequivalenzvertrag: Struktur exakt, ausschliesslich
        die ausdruecklich genannten Zahlenfelder innerhalb der Toleranz.
        Die Ligakarte bleibt der einzige Strukturunterschied.
        """
        from src.ml import c22_release_equivalence as c22

        with open(AKTIVES_BUNDLE, encoding="utf-8") as datei:
            alt = json.load(datei)
        bitgleich = c22.is_reference_environment()

        def pruefe(a, b, pfad):
            bericht = c22.classify_differences(a, b, praefix=pfad)
            if bitgleich:
                assert bericht["differing_fields"] == [], pfad
            else:
                assert bericht["structural_mismatches"] == [], pfad
                assert bericht["numerical_mismatches"] == [], pfad

        for feld in ("alpha", "features", "feature_count", "candidate",
                     "schema_version", "models", "training",
                     "contract_bindings"):
            pruefe(alt[feld], neues_bundle[feld], feld)

        for feld in ("gamma", "alpha", "attack", "defence",
                     "factor_bounds", "stage", "selection", "trained_on"):
            pruefe(alt["league_strength"][feld],
                   neues_bundle["league_strength"][feld],
                   "league_strength/%s" % feld)

        # Genau zwei Schluessel duerfen sich unterscheiden - in der
        # Referenzumgebung ueberhaupt, anderswo ausserhalb der Toleranz.
        def abweichend(schluessel):
            a = alt["league_strength"].get(schluessel)
            b = neues_bundle["league_strength"].get(schluessel)
            if bitgleich:
                return a != b
            bericht = c22.classify_differences(
                a, b, praefix="league_strength/%s" % schluessel)
            return bool(bericht["structural_mismatches"]
                        or bericht["numerical_mismatches"])

        geaendert = {schluessel
                     for schluessel in set(neues_bundle["league_strength"])
                     | set(alt["league_strength"])
                     if abweichend(schluessel)}
        assert geaendert == {"team_leagues", "team_leagues_provenance"}

    def test_das_basismodell_behaelt_seine_kennung(self, neues_bundle,
                                                   zeilen):
        """
        Die Modell-ID besteht aus Basismodell- und Ligastufenteil. Nur
        der zweite darf sich aendern; der erste ist der Beleg, dass das
        Basismodell dasselbe ist.

        GEAENDERT IN V2-C22: In der Referenzumgebung bleibt das der
        Beleg. Anderswo traegt dasselbe Basismodell andere letzte
        Stellen und damit einen anderen Basisteil; der Beleg ist dann der
        eingefrorene Aequivalenzvertrag: jede Definition der ersten Stufe
        exakt, ihre Zahlen und Lambdas in der Toleranz, und die neue
        Kennung ergibt sich aus dem eigenen Inhalt.
        """
        from src.ml import c22_release_equivalence as c22

        with open(AKTIVES_BUNDLE, encoding="utf-8") as datei:
            alt = json.load(datei)
        alt_basis, alt_stufe = alt["model_id"].rsplit("-", 1)
        neu_basis, neu_stufe = neues_bundle["model_id"].rsplit("-", 1)
        assert neu_stufe != alt_stufe
        if c22.is_reference_environment():
            assert neu_basis == alt_basis
            return

        assert c22.identity_findings(neues_bundle, "Neubau") == []
        for feld in ("candidate", "features", "alpha", "release_stage",
                     "models", "training"):
            bericht = c22.classify_differences(alt[feld], neues_bundle[feld],
                                               praefix=feld)
            assert bericht["structural_mismatches"] == [], feld
            assert bericht["numerical_mismatches"] == [], feld
        for teil in ("dataset_fingerprint", "evaluation"):
            assert (neues_bundle["provenance"][teil]
                    == alt["provenance"][teil]), teil
        vorhersage = c22.compare_predictions(
            alt, neues_bundle, c22.reference_population(zeilen),
            stufen=("base",))
        assert vorhersage["rows"] == 283
        assert vorhersage["within_tolerance"] is True, vorhersage


# ---------------------------------------------------------------------------
# 2. Zeitlich korrekte Foldkarten
# ---------------------------------------------------------------------------

class TestFoldZeitlichkeit:

    def test_jeder_fold_bekommt_seine_eigene_obergrenze(self, artefakt):
        folds = artefakt["measurement"]["standard"]["folds"]
        groessen = []
        for fold in folds:
            _karte, diagnose = c19.build_team_league_map(
                max(fold["train_seasons"]))
            assert diagnose["upto_season"] == max(fold["train_seasons"])
            assert all(s <= max(fold["train_seasons"])
                       for s in diagnose["seasons_used"])
            groessen.append(diagnose["teams"])
        # Der spaetere Fold darf mehr wissen, der fruehere nicht.
        assert groessen == sorted(groessen)
        assert groessen[0] < groessen[-1]

    def test_die_foldkarte_ist_kleiner_als_die_produktionskarte(self,
                                                               artefakt):
        from src.ml import persist as ps
        _k, produktion = c19.build_team_league_map(
            max(ps.DEFAULT_TRAINING_SEASONS))
        for fold in artefakt["measurement"]["standard"]["folds"]:
            if max(fold["train_seasons"]) >= max(ps.DEFAULT_TRAINING_SEASONS):
                continue
            _k2, diagnose = c19.build_team_league_map(
                max(fold["train_seasons"]))
            assert diagnose["teams"] < produktion["teams"]


# ---------------------------------------------------------------------------
# 3. Vollstaendige Paritaet ueber den echten Produktionspfad
# ---------------------------------------------------------------------------

class TestVollstaendigeParitaet:
    """
    Alle 283 Standardpartien, je Fold mit dessen eigenem Modell.

    Das finale Bundle hat spaetere Saisons gesehen und wird
    ausdruecklich NICHT rueckwirkend gegen fruehere Foldvorhersagen
    gehalten.
    """

    def test_alle_283_partien_stimmen_ueberein(self, zeilen, artefakt):
        from src.features import league_strength as ls
        from src.features.pit_profiles import PitProfileRepository
        from src.features.strength_provider import get_cl_team_strengths
        from src.ml import c16_release as rel
        from src.ml import cl_evaluate as ce
        from src.ml import dataset as ds
        from src.ml import evaluate as ev
        from src.ml import feature_groups as fg
        from src.ml import inference as inf
        from src.ml import persist as ps
        from src.predict.cl_match_sim import _resolve_cl_profile

        spalten = fg.columns_for(fg.C15_CANDIDATE)
        repository = PitProfileRepository()
        gesamt = angewandt = neutral = 0
        max_lambda = max_faktor = 0.0

        for fold in artefakt["measurement"]["standard"]["folds"]:
            saisons = tuple(fold["train_seasons"])
            karte, _d = c19.build_team_league_map(max(saisons))
            test = ce.cl_rows(zeilen, fold["test_season"])
            bundle, _diag = rel.build_final_bundle(zeilen, karte, artefakt,
                                                   seasons=saisons)
            block = bundle["league_strength"]
            staerke = ls.LeagueStrength(block["attack"], block["defence"],
                                        gamma=block["gamma"])

            with tempfile.TemporaryDirectory() as tmp:
                pfad = os.path.join(tmp, bundle["model_id"] + ".json")
                with open(pfad, "w", encoding="utf-8") as datei:
                    json.dump(bundle, datei, ensure_ascii=False)
                geladen, modelle = ps.load_bundle(pfad)
                basis, _s = ev.predict_lambdas(geladen["alpha"], modelle,
                                               test, spalten)
                erwartet, _k = ls.apply_factors(staerke, test, basis, karte)
                inf.reset_model_cache()

                for zeile, (soll_h, soll_a) in zip(test, erwartet):
                    gesamt += 1
                    stichtag = ds.prediction_cutoff(zeile["date"])
                    quellen = get_cl_team_strengths(
                        season=zeile["season"], cutoff=stichtag,
                        repository=repository)
                    heim, _rh = _resolve_cl_profile(
                        quellen, zeile["home_id"], None)
                    gast, _ra = _resolve_cl_profile(
                        quellen, zeile["away_id"], None)

                    # Der Produktionspfad loest die Identitaet selbst auf.
                    assert heim["team_id"] == zeile["home_id"]
                    assert gast["team_id"] == zeile["away_id"]

                    ergebnis = inf.shadow_lambdas(
                        zeile["baseline_lambda_home"],
                        zeile["baseline_lambda_away"],
                        home_profile=heim, away_profile=gast,
                        model_path=pfad)
                    stufe = ergebnis["league_stage"]

                    liga_h = karte.get(zeile["home_id"])
                    liga_a = karte.get(zeile["away_id"])
                    assert stufe["home_league"] == liga_h
                    assert stufe["away_league"] == liga_a
                    # Beide Wege sind sich einig, OB korrigiert wird.
                    assert bool(stufe["applied"]) == bool(liga_h and liga_a)

                    if stufe["applied"]:
                        angewandt += 1
                        f_h, f_a = staerke.factors(liga_h, liga_a)
                        max_faktor = max(
                            max_faktor,
                            abs(stufe["league_factor_home"] - f_h),
                            abs(stufe["league_factor_away"] - f_a))
                    else:
                        neutral += 1
                        assert stufe["status"] == c19.UNKNOWN_TEAM

                    max_lambda = max(
                        max_lambda,
                        abs(ergebnis["shadow_lambda_home"] - soll_h),
                        abs(ergebnis["shadow_lambda_away"] - soll_a))

        # Keine Partie wurde als "nicht vergleichbar" entfernt.
        assert gesamt == 283
        assert angewandt + neutral == gesamt
        assert angewandt > 0 and neutral > 0
        assert max_lambda <= TOLERANZ, max_lambda
        assert max_faktor <= TOLERANZ, max_faktor


# ---------------------------------------------------------------------------
# 4. Die Laufzeit benutzt die eingefrorene Karte
# ---------------------------------------------------------------------------

class TestLaufzeitBenutztBundleKarte:

    def test_die_laufzeit_liest_keine_ligadatei_nach(self, monkeypatch):
        """
        Die Karte kommt aus dem Bundle. Wuerde die Laufzeit sie zur
        Simulationszeit neu bauen, rechneten zwei Bundles je nach
        Plattenstand verschieden.
        """
        from src.ml import inference as inf

        aufrufe = []
        monkeypatch.setattr(c19, "build_team_league_map",
                            lambda *a, **kw: aufrufe.append(1) or ({}, {}))

        with open(AKTIVES_BUNDLE, encoding="utf-8") as datei:
            bundle = json.load(datei)
        profil = {"team_id": 5}
        inf._ligastaerke_anwenden(bundle["league_strength"], profil,
                                  {"team_id": 930}, 1.0, 1.0)
        assert aufrufe == []

    def test_ein_verein_ausserhalb_der_karte_bleibt_neutral(self):
        from src.ml import inference as inf

        with open(AKTIVES_BUNDLE, encoding="utf-8") as datei:
            bundle = json.load(datei)
        f_h, f_a, diagnose = inf._ligastaerke_anwenden(
            bundle["league_strength"], {"team_id": 5},
            {"team_id": 999999}, 1.0, 1.0)
        assert (f_h, f_a) == (1.0, 1.0)
        assert diagnose["applied"] is False
        assert diagnose["status"] == c19.UNKNOWN_TEAM
