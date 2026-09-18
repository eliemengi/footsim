"""
Evaluation gegen Laufzeit: der Paritaetsnachweis (V2-C18).

WARUM ES DIESEN TEST GEBEN MUSS
-------------------------------
Die C16-Evaluation und die Laufzeit bestimmten die Herkunftsliga einer
Mannschaft auf ZWEI verschiedenen Wegen:

    Evaluation  c15_league_strength.apply_factors
                -> ligakarte[zeile["home_id"]]        football-data

    Laufzeit    inference._ligastaerke_anwenden
                -> bundle["team_leagues"][profil["team_id"]]

Solange profil["team_id"] im Namensraum des Providers stand, waren das
verschiedene Zahlen - und niemand hat es gemerkt, weil kein Test je
beide Wege gegen dasselbe Spiel laufen liess. Genau das tut diese
Datei.

WAS HIER NICHT GEMACHT WIRD
---------------------------
Kein Vergleich zweier Hilfsfunktionen auf bereits gleich praeparierten
Profilen - das wuerde die Frage umgehen statt sie zu beantworten. Die
Laufzeitseite laeuft durch inference.shadow_lambdas, also durch den
Merkmalsbau, den Modellaufruf, die zweite Stufe und die Begrenzung.

JE FOLD SEIN EIGENES MODELL
---------------------------
Verglichen wird fold-weise mit einem Bundle, das NUR auf den
Trainingssaisons dieses Folds gebaut ist. Das finale Produktionsbundle
hat spaetere Saisons gesehen; es rueckwirkend gegen fruehere
Foldvorhersagen zu halten waere ein Leck und kein Nachweis. Das zeigt
sich auch in den Parametern: Fold cl_2025 traegt gamma 0.75, das
Produktionsbundle 1.00.

DIE VERBLEIBENDE DIFFERENZ, DIE DIESER TEST NICHT WEGREDET
-----------------------------------------------------------
Die Evaluation schlaegt die Liga in der VOLLSTAENDIGEN Karte aller
nationalen Ligadateien nach. Das Bundle traegt nur die Vereine, die in
den Trainings-CL-Partien vorkamen. Wo ein Verein der Karte des Bundles
fehlt, kann die Laufzeit nicht korrigieren - unabhaengig von jedem
Codefehler. Dieser Test rechnet diese Faelle NICHT weg: Er trennt sie,
zaehlt sie und verlangt fuer sie die ausdrueckliche Diagnose
team_not_in_map. Die Schliessung dieser Luecke braucht ein neues
Bundle und gehoert damit nicht in diesen Block.
"""

import json
import os
import pathlib
import tempfile

import pytest

from src.features import league_strength as ls
from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev
from src.ml import feature_groups as fg
from src.ml import inference as inf
from src.ml import persist as ps

WURZEL = pathlib.Path(__file__).resolve().parents[1]
ARTEFAKT = WURZEL / "data" / "ml" / "c16_damped_league_strength_evaluation.json"

#: Vor dem Vergleich festgelegt, nicht danach angepasst. Beide Seiten
#: rechnen dieselbe Formel auf denselben Gleitkommazahlen; eine echte
#: Uebereinstimmung ist hier bitgleich. Die Schranke laesst nur die
#: Umordnung einzelner Multiplikationen zu.
TOLERANZ = 1e-9

#: Die Standardpopulation der C16-Messung.
ERWARTETE_ZEILEN = 283


def _artefakt():
    if not ARTEFAKT.is_file():
        pytest.skip("C16-Evaluationsartefakt liegt nicht vor")
    with open(ARTEFAKT, encoding="utf-8") as datei:
        return json.load(datei)


@pytest.fixture(scope="module")
def bestand():
    """
    Datensatz, Ligakarte und Foldbeschreibung - einmal je Modul.

    Der Aufbau liest lokale Dateien und ist teuer; er darf nicht je
    Testfunktion neu laufen. Netz wird dabei nicht beruehrt.
    """
    from src.ml import c14_reevaluation as c14
    from src.ml import dataset as ds

    artefakt = _artefakt()
    zeilen, _diag = ds.build_dataset(include_cl=True)
    return {
        "zeilen": zeilen,
        "ligakarte": c14.team_league_map(),
        "folds": artefakt["measurement"]["standard"]["folds"],
        "artefakt": artefakt,
        "spalten": fg.columns_for(fg.C15_CANDIDATE),
        "profilfelder": ds.PROFILE_RATING_FELDER,
    }


