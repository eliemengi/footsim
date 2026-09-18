"""
Der zeitliche Zuordnungsvertrag, korrigiert (V2-C20).

WAS AN C19 FALSCH WAR
---------------------
C19 hat die Team-Liga-Karte eines Folds auf die LETZTE TRAININGSSAISON
begrenzt. Die Begruendung war richtig gemeint: Ein Fold darf nichts
wissen, was nach seinem Testzeitpunkt liegt. Umgesetzt wurde aber eine
strengere Regel, als die Begruendung verlangt - und diese Strenge hat
etwas anderes gemessen als den Informationsstand vor Anstoss.

Nachgemessen auf den 283 Standardpartien:

  - Die Ligaparameter (Attack, Defence, Alpha, Gamma) sind unter der
    unbegrenzten Karte, der C19-Karte und der hier eingefuehrten Karte
    BITGLEICH. Die Begrenzung aendert nichts an der Schaetzung.
  - Der gesamte Messunterschied zwischen unbegrenzter und C19-Karte
    stammt aus genau 52 Partien, und zwar jedes Mal, weil ein Verein
    unter C19 unbekannt war.
  - In jedem dieser 52 Faelle liegt die Liga des Vereins lokal nur fuer
    die TESTsaison vor, nicht fuer die Trainingssaisons: CZ1, HR1, SK1
    im Fold 2024, AZ1, CY1, GR1, KZ1, NO1 im Fold 2025. Fuenfzehn der
    23 nationalen Ligen haben lueckenhafte lokale Dateien.

C19 hat also eine fehlende LOKALE DATEI mit einer unbekannten
LIGAZUGEHOERIGKEIT verwechselt. Slovan Bratislava spielte 2023 in der
slowakischen Liga; die lokale Datei dafuer gibt es nur nicht.

WAS VOR ANSTOSS BEKANNT IST, UND WAS NICHT
------------------------------------------
Drei Arten von Information, streng getrennt:

  1. Spielergebnisse nach dem Stichtag - nie zulaessig. Die Karte liest
     sie auch nicht: Sie entnimmt einer Saisondatei ausschliesslich die
     teilnehmenden Vereine, keine Tore, keinen Ausgang.
  2. Ligamitgliedschaft einer SPAETEREN Saison - nicht zulaessig. Die
     unbegrenzte Karte hat fuer den Fold 2024 Dateien von 2025 gelesen.
     Nachgemessen war das wirkungslos (keiner der erst 2025 bekannten
     Vereine kommt in einer Testpartie von 2024 vor), zulaessig war es
     trotzdem nicht.
  3. Ligamitgliedschaft der VORHERSAGESAISON selbst - zulaessig. Sie
     steht mit dem veroeffentlichten Spielplan vor Saisonbeginn fest,
     also vor jeder Ligaphasenpartie derselben Saison. Das ist
     Metadatum, kein Ergebnis.

Daraus folgt eine einzige Regel, fuer Messung und Auslieferung gleich:

    upto_season = Vorhersagesaison = letzte Trainingssaison + 1

Im Fold ist das die Testsaison, im Produktionsbundle die Saison, fuer
die es freigegeben wird.

WAS SICH AN DER LAUFZEIT NICHT AENDERT
--------------------------------------
Nichts. Die Karte steht weiterhin eingefroren im Bundle, die Laufzeit
liest keine Ligadatei nach, und die Kartenbildung selbst ist
unveraendert die aus C19 (c19_league_map.build_team_league_map). Neu
ist ausschliesslich, WELCHE Obergrenze an diese Funktion geht.
"""

import datetime as _dt
import functools
import json
import os

from src.ml import c19_league_map as c19

CONTRACT_VERSION = "v2-c20.1"

CONTRACT_PATH = "data/ml/c20_temporal_map_contract.json"
EVALUATION_PATH = "data/ml/c20_damped_league_strength_evaluation.json"