@pytest.fixture(scope="module")
def vergleich(bestand):
    """
    Der eigentliche Lauf: je Fold ein eigenes Bundle, dann Zeile
    fuer Zeile Evaluation gegen Laufzeit.

    Ergebnis ist eine Liste von Befunden je Partie, damit die
    einzelnen Tests darauf nur noch pruefen und nicht neu rechnen.
    """
    from src.ml import c16_release as rel

    befunde = []
    folds = []
    for fold in bestand["folds"]:
        seasons = tuple(fold["train_seasons"])
        test = ce.cl_rows(bestand["zeilen"], fold["test_season"])
        bundle, _d = rel.build_final_bundle(
            bestand["zeilen"], bestand["ligakarte"], bestand["artefakt"],
            seasons=seasons)
        block = bundle["league_strength"]
        staerke = ls.LeagueStrength(block["attack"], block["defence"],
                                    gamma=block["gamma"])

        with tempfile.TemporaryDirectory() as tmp:
            pfad = os.path.join(tmp, bundle["model_id"] + ".json")
            with open(pfad, "w", encoding="utf-8") as datei:
                json.dump(bundle, datei, ensure_ascii=False)

            # Volle Ladevalidierung. Ein Testbundle, das hier
            # durchfaellt, darf auch nicht verglichen werden.
            geladen, modelle = ps.load_bundle(pfad)

            basis, _stat = ev.predict_lambdas(
                geladen["alpha"], modelle, test, bestand["spalten"])
            eval_lambdas, _k = ls.apply_factors(
                staerke, test, basis, bestand["ligakarte"])

            inf.reset_model_cache()
            for zeile, (eval_h, eval_a) in zip(test, eval_lambdas):
                profil_heim = dict(
                    {feld: zeile["home_" + feld]
                     for feld in bestand["profilfelder"]},
                    team_id=zeile["home_id"])
                profil_gast = dict(
                    {feld: zeile["away_" + feld]
                     for feld in bestand["profilfelder"]},
                    team_id=zeile["away_id"])

                lauf = inf.shadow_lambdas(
                    zeile["baseline_lambda_home"],
                    zeile["baseline_lambda_away"],
                    home_profile=profil_heim, away_profile=profil_gast,
                    home_profile_source=zeile.get("home_profile_source"),
                    away_profile_source=zeile.get("away_profile_source"),
                    model_path=pfad)

                karte = block["team_leagues"]
                gedeckt = bool(karte.get(str(zeile["home_id"]))
                               and karte.get(str(zeile["away_id"])))
                befunde.append({
                    "fold": fold["fold"],
                    "match_id": zeile.get("match_id"),
                    "home_id": zeile["home_id"],
                    "away_id": zeile["away_id"],
                    "gedeckt": gedeckt,
                    "eval_home": eval_h, "eval_away": eval_a,
                    "lauf_home": lauf["shadow_lambda_home"],
                    "lauf_away": lauf["shadow_lambda_away"],
                    "stufe": lauf["league_stage"],
                    "status": lauf["status"],
                    "liga_eval_home": bestand["ligakarte"].get(
                        zeile["home_id"]),
                    "liga_eval_away": bestand["ligakarte"].get(
                        zeile["away_id"]),
                })
            inf.reset_model_cache()

        folds.append({
            "fold": fold["fold"],
            "train_seasons": list(seasons),
            "test_season": fold["test_season"],
            "gamma": block["gamma"],
            "alpha": bundle["alpha"],
            "model_id": bundle["model_id"],
            "teams_in_map": len(block["team_leagues"]),
            "test_rows": len(test),
            "erwartet": fold["test_rows"],
        })
    return {"befunde": befunde, "folds": folds}


# ===========================================================================
# 1  Der Messaufbau selbst
# ===========================================================================

def test_die_messung_deckt_die_standardpopulation_vollstaendig(vergleich):
    assert len(vergleich["befunde"]) == ERWARTETE_ZEILEN
    for fold in vergleich["folds"]:
        assert fold["test_rows"] == fold["erwartet"], fold


def test_jeder_fold_benutzt_sein_eigenes_zeitlich_korrektes_modell(vergleich):
    """
    Kein Rueckgriff auf das Produktionsbundle.

    Der Beleg ist nicht nur die Bauanweisung, sondern der Parameter
    selbst: Ein Fold traegt eine ANDERE Daempfung als das finale
    Bundle. Waere hier versehentlich das Produktionsmodell benutzt
    worden, stuenden beide auf 1.00.
    """
    produktion = json.loads(
        (WURZEL / "data" / "ml" / "models"
         / "clm-3475c9aacef6fec9-lsa165be9c.json").read_text(
            encoding="utf-8"))
    for fold in vergleich["folds"]:
        assert fold["model_id"] != produktion["model_id"]
        assert max(fold["train_seasons"]) < fold["test_season"]

    gammas = {f["fold"]: f["gamma"] for f in vergleich["folds"]}
    assert any(g != produktion["league_strength"]["gamma"]
               for g in gammas.values()), gammas


def test_jede_zeile_hat_eine_gueltige_laufzeitvorhersage(vergleich):
    for b in vergleich["befunde"]:
        assert b["status"] == "shadow_prediction", b


# ===========================================================================
# 2  Der Nachweis
# ===========================================================================

def test_lambdas_sind_identisch_wo_das_bundle_beide_vereine_kennt(vergleich):
    """
    DER KERN.

    Wo beide Seiten dieselbe Frage beantworten koennen, muessen sie
    dieselbe Antwort geben - nicht ungefaehr, sondern innerhalb einer
    vorher festgelegten, sehr engen Schranke.
    """
    gedeckt = [b for b in vergleich["befunde"] if b["gedeckt"]]
    assert gedeckt, "kein einziger vergleichbarer Fall - Test waere blind"
    # Seit V2-C19 traegt das Bundle dieselbe Karte wie die Messung.
    # Damit ist JEDE Partie vergleichbar, nicht nur ein Drittel.
    assert len(gedeckt) == len(vergleich["befunde"])

    schlimmste = 0.0
    fehler = []
    for b in gedeckt:
        d = max(abs(b["lauf_home"] - b["eval_home"]),
                abs(b["lauf_away"] - b["eval_away"]))
        schlimmste = max(schlimmste, d)
        if d > TOLERANZ:
            fehler.append((b["fold"], b["match_id"], d))

    assert not fehler, (
        "%d von %d gedeckten Partien weichen ab (groesste %.3e): %s"
        % (len(fehler), len(gedeckt), schlimmste, fehler[:5]))
    assert schlimmste <= TOLERANZ


def test_die_zweite_stufe_hat_dort_auch_wirklich_gegriffen(vergleich):
    """
    Gleichheit allein genuegt nicht: Sie waere auch dann gegeben,
    wenn BEIDE Seiten gar nichts angewandt haetten. Deshalb wird
    zusaetzlich verlangt, dass die Stufe gelaufen ist.
    """
    gedeckt = [b for b in vergleich["befunde"] if b["gedeckt"]]
    for b in gedeckt:
        # Seit V2-C19 gibt es zwei Zustaende, in denen die Stufe
        # gelaufen ist: mit vollstaendigen Ligawerten (applied) und
        # mit einer Liga, fuer die das Modell nichts gelernt hat
        # (league_without_parameters, Beitrag 0). Beide sind eine
        # angewandte Korrektur und rechnen genau wie
        # league_strength.apply_factors.
        assert b["stufe"]["status"] in (
            inf.STAGE2_APPLIED, inf.STAGE2_LEAGUE_WITHOUT_PARAMS), b
        assert b["stufe"]["applied"] is True, b


def test_die_aufgeloeste_liga_stimmt_auf_beiden_wegen_ueberein(vergleich):
    """
    Die Identitaetsfrage direkt: Beide Wege muessen fuer dieselbe
    Mannschaft dieselbe Liga nennen. Genau das war vorher nicht so.
    """
    gedeckt = [b for b in vergleich["befunde"] if b["gedeckt"]]
    for b in gedeckt:
        assert b["stufe"]["home_league"] == b["liga_eval_home"], b
        assert b["stufe"]["away_league"] == b["liga_eval_away"], b


# ===========================================================================
# 3  Die verbleibende Differenz - benannt, nicht weggerechnet
# ===========================================================================

def test_die_luecke_hat_genau_einen_grund_und_der_ist_ausgewiesen(vergleich):
    """
    Jede nicht vergleichbare Partie muss ihren Grund selbst nennen.

    Eine stille Abweichung waere genau der Zustand, gegen den dieser
    Block gebaut wurde.
    """
    luecke = [b for b in vergleich["befunde"] if not b["gedeckt"]]
    for b in luecke:
        assert b["stufe"]["status"] == inf.STAGE2_TEAM_NOT_IN_MAP, b
        assert b["stufe"]["applied"] is False, b


def test_die_luecke_ist_seit_c19_geschlossen(vergleich):
    """
    Frueher stand hier das Gegenteil.

    C18 hielt fest, dass die Luecke NICHT vom Laufzeitpfad stammt,
    sondern von der gekuerzten Bundlekarte: 191 der 283 Partien waren
    unvergleichbar, weil das Bundle nur die 63 Vereine der
    CL-Trainingshistorie trug. Seit C19 baut das Bundle seine Karte
    ueber denselben Vertrag wie die Messung, und die Luecke ist weg.

    Der Test bleibt als Waechter stehen: Wer die Karte wieder kuerzt,
    bricht ihn.
    """
    luecke = [b for b in vergleich["befunde"] if not b["gedeckt"]]
    assert luecke == [], (
        "%d Partien sind wieder unvergleichbar - die Bundlekarte "
        "wurde gekuerzt: %s" % (len(luecke), luecke[:3]))


def test_kein_netzzugriff_und_keine_env_datei_noetig(bestand):
    """
    Der Nachweis laeuft ausschliesslich auf lokalen Dateien.

    Geprueft ueber die Betriebsart: Sie kommt aus der Prozessumgebung
    und nicht aus einer Datei, und der Standard ist aus.
    """
    from src.ml import runtime as rt

    umgebung = {}
    assert rt.current_config(umgebung)["mode"] == rt.MODE_OFF
    assert bestand["zeilen"], "ohne lokalen Datensatz waere der Test leer"