def prediction_season(training_seasons):
    """
    Die Saison, fuer die ein auf `training_seasons` trainiertes Modell
    vorhersagt.

    Bewusst aus den Trainingssaisons abgeleitet und nicht frei
    uebergeben: Eine frei waehlbare Obergrenze liesse sich spaeter
    unbemerkt auf eine Saison stellen, die nach der Vorhersage liegt.
    """
    saisons = sorted(int(s) for s in training_seasons)
    if not saisons:
        raise ValueError("ohne Trainingssaison gibt es keine "
                         "Vorhersagesaison")
    return saisons[-1] + 1


def fold_upto(fold):
    """
    Die Obergrenze der Karte eines Messfolds.

    Sie MUSS die Testsaison sein. Ein Fold, dessen Testsaison nicht
    unmittelbar auf die Trainingssaisons folgt, waere mit dieser Regel
    nicht beschreibbar - das wird geprueft, nicht angenommen.
    """
    upto = prediction_season(fold["train_seasons"])
    if int(fold["test_season"]) != upto:
        raise ValueError(
            "Fold %r: Testsaison %s folgt nicht auf die Trainingssaisons "
            "%s - der Vertrag ist dafuer nicht definiert"
            % (fold.get("name") or fold.get("fold"), fold["test_season"],
               fold["train_seasons"]))
    return upto


@functools.lru_cache(maxsize=None)
def _karte(upto):
    karte, diagnose = c19.build_team_league_map(upto)
    return karte, diagnose


def fold_map(fold):
    """Die Karte eines Messfolds - ueber den unveraenderten C19-Bauer."""
    return dict(_karte(fold_upto(fold))[0])


def fold_map_diagnosis(fold):
    return dict(_karte(fold_upto(fold))[1])


def production_map(training_seasons):
    """
    Die Karte eines Produktionsbundles.

    Sie reicht bis zur Vorhersagesaison. Liegt fuer diese Saison lokal
    noch keine Ligadatei vor, liest der Bauer bis zur letzten
    vorhandenen - und die Diagnose sagt das ausdruecklich
    (`seasons_used`). Ein Verein, dessen Mitgliedschaft dadurch nicht
    belegt ist, bleibt `team_not_in_map`; die Laufzeit zaehlt ihn.
    """
    upto = prediction_season(training_seasons)
    karte, diagnose = _karte(upto)
    return dict(karte), dict(diagnose)


def comparison_resolvers():
    """
    Die drei Informationsstaende, unter denen C20 gemessen hat.

    Fuer c16.run_measurement(zeilen, resolver). Damit ist der
    Vergleich, der den C19-Defekt belegt, aus dem Code reproduzierbar
    und nicht nur aus einem Bericht.

      A  unbegrenzt - liest auch Saisons NACH der Testsaison
      B  C19        - bis zur letzten Trainingssaison
      C  C20        - bis zur Vorhersagesaison (dieser Vertrag)

    A und B sind ausdruecklich KEINE zulaessigen Vertraege. Sie stehen
    hier nur, damit der Vergleich nachgerechnet werden kann.
    """
    from src.ml import c14_reevaluation as c14

    return {
        "A_unbounded": lambda fold: c14.team_league_map(),
        "B_c19_training_end": (
            lambda fold: dict(_karte(max(fold["train_seasons"]))[0])),
        "C_c20_prediction_season": fold_map,
    }


def reset_cache():
    _karte.cache_clear()


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def contract():
    """Die Regeln - ohne eine einzige Messung."""
    return {
        "version": CONTRACT_VERSION,
        "supersedes": {
            "contract_version": c19.CONTRACT_VERSION,
            "contract_fingerprint": c19.contract_fingerprint(),
            "what_changes": "ausschliesslich die Obergrenze der Karte",
            "defect": ("C19 begrenzte die Karte eines Folds auf die "
                       "letzte Trainingssaison und verwechselte damit "
                       "eine fehlende lokale Saisondatei mit einer "
                       "unbekannten Ligazugehoerigkeit"),
            "c19_artifacts_untouched": True,
        },
        "map_builder": {
            "function": "src.ml.c19_league_map.build_team_league_map",
            "unchanged": True,
            "reads": ("ausschliesslich die Kennungen der teilnehmenden "
                      "Vereine je Saisondatei; keine Tore, kein "
                      "Spielausgang"),
        },
        "information_classes": {
            "match_results_after_cutoff": {
                "admissible": False,
                "used_by_map": False,
            },
            "league_membership_after_prediction_season": {
                "admissible": False,
                "why": ("Mitgliedschaft einer spaeteren Saison steht vor "
                        "Anstoss nicht fest (Auf- und Abstieg)"),
            },
            "league_membership_of_prediction_season": {
                "admissible": True,
                "why": ("steht mit dem veroeffentlichten Spielplan vor "
                        "Saisonbeginn fest und damit vor jeder "
                        "Ligaphasenpartie derselben Saison"),
            },
            "identity_crosswalk": {
                "admissible": True,
                "why": ("statische Identitaetsmetadaten aus dem "
                        "geprueften Crosswalk, kein Leistungswert"),
            },
        },
        "upto_rule": {
            "formula": "upto_season = max(training_seasons) + 1",
            "evaluation_fold": "die Testsaison des Folds",
            "production_bundle": "die Saison, fuer die das Bundle "
                                 "freigegeben wird",
            "never": "eine Saison nach der Vorhersagesaison",
            "fold_must_be_consecutive": True,
        },
        "local_coverage": {
            "note": ("Eine fehlende lokale Saisondatei ist keine "
                     "unbekannte Mitgliedschaft. Der Bauer liest, was "
                     "lokal fuer zulaessige Saisons vorliegt; was dadurch "
                     "nicht belegt ist, bleibt team_not_in_map und wird "
                     "gezaehlt - es wird nicht geraten."),
        },
        "unknown_semantics_reference": {
            "contract": c19.CONTRACT_VERSION,
            "team_not_in_map": "Lambdas unveraendert",
            "league_without_parameters": ("Beitrag 0, die bekannte Seite "
                                          "korrigiert weiter"),
        },
        "parameter_estimation": {
            "same_map_for_estimation_and_application": True,
        },
        "gates": "unveraendert aus dem C16-Vertrag",
        "binds": ["evaluation", "bundle", "runtime"],
    }


def contract_fingerprint():
    return c19._stabil(contract())


def build_contract_artifact(fold_definitions, training_seasons):
    """
    Der Vertrag samt der Karten, die er erzeugt - VOR der Messung.
    """
    karten = {}
    for fold in fold_definitions:
        diagnose = fold_map_diagnosis(fold)
        karten[fold["name"]] = {
            "train_seasons": list(fold["train_seasons"]),
            "test_season": fold["test_season"],
            "upto_season": diagnose["upto_season"],
            "seasons_used": diagnose["seasons_used"],
            "teams": diagnose["teams"],
            "map_fingerprint": diagnose["map_fingerprint"],
        }
    _karte_p, produktion = production_map(training_seasons)
    return {
        "artifact": "v2-c20 temporal league map contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": c19._git(),
        "contract": contract(),
        "contract_fingerprint": contract_fingerprint(),
        "frozen_before_measurement": True,
        "fold_maps": karten,
        "production_map": {
            "training_seasons": sorted(training_seasons),
            "prediction_season": prediction_season(training_seasons),
            "upto_season": produktion["upto_season"],
            "seasons_used": produktion["seasons_used"],
            "teams": produktion["teams"],
            "map_fingerprint": produktion["map_fingerprint"],
        },
    }


def write_json(pfad, dokument):
    """Atomar und deterministisch schreiben. Nie ueberschreiben."""
    ziel = os.path.join(c19._repo_root(), pfad)
    if os.path.exists(ziel):
        raise FileExistsError(
            "%s existiert bereits - ein eingefrorenes Artefakt wird nicht "
            "ueberschrieben" % pfad)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    tmp = ziel + ".tmp"
    with open(tmp, "w", encoding="utf-8") as datei:
        json.dump(dokument, datei, ensure_ascii=False, indent=1,
                  sort_keys=True, default=str)
        datei.write("\n")
    os.replace(tmp, ziel)
    return ziel
