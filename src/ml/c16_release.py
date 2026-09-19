"""
Das finale C16-Modell und seine Freigabe (V2-C16).

WAS HIER ENTSTEHT
-----------------
Ein Bundle, das BEIDE Stufen traegt. Das bisherige Format kannte nur
die nationale Basisstufe; ein Bundle ohne die Ligastaerke wuerde zur
Laufzeit nur das halbe Modell anwenden und dabei aussehen wie das
ganze.

Der Zusatzblock heisst `league_strength` und enthaelt die
Ligaparameter, die Daempfung und die Ligazuordnung der Vereine.

WARUM DIE LIGAZUORDNUNG IM BUNDLE LIEGT
---------------------------------------
Sie zur Laufzeit aus den Ligadateien zu holen haette zwei Nachteile:
Jede Simulation muesste 23 Dateien lesen, und zwei Laeufe desselben
Bundles koennten je nach Plattenstand verschieden rechnen. Im Bundle
ist sie Teil des Modells und wandert mit ihm.

DIE FREIGABE
------------
Sie laeuft ueber denselben transaktionalen Weg wie V2-C15:
Vorpruefung, Vorzustandssicherung, Registry schreiben, erneut
validieren, erst danach das Releaseartefakt. Der Stufenweg ist
`candidate`, `shadow`, `active` - ein nie im Schatten gelaufenes
Modell wirkt nicht als erstes auf Nutzer.
"""

import json
import os

from src.ml import c15_release as base
from src.ml import c16_damped_league_strength as c16
from src.ml import model_registry as mr

BUNDLE_DIR = "data/ml/models"

#: Fassung des Bundleformats mit zweiter Stufe. Die bestehende Fassung
#: 2 bleibt gueltig und unveraendert; ein Bundle ohne
#: `league_strength` rechnet Bit fuer Bit wie zuvor.
BUNDLE_SCHEMA_WITH_LEAGUE = 3


def _bundle_hash_vorab(bundle):
    """
    Der Hash, den die Datei nach dem Schreiben tragen wird.

    Dieselbe Serialisierung wie `persist.save_bundle`, damit
    Trockenlauf und Anwendung denselben Wert sehen.
    """
    import hashlib
    import json as _json

    text = _json.dumps(bundle, indent=2, ensure_ascii=False,
                       sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cutoff_stunde():
    from src.features import prediction_cutoff as pc

    return pc.CUTOFF_HOUR


def _stabil_kurz(block):
    """Ein kurzer, stabiler Fingerabdruck der zweiten Stufe."""
    import hashlib
    import json as _json

    text = _json.dumps(block, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class ReleaseError(RuntimeError):
    """Die Freigabe ist nicht zulaessig oder nicht sicher durchfuehrbar."""


# ---------------------------------------------------------------------------
# Bauumgebung und Modellinhalt trennen (V2-C22)
# ---------------------------------------------------------------------------

#: Felder, in denen sich zwei Bauten desselben Modells unterscheiden
#: DUERFEN: Sie beschreiben, WANN und WO gebaut wurde, nicht WAS.
#: Bauzeitpunkt, Commit, Zustand des Arbeitsbaums, Plattform und
#: Bibliotheksversionen. Jede andere Abweichung - Koeffizienten,
#: Ligakarte, Vertragsbindungen, Datensatzfingerabdruck, Integritaetshash
#: der Modelle - heisst, es wurde nicht dasselbe Modell gebaut.
#:
#: Eingefuehrt in V2-C21 fuer den isolierten Trockenlauf, seit V2-C22 im
#: Freigabeweg selbst: Eine vorhandene Bundledatei wird nur noch
#: uebernommen, wenn sie ausserhalb dieser Felder dem Neubau gleicht.
BUILD_METADATA_FIELDS = (
    "created_at", "provenance/git_commit", "provenance/git_dirty",
    "provenance/git_status", "provenance/platform",
    "provenance/python_version", "provenance/sklearn_version")


def is_build_metadata(pfad):
    """Gehoert ein Pfad aus differing_fields zur Bauumgebung?"""
    return any(pfad == f or pfad.startswith(f + "/")
               or pfad.startswith(f + "[") for f in BUILD_METADATA_FIELDS)


def differing_fields(a, b, pfad=""):
    """Alle Pfade, an denen sich zwei JSON-Dokumente unterscheiden."""
    if isinstance(a, dict) and isinstance(b, dict):
        heraus = []
        for k in sorted(set(a) | set(b)):
            unter = "%s/%s" % (pfad, k) if pfad else k
            if k not in a or k not in b:
                heraus.append(unter)
            else:
                heraus.extend(differing_fields(a[k], b[k], unter))
        return heraus
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [pfad]
        heraus = []
        for i, (x, y) in enumerate(zip(a, b)):
            heraus.extend(differing_fields(x, y, "%s[%d]" % (pfad, i)))
        return heraus
    return [] if a == b else [pfad]


def bundle_mismatch(vorhanden, gebaut):
    """
    Die modellrelevanten Abweichungen zwischen einer vorhandenen
    Bundledatei und dem Neubau.

    Der Neubau wird vorher so serialisiert, wie `persist.save_bundle`
    ihn schreiben wuerde, damit Tupel und Listen nicht als Abweichung
    erscheinen. Rueckgabe: (alle abweichenden Pfade, davon
    modellrelevante).
    """
    normiert = json.loads(json.dumps(gebaut, sort_keys=True,
                                     ensure_ascii=False, default=str))
    alle = differing_fields(vorhanden, normiert)
    return alle, [p for p in alle if not is_build_metadata(p)]


# ---------------------------------------------------------------------------
# Die Artefakte, von denen der Freigabeweg abhaengt (V2-C22)
# ---------------------------------------------------------------------------

def dependency_findings():
    """
    Die Dateiabhaengigkeiten des Freigabewegs, fail-closed geprueft.

    Bis C21 standen sie nur im Runbook. Zwei davon wirkten still:
    Fehlt das C10-Artefakt, scheitert erst die Freigabe mit einer
    Ausnahme. Fehlt das C16-Artefakt, liefert der C17-Vertrag einen
    anderen Fingerabdruck, und ein Neubau truege stillschweigend eine
    andere Bindung als der gemessene Kandidat.

    Geprueft wird deshalb, dass jede Datei vorliegt und dass der
    C17-Vertragsfingerabdruck, wie ihn der Code JETZT berechnet, dem
    eingefrorenen C17-Vertragsartefakt gleicht. Ein fehlendes oder
    veraendertes C16-Artefakt faellt genau dort auf.

    Rueckgabe: Liste der Befunde. Leer heisst in Ordnung.
    """
    from src.ml import c10_contract as c10
    from src.ml import c17_bundle_contract as c17
    from src.ml import early_v2 as e9

    befunde = []
    if not base._c9_manifest_fingerprint(_repo_root()):
        befunde.append("das C9-Manifest fehlt: %s" % e9.MANIFEST_PATH)
    if not base._artefakt_feld(_repo_root(), c10.ARTIFACT_PATH,
                               "contract_fingerprint"):
        befunde.append("das C10-Vertragsartefakt fehlt oder traegt keinen "
                       "Fingerabdruck: %s" % c10.ARTIFACT_PATH)
    if not base._artefakt_feld(_repo_root(), c16.ARTIFACT_PATH,
                               "result_fingerprint"):
        befunde.append("das C16-Messartefakt fehlt oder traegt keinen "
                       "Ergebnisfingerabdruck: %s" % c16.ARTIFACT_PATH)
    eingefroren = base._artefakt_feld(_repo_root(), c17.CONTRACT_PATH,
                                      "contract_fingerprint")
    if not eingefroren:
        befunde.append("das C17-Vertragsartefakt fehlt: %s"
                       % c17.CONTRACT_PATH)
    elif eingefroren != c17.contract_fingerprint():
        befunde.append(
            "der C17-Vertragsfingerabdruck weicht vom eingefrorenen ab "
            "(C16-Messartefakt fehlt oder wurde veraendert?)")
    # V2-C22: der eingefrorene Aequivalenzvertrag und die Foldreferenzen,
    # gegen die ein nicht bitgleicher Neubau geprueft wird.
    from src.ml import c22_release_equivalence as c22

    befunde.extend(c22.dependency_findings())
    return befunde


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Das finale Modell
# ---------------------------------------------------------------------------

def build_final_bundle(zeilen, ligakarte, evaluation, seasons=None,
                       map_upto_season=None, map_contract=None):
    """
    Das finale C16-Bundle - beide Stufen, deterministisch.

    Stufe eins entsteht ueber den bestehenden, getesteten Weg
    (`persist.train_cl_model`) auf den nationalen Ligazeilen.

    DIE FREIGABESTUFE IM BUNDLE
    Sie ist `approved`, und das ist kein Widerspruch zum
    Registryweg candidate -> shadow -> active. Beide beschreiben
    Verschiedenes: Die Bundlestufe sagt, was dieses ARTEFAKT
    ueberhaupt darf, die Registrystufe sagt, welches Modell es
    gerade IST. Ein Bundle auf `shadow` duerfte auch dann keine
    Nutzerantwort bestimmen, wenn die Registry es aktiv fuehrt -
    die Laufzeit weist es an der Stufenpruefung ab. Fuer ein Modell,
    das alle elf Gates erfuellt hat, ist `approved` die richtige
    Aussage. Stufe
    zwei wird auf der GESAMTEN verfuegbaren CL-Historie geschaetzt,
    und gamma nach derselben inneren Regel gewaehlt wie in der
    Messung.

    Rueckgabe: (bundle, diagnose).
    """
    from src.features import league_strength as ls
    from src.ml import c19_league_map as c19
    from src.ml import c15_league_strength as c15
    from src.ml import cl_evaluate as ce
    from src.ml import evaluate as ev
    from src.ml import feature_groups as fg
    from src.ml import model as mdl
    from src.ml import persist as ps

    seasons = tuple(seasons or ps.DEFAULT_TRAINING_SEASONS)

    # -- Stufe eins ------------------------------------------------------
    #
    # HIER LIEGT EINE ECHTE VERTRAGSGRENZE, UND SIE WIRD NICHT
    # UMGANGEN.
    #
    # `persist.evaluation_reference` verlangt aus V2-C0B drei Dinge:
    # das Evaluationsartefakt muss `configuration.task ==
    # "cl_shadow_backtest"` tragen, seinen Kandidatennamen mit dem
    # Training teilen, und `load_bundle` prueft denselben Namen beim
    # Laden gegen `cl_evaluate.CANDIDATE`.
    #
    # Ein zweistufiges C16-Modell erfuellt keine dieser drei
    # Bedingungen. Sie zu erfuellen hiesse, den Provenienzvertrag, die
    # Kandidatenpruefung UND den Loader gleichzeitig aufzuweichen -
    # also genau die Schranken, gegen deren Umgehung V2-C11 und V2-C15
    # gebaut wurden.
    #
    # Der Bundlevertrag fuer ein MEHRSTUFIGES Modell ist eigene Arbeit
    # mit eigenem eingefrorenen Vertrag. Bis dahin scheitert dieser
    # Weg fail-closed und mit klarem Grund, statt ein Bundle zu
    # erzeugen, das der Loader spaeter ablehnt oder - schlimmer - ein
    # halbes Modell mit dem Etikett eines ganzen.
    # Seit V2-C17 traegt der Bundlevertrag mehrstufige Modelle
    # ausdruecklich: Der C16-Kandidat steht namentlich in
    # c17_bundle_contract.ALLOWED_MULTISTAGE_CANDIDATES, und das
    # C16-Artefakt ist eine zugelassene Evaluationsart. Beides ist
    # eine benannte Erweiterung, keine generische Ausnahme.
    try:
        bundle = ps.train_cl_model(zeilen, evaluation, seasons=seasons,
                                   candidate=c16.CANDIDATE,
                                   release_stage=ps.STAGE_APPROVED)
    except ps.ModelBundleError as fehler:
        raise ReleaseError(
            "Der Bundlevertrag laesst dieses Modell nicht zu: %s"
            % fehler)

    # -- Stufe zwei, auf der gesamten verfuegbaren CL-Historie ----------
    historie = ce.context_rows(zeilen, list(seasons))
    if not historie:
        raise ReleaseError(
            "ohne CL-Historie entsteht keine Ligastaerke - ein Bundle "
            "mit leerer zweiter Stufe waere ein halbes Modell mit dem "
            "Etikett eines ganzen")

    spalten = fg.columns_for(fg.C15_CANDIDATE)
    modelle = {seite: mdl.fit_side(
        ce.league_rows(zeilen, list(seasons)), seite,
        bundle["alpha"], spalten)[0] for seite in ("home", "away")}

    def basis_lambdas(rows):
        lam, _ = ev.predict_lambdas(bundle["alpha"], modelle, rows, spalten)
        return lam

    frueh, spaet, innen = c15._innere_teilung(historie, seasons)

    alpha, alpha_protokoll = None, {"strategy": "keine innere Teilung"}
    if frueh and spaet:
        alpha, alpha_protokoll = ls.select_alpha(
            frueh, basis_lambdas(frueh), spaet, basis_lambdas(spaet),
            ligakarte, mdl.ALPHA_CANDIDATES)
    if alpha is None:
        alpha = max(mdl.ALPHA_CANDIDATES)
        alpha_protokoll = dict(alpha_protokoll,
                               fallback="staerkste Regularisierung")

    gamma, gamma_protokoll = None, {"strategy": "keine innere Teilung"}
    if frueh and spaet:
        staerke_innen = ls.estimate(frueh, basis_lambdas(frueh), ligakarte,
                                    alpha)
        gamma, gamma_protokoll = ls.select_gamma(
            staerke_innen, spaet, basis_lambdas(spaet), ligakarte)
    if gamma is None:
        gamma = min(ls.GAMMA_GRID)
        gamma_protokoll = dict(gamma_protokoll,
                               fallback="kleinstes Gamma des Gitters")

    staerke = ls.estimate(historie, basis_lambdas(historie), ligakarte,
                          alpha)
    if staerke.is_neutral():
        raise ReleaseError(
            "die Ligastaerke blieb neutral - zu wenige Beobachtungen. "
            "Ein Bundle, dessen zweite Stufe nichts tut, waere als "
            "C16-Modell falsch etikettiert.")

    # DIE KARTE IST DIESELBE, MIT DER GEMESSEN WURDE (V2-C19).
    #
    # Bis C18 stand hier eine Einschraenkung auf die Vereine, die in
    # den Trainings-CL-Partien vorkamen - 63 statt 146. Sie war als
    # "nur was zum Modell gehoert" gedacht und hatte eine Nebenwirkung,
    # die niemand geprueft hat: Die MESSUNG schlug in der vollen Karte
    # nach, die AUSLIEFERUNG in der gekuerzten. Nachgemessen wandte die
    # Evaluation auf 188 von 283 Standardpartien einen Ligafaktor an,
    # den die Laufzeit gar nicht anwenden konnte.
    #
    # Ein Verein, der noch nie Champions League gespielt hat, ist
    # deshalb keine unbekannte Liga. Seine Liga ist bekannt, und das
    # Modell hat fuer sie gelernt. Ihn aus der Karte zu lassen hiess,
    # ihn zu behandeln, als gaebe es seine Liga nicht.
    #
    # Eingefroren wird deshalb die VOLLSTAENDIGE Karte, die auch die
    # Schaetzung benutzt hat. Sie ist weiterhin Teil des Modells und
    # keine Momentaufnahme der Platte: Die Laufzeit liest sie aus dem
    # Bundle und nie aus den Ligadateien.
    ligakarte = dict(ligakarte or {})
    # WELCHER Vertrag die Karte bestimmt, gehoert in die Provenienz.
    # Ohne Angabe bleibt es beim C19-Vertrag, damit dessen Kandidat
    # reproduzierbar bleibt. Der Produktionsweg (run_release) uebergibt
    # seit V2-C20 ausdruecklich den korrigierten Vertrag - dort reicht
    # die Karte bis zur Vorhersagesaison statt bis zur letzten
    # Trainingssaison.
    obergrenze = (map_upto_season if map_upto_season is not None
                  else max(seasons))
    if map_contract is None:
        # Bit fuer Bit der C19-Block. Er geht in den Hash der Modell-ID
        # ein; jede zusaetzliche Zeile machte den C19-Kandidaten
        # nachtraeglich unreproduzierbar.
        karte_diagnose = {
            "source": "v2-c19 gemeinsamer Zuordnungsvertrag",
            "contract_fingerprint": c19.contract_fingerprint(),
            "upto_season": obergrenze,
            "teams": len(ligakarte),
            "map_fingerprint": c19.map_fingerprint(ligakarte, obergrenze),
            "note": ("dieselbe Karte, mit der die zweite Stufe geschaetzt "
                     "und gemessen wurde"),
        }
    else:
        karte_diagnose = {
            "source": "%s Zuordnungsvertrag" % map_contract.CONTRACT_VERSION,
            "contract_version": map_contract.CONTRACT_VERSION,
            "contract_fingerprint": map_contract.contract_fingerprint(),
            "upto_season": obergrenze,
            "training_seasons": sorted(seasons),
            "teams": len(ligakarte),
            "map_fingerprint": c19.map_fingerprint(ligakarte, obergrenze),
            "note": ("dieselbe Karte, mit der die zweite Stufe geschaetzt "
                     "und gemessen wurde; sie reicht bis zur "
                     "Vorhersagesaison"),
        }

    bundle["schema_version"] = BUNDLE_SCHEMA_WITH_LEAGUE
    bundle["league_strength"] = {
        "stage": 2,
        "gamma": gamma,
        "alpha": alpha,
        "attack": {k: round(v, 10) for k, v in sorted(staerke.attack.items())},
        "defence": {k: round(v, 10)
                    for k, v in sorted(staerke.defence.items())},
        "team_leagues": c19.bundle_map(ligakarte),
        # Additiv (V2-C19). Der Vertrag verlangt die Pflichtfelder;
        # zusaetzliche Provenienz ist erlaubt und hier noetig, weil
        # eine Karte ohne ihre Obergrenze nicht nachpruefbar ist.
        "team_leagues_provenance": karte_diagnose,
        "factor_bounds": [ls.FACTOR_MIN, ls.FACTOR_MAX],
        "trained_on": {
            "source": "Champions-League-Partien der Trainingssaisons",
            "seasons": sorted(seasons),
            "matches": len(historie),
            "observations": staerke.diagnose.get("observations"),
            "leagues": staerke.diagnose.get("columns", 0) // 2,
        },
        "selection": {"alpha": alpha_protokoll, "gamma": gamma_protokoll,
                      "inner_split": innen},
        "cold_start": ("Eine Liga ohne Eintrag traegt 0 und damit den "
                       "Faktor 1. Unbekannt heisst unbekannt."),
    }
    # Die Vertragsbindungen. Sie stehen IM Bundle, damit der Loader
    # sie prueft und ein spaeterer Leser sie nicht suchen muss.
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c17_bundle_contract as c17
    from src.ml import early_v2 as e9

    bundle["contract_bindings"] = {
        "c9_schema_fingerprint": e9.schema_fingerprint(),
        "c10_cutoff_hour": _cutoff_stunde(),
        "c13_contract_fingerprint": c13.contract_fingerprint(),
        "c14_contract_fingerprint": c14.contract_fingerprint(),
        "c15_contract_fingerprint": c15.contract_fingerprint(),
        "c16_contract_fingerprint": c16.contract_fingerprint(),
        "c16_model_schema_fingerprint": c16.schema_fingerprint(),
        "c16_result_fingerprint": evaluation.get("result_fingerprint"),
        "c17_contract_fingerprint": c17.contract_fingerprint(),
    }
    if map_contract is not None:
        # Additiv und nur auf dem ausdruecklichen Weg (V2-C20). Der
        # Zuordnungsvertrag bestimmt, welche Partien die zweite Stufe
        # ueberhaupt korrigieren kann - er gehoert zu den Bindungen und
        # nicht nur in die Provenienz der Karte.
        bundle["contract_bindings"]["%s_contract_fingerprint" % (
            map_contract.CONTRACT_VERSION.split(".")[0].replace(
                "v2-", ""))] = map_contract.contract_fingerprint()
    bundle["acceptance_class"] = (evaluation.get("decision") or {}).get(
        "acceptance_class")
    bundle["known_limits"] = [
        "Kein unangetasteter Holdout. Die Modellform wurde auf "
        "denselben Saisons abgeleitet, auf denen sie gemessen wurde.",
        "Eine unabhaengige Bestaetigung waere erst mit Saison 2026/27 "
        "moeglich.",
    ]

    # Die Modell-ID muss die ZWEITE Stufe mit abdecken. Zwei Bundles,
    # die sich nur in gamma unterscheiden, waeren sonst gleich
    # benannt - und ein Rollback koennte das falsche erwischen.
    bundle["model_id"] = "%s-ls%s" % (
        bundle["model_id"],
        _stabil_kurz(bundle["league_strength"]))

    # Der Vertrag muss das fertige Bundle tragen, bevor es die Funktion
    # verlaesst. Ein Bundle, das erst der Loader ablehnt, waere zu
    # spaet geprueft.
    c17.assert_bundle(bundle)

    return bundle, {
        "gamma": gamma, "league_alpha": alpha,
        "leagues": len(staerke.attack),
        "teams_mapped": len(bundle["league_strength"]["team_leagues"]),
        "history_matches": len(historie),
    }


def write_bundle(bundle, pfad=None, force=False):
    """
    Das Bundle schreiben und danach wieder laden.

    Der Loader ist die eigentliche Pruefung: Was hier ankommt, ist
    bereits einmal erfolgreich gelesen worden.
    """
    from src.ml import persist as ps

    pfad = pfad or os.path.join(BUNDLE_DIR,
                                "%s.json" % bundle["model_id"])
    ps.save_bundle(bundle, pfad, force=force)
    return pfad


# ---------------------------------------------------------------------------
# Die Freigabe
# ---------------------------------------------------------------------------

def _registry_eintrag(bundle, bundle_pfad, artefakt_pfad,
                      dry_run=False):
    """
    Der Registryeintrag mit allen Bindungen.

    Im Trockenlauf liegt das Bundle noch nicht auf der Platte. Der
    Hash wird dann aus dem Bundleinhalt gebildet, damit die
    Vorpruefung dieselbe Groesse sieht wie spaeter der Loader.
    """
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15

    return {
        "model_id": bundle["model_id"],
        "model_name": c16.CANDIDATE,
        "model_family": bundle["model_family"],
        "bundle_schema_version": bundle["schema_version"],
        "stage": mr.STAGE_CANDIDATE,
        "bundle_path": bundle_pfad.replace(os.sep, "/"),
        "bundle_sha256": (_bundle_hash_vorab(bundle) if dry_run
                          else mr.bundle_sha256(bundle_pfad)),
        "feature_schema_fingerprint": c16.schema_fingerprint(),
        "c9_manifest_fingerprint": base._c9_manifest_fingerprint(),
        "c10_contract_fingerprint": base._artefakt_feld(
            None, "data/ml/c10_prediction_cutoff_contract_2023-2025.json",
            "contract_fingerprint"),
        "c13_contract_fingerprint": c13.contract_fingerprint(),
        "c14_contract_fingerprint": c14.contract_fingerprint(),
        "c15_contract_fingerprint": c15.contract_fingerprint(),
        "c16_contract_fingerprint": c16.contract_fingerprint(),
        "evaluation_artifact": artefakt_pfad,
        "evaluation_status": mr.EVALUATION_ACCEPTED,
        "state_reason": ("V2-C16: alle elf Gates erfuellt, Freigabe ueber "
                         "den regulaeren Weg"),
    }


def preflight(urteil, eintrag, bundle_pfad=None, repo_root=None,
              dokument=None):
    """
    Alles pruefen, was vor einem Schreibvorgang stimmen muss.

    Dieselbe Struktur wie V2-C15, aber gegen den C16-Vertrag und das
    C16-Schema. Fail-closed: Jeder unklare Fall verhindert die
    Freigabe.
    """
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15

    befunde = []

    if (urteil or {}).get("verdict") != c16.VERDICT_ACCEPTED:
        befunde.append(
            "das Urteil lautet %r, nicht accepted"
            % (urteil or {}).get("verdict"))
    try:
        c16.assert_contract_matches(urteil)
    except c16.ContractViolation as fehler:
        befunde.append(str(fehler))

    if not eintrag:
        befunde.append("kein Registryeintrag uebergeben")
        return False, befunde

    for feld in ("model_id", "bundle_sha256",
                 "feature_schema_fingerprint"):
        if not eintrag.get(feld):
            befunde.append("dem Eintrag fehlt %s" % feld)

    if bundle_pfad:
        voll = base._pfad(repo_root, bundle_pfad)
        if not os.path.isfile(voll):
            befunde.append("das Bundle fehlt: %s" % bundle_pfad)
        else:
            ist = mr.bundle_sha256(voll)
            if ist != eintrag.get("bundle_sha256"):
                befunde.append("der Bundle-Hash stimmt nicht")
            else:
                # Das Bundle MUSS die zweite Stufe tragen, sonst waere
                # es ein C15-Modell mit C16-Etikett.
                try:
                    with open(voll, encoding="utf-8") as datei:
                        roh = json.load(datei)
                except (OSError, ValueError):         # pragma: no cover
                    roh = {}
                if not (roh.get("league_strength") or {}).get("attack"):
                    befunde.append(
                        "dem Bundle fehlt die zweite Stufe - es waere "
                        "ein halbes Modell mit dem Etikett eines ganzen")
                elif (roh.get("league_strength") or {}).get("gamma") is None:
                    befunde.append("dem Bundle fehlt gamma")

    if eintrag.get("feature_schema_fingerprint") != c16.schema_fingerprint():
        befunde.append("das Merkmalsschema passt nicht zu C16")

    erwartet = {
        "c9_manifest_fingerprint": base._c9_manifest_fingerprint(),
        "c13_contract_fingerprint": c13.contract_fingerprint(),
        "c14_contract_fingerprint": c14.contract_fingerprint(),
        "c15_contract_fingerprint": c15.contract_fingerprint(),
        "c16_contract_fingerprint": c16.contract_fingerprint(),
    }
    for feld, wert in erwartet.items():
        if eintrag.get(feld) not in (None, wert):
            befunde.append("%s stimmt nicht" % feld)

    if pc.CUTOFF_HOUR != 12 or pc.CUTOFF_INCLUSIVE is not False:
        befunde.append("der C10-Stichtagsvertrag ist veraendert")

    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    fehler_registry = mr.validate_registry(dokument, repo_root)
    if fehler_registry:
        befunde.append("die Registry ist nicht valide: %s"
                       % fehler_registry[:3])

    aktiv = [m for m in (dokument.get("models") or [])
             if m.get("stage") == mr.STAGE_ACTIVE]
    if len(aktiv) > 1:
        befunde.append("es sind bereits mehrere Modelle aktiv")

    return (not befunde), befunde


def apply_release(urteil, eintrag, artefakt, bundle_pfad=None,
                  repo_root=None, dokument=None, dry_run=True,
                  fail_after=None):
    """
    Die Freigabe anwenden - oder als Trockenlauf durchspielen.

    Derselbe transaktionale Weg wie V2-C15, gegen den C16-Vertrag.
    """
    protokoll = []
    schritte = {}
    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    vorher_fp = mr.registry_fingerprint(dokument)

    def stufe(name):
        schritte[name] = True
        if not dry_run:
            base.write_journal(schritte, repo_root,
                               extra={"model_id": eintrag.get("model_id"),
                                      "registry_before": vorher_fp,
                                      "block": "v2-c16"})
        if fail_after == name:
            raise ReleaseError("Absturzprobe nach Schritt %r" % name)

    ok, befunde = preflight(urteil, eintrag, bundle_pfad, repo_root,
                            dokument)
    protokoll.append("Vorpruefung: %s" % ("bestanden" if ok
                                          else "%d Befunde" % len(befunde)))
    for befund in befunde:
        protokoll.append("  ! %s" % befund)
    if not ok:
        return {"status": "refused", "reason": befunde[0],
                "findings": befunde, "log": protokoll,
                "registry_before": vorher_fp, "registry_after": vorher_fp,
                "wrote_anything": False}
    stufe("preflight_ok")

    if dry_run:
        protokoll.append("Trockenlauf: kein Vorzustand geschrieben")
    else:
        base.save_snapshot(dokument, repo_root)
        protokoll.append("Vorzustand gesichert")
    stufe("snapshot_written")

    # Registrieren, falls noch nicht geschehen.
    neu = dokument
    if not any(m.get("model_id") == eintrag["model_id"]
               for m in (neu.get("models") or [])):
        neu = mr.register_candidate(neu, eintrag)
        protokoll.append("als Kandidat registriert")

    stufen_weg = []
    aktueller = next(m for m in neu["models"]
                     if m["model_id"] == eintrag["model_id"])

    # BEREITS FREIGEGEBEN IST KEIN FEHLER.
    #
    # Ein zweiter Aufruf soll nicht versuchen, ein aktives Modell
    # noch einmal zu aktivieren - der Uebergang active -> active ist
    # zu Recht nicht vorgesehen. Er soll den Zustand feststellen und
    # ihn bestaetigen, und zwar nur dann, wenn die Freigabe wirklich
    # gueltig ist.
    if aktueller.get("stage") == mr.STAGE_ACTIVE:
        gueltig, warum = mr.verify_approval(aktueller,
                                            aktueller.get("approval"),
                                            mr.STAGE_ACTIVE)
        if not gueltig:
            return {"status": "refused",
                    "reason": ("das Modell ist aktiv, seine Freigabe "
                               "traegt aber nicht: %s" % warum),
                    "log": protokoll, "registry_before": vorher_fp,
                    "registry_after": vorher_fp,
                    "wrote_anything": False}
        protokoll.append("Modell ist bereits aktiv und die Freigabe "
                         "traegt - nichts zu tun")
        return {"status": "already_active", "log": protokoll,
                "registry_before": vorher_fp,
                "registry_after": vorher_fp,
                "model_id": eintrag["model_id"],
                "wrote_anything": False}

    if aktueller.get("stage") == mr.STAGE_CANDIDATE:
        freigabe_schatten = mr.build_approval(
            aktueller, mr.STAGE_SHADOW,
            reason=("V2-C16: Der Kandidat hat alle elf Gates erfuellt "
                    "und geht zuerst in den Schattenbetrieb."))
        neu = mr.set_stage(neu, eintrag["model_id"], mr.STAGE_SHADOW,
                           approval=freigabe_schatten)
        stufen_weg.append("candidate -> shadow")

    im_schatten = next(m for m in neu["models"]
                       if m["model_id"] == eintrag["model_id"])
    freigabe = mr.build_approval(
        im_schatten, mr.STAGE_ACTIVE,
        reason=("V2-C16: Alle elf verpflichtenden Gates sind erfuellt. "
                "Die Freigabe ist an Bundle, Merkmalsschema und die "
                "Vertraege C9, C10, C13, C14, C15 und C16 gebunden."))
    neu = mr.set_stage(neu, eintrag["model_id"], mr.STAGE_ACTIVE,
                       approval=freigabe)
    stufen_weg.append("shadow -> active")
    protokoll.append("Registryzustand vorbereitet: %s"
                     % " , ".join(stufen_weg))

    aktiv = [m for m in neu["models"] if m.get("stage") == mr.STAGE_ACTIVE]
    if len(aktiv) != 1:
        return {"status": "refused",
                "reason": "nach der Aenderung waeren %d Modelle aktiv"
                          % len(aktiv),
                "log": protokoll, "registry_before": vorher_fp,
                "registry_after": vorher_fp, "wrote_anything": False}

    fehler = mr.validate_registry(neu, repo_root)
    if fehler:
        return {"status": "refused",
                "reason": "der vorbereitete Zustand ist nicht valide: %s"
                          % fehler[:2],
                "log": protokoll, "registry_before": vorher_fp,
                "registry_after": vorher_fp, "wrote_anything": False}
    protokoll.append("vorbereiteter Zustand validiert")
    nachher_fp = mr.registry_fingerprint(neu)

    release_artefakt = {
        "artifact": "v2-c16 release",
        "model_id": eintrag["model_id"],
        "bundle_path": bundle_pfad,
        "bundle_sha256": eintrag.get("bundle_sha256"),
        "bundle_schema_version": eintrag.get("bundle_schema_version"),
        "feature_schema_fingerprint": c16.schema_fingerprint(),
        "contract_fingerprint": c16.contract_fingerprint(),
        "evaluation_result_fingerprint": (artefakt or {}).get(
            "result_fingerprint"),
        "verdict": (urteil or {}).get("verdict"),
        "approval": {k: v for k, v in freigabe.items() if k != "token"},
        "approval_token_present": bool(freigabe.get("token")),
        "transitions": stufen_weg,
        "registry_before": vorher_fp,
        "registry_after": nachher_fp,
    }
    stufe("artifact_staged")

    if dry_run:
        protokoll.append("Trockenlauf beendet - nichts wurde geschrieben")
        return {"status": "dry_run_ok", "log": protokoll,
                "registry_before": vorher_fp,
                "registry_after_would_be": nachher_fp,
                "model_id": eintrag["model_id"], "wrote_anything": False}

    mr.write_registry(neu, repo_root=repo_root)
    protokoll.append("Registry geschrieben (atomar)")
    stufe("registry_written")

    frisch = mr.load_registry(repo_root=repo_root)
    if mr.registry_fingerprint(frisch) != nachher_fp:
        raise ReleaseError("die geschriebene Registry stimmt nicht mit "
                           "dem vorbereiteten Zustand ueberein")
    fehler = mr.validate_registry(frisch, repo_root)
    if fehler:
        raise ReleaseError("die geschriebene Registry ist nicht valide")
    protokoll.append("Registry von der Platte erneut validiert")
    stufe("registry_revalidated")

    pfad = base._atomar(base._pfad(repo_root, c16.RELEASE_PATH),
                        json.dumps(release_artefakt, indent=2,
                                   ensure_ascii=False, default=str))
    protokoll.append("Releaseartefakt geschrieben: %s" % c16.RELEASE_PATH)
    stufe("artifact_finalised")

    return {"status": "applied", "log": protokoll,
            "registry_before": vorher_fp, "registry_after": nachher_fp,
            "model_id": eintrag["model_id"], "artifact_path": pfad,
            "wrote_anything": True}


def rollback(repo_root=None, dry_run=True):
    """Den gesicherten Vorzustand wiederherstellen - Weg aus V2-C15."""
    return base.rollback(repo_root=repo_root, dry_run=dry_run)


def recover(repo_root=None):
    """Einen unterbrochenen Freigabevorgang aufloesen - Weg aus V2-C15."""
    return base.recover(repo_root=repo_root)


def release(dry_run=True, repo_root=None, expected_model_id=None):
    """
    Der Weg, den die CLI geht.

    Er laedt das Ergebnis der Messung UNTER DEM GELTENDEN
    ZUORDNUNGSVERTRAG, baut bei Bedarf das Bundle und wendet an - oder
    verweigert mit Grund. Ohne accepted passiert nichts.

    SEIT V2-C20 IST DAS DIE C20-MESSUNG
    Das Bundle traegt die Karte des C20-Vertrags. Es darf deshalb nur
    an eine Messung gebunden werden, die unter genau diesem Vertrag
    lief. Die C16-Messung benutzte eine unbegrenzte Karte, die fuer
    den fruehen Fold Mitgliedschaften einer spaeteren Saison las - ihr
    Urteil auf ein C20-Bundle zu uebertragen hiesse, eine Freigabe zu
    uebernehmen, ohne die Messung zu binden, auf der sie beruht.

    SEIT V2-C22 ZWEI NACHWEISE, NICHT EINER
    Neben der C20-Match-Messung verlangt der Weg die C21-Saisonfreigabe,
    und zwar fuer genau diesen Modellstand: Die Foldmodelle, auf denen
    C21 gemessen hat, muessen aus denselben Daten und derselben
    C20-Messung wieder entstehen (`c21_season_validation.
    release_evidence`). Dazu werden die Dateiabhaengigkeiten
    fail-closed geprueft (`dependency_findings`), eine vorhandene
    Bundledatei nur bei inhaltlicher Gleichheit mit dem Neubau
    uebernommen, und auf Wunsch die erwartete Modell-ID erzwungen.

    BITGLEICH ODER AEQUIVALENT, NIE ERSETZT (V2-C22)
    Bitgleich bleibt der erste Weg. In einer anderen numerischen
    Umgebung entsteht dasselbe Modell mit anderen letzten Stellen und
    damit einer anderen Modell-ID. Ein solcher Neubau bestaetigt das
    gespeicherte, per SHA-256 gepinnte Referenzbundle nur unter dem
    eingefrorenen Aequivalenzvertrag (`c22_release_equivalence`), und
    registriert wird danach das gespeicherte Bundle, nie der Neubau.
    Alles andere wird verweigert, und nichts wird geschrieben.
    """
    from src.ml import c20_temporal_map as c20

    pfad = base._pfad(repo_root, c20.EVALUATION_PATH)
    if not os.path.isfile(pfad):
        return {"status": "refused",
                "reason": "es gibt kein Ergebnis unter dem C20-Vertrag",
                "log": ["zuerst die C20-Messung ausfuehren"]}

    with open(pfad, encoding="utf-8") as datei:
        artefakt = json.load(datei)
    urteil = artefakt.get("decision") or {}

    if urteil.get("verdict") != c16.VERDICT_ACCEPTED:
        return {"status": "refused",
                "reason": ("das Urteil lautet %r, nicht accepted"
                           % urteil.get("verdict")),
                "log": ["ohne accepted wird nichts aktiviert"]}

    # Die Messung muss unter DEMSELBEN Vertrag gelaufen sein, den das
    # Bundle gleich tragen wird. Ein Ergebnisartefakt ohne diese
    # Bindung wird abgewiesen, nicht stillschweigend angenommen.
    bindung = (artefakt.get("map_contract") or {}).get("contract_fingerprint")
    if bindung != c20.contract_fingerprint():
        return {"status": "refused",
                "reason": ("das Ergebnis ist nicht an den geltenden "
                           "Zuordnungsvertrag gebunden"),
                "log": ["Vertrag im Ergebnis: %r" % bindung]}

    abhaengig = dependency_findings()
    if abhaengig:
        return {"status": "refused",
                "reason": abhaengig[0], "findings": abhaengig,
                "log": ["Dateiabhaengigkeiten unvollstaendig - fail-closed"]
                       + ["  ! %s" % b for b in abhaengig],
                "wrote_anything": False}

    from src.ml import c21_season_validation as c21
    from src.ml import dataset as ds
    from src.ml import persist as ps_

    protokoll = ["C20-Ergebnis geladen, Urteil accepted, Vertrag gebunden",
                 "Dateiabhaengigkeiten C9, C10, C16, C17, C22 vollstaendig"]
    zeilen, _ = ds.build_dataset(include_cl=True)

    saison_ok, saison_befunde, saison_bericht = c21.release_evidence(
        zeilen, artefakt, repo_root=repo_root)
    if not saison_ok:
        return {"status": "refused",
                "reason": "C21-Saisonfreigabe fehlt oder passt nicht: %s"
                          % saison_befunde[0],
                "findings": saison_befunde,
                "log": protokoll + ["C21-Saisonfreigabe: %d Befunde"
                                    % len(saison_befunde)]
                       + ["  ! %s" % b for b in saison_befunde],
                "wrote_anything": False}
    arten = {s: (v or {}).get("mode", "exact") for s, v in (
        saison_bericht.get("fold_comparisons") or {}).items()}
    if all(a == "exact" for a in arten.values()):
        protokoll.append("C21-Saisonfreigabe gebunden: Urteil accepted, "
                         "Foldmodelle %s bitgleich wieder gebaut"
                         % ", ".join(saison_bericht["fold_models"]))
    else:
        protokoll.append(
            "C21-Saisonfreigabe gebunden: Urteil accepted, Foldmodelle %s "
            "wieder gebaut (%s) - nicht bitgleich Gebautes bestaetigt die "
            "gespeicherte Foldreferenz unter dem eingefrorenen "
            "Aequivalenzvertrag"
            % (", ".join(saison_bericht["fold_models"]),
               ", ".join("%s: %s" % (s, a) for s, a in sorted(arten.items()))))
    # V2-C20: EINE Karte fuer Schaetzung, Messung und Bundle, und sie
    # reicht bis zur VORHERSAGESAISON. C19 begrenzte sie auf die letzte
    # Trainingssaison und verwechselte damit eine fehlende lokale
    # Ligadatei mit einer unbekannten Ligazugehoerigkeit.
    ligakarte, karte_diagnose = c20.production_map(
        ps_.DEFAULT_TRAINING_SEASONS)
    protokoll.append("Ligakarte: %d Vereine bis Saison %s, gelesen %s "
                     "(fp %s)"
                     % (karte_diagnose["teams"],
                        karte_diagnose["upto_season"],
                        karte_diagnose["seasons_used"],
                        karte_diagnose["map_fingerprint"][:16]))

    try:
        bundle, diagnose = build_final_bundle(
            zeilen, ligakarte, artefakt,
            map_upto_season=karte_diagnose["upto_season"],
            map_contract=c20)
    except ReleaseError as fehler:
        return {"status": "blocked_by_bundle_contract",
                "reason": str(fehler),
                "log": protokoll + [
                    "Bundlebau abgebrochen - fail-closed",
                    "Die Evaluation bleibt gueltig und accepted.",
                    "Die Registry wurde NICHT veraendert."]}
    protokoll.append("Bundle gebaut: %s" % bundle["model_id"])
    protokoll.append("  gamma=%s alpha=%s Ligen=%s Vereine=%s"
                     % (diagnose["gamma"], diagnose["league_alpha"],
                        diagnose["leagues"], diagnose["teams_mapped"]))

    # V2-C22: DAS GESPEICHERTE ARTEFAKT BLEIBT DAS ARTEFAKT.
    #
    # Baut dieser Prozess den Referenzkandidaten nicht bitgleich - etwa
    # weil exp() der C-Bibliothek oder der BLAS-Kern die letzten Stellen
    # anders rundet -, dann ist der Neubau ein NACHWEIS, kein Ersatz.
    # Er bestaetigt das gespeicherte, per SHA-256 gepinnte Bundle nur
    # unter dem eingefrorenen Aequivalenzvertrag; danach wird das
    # gespeicherte Bundle registriert, nie der Neubau. Ein nicht
    # aequivalenter Neubau wird verweigert, und er wird nie geschrieben.
    from src.ml import c22_release_equivalence as c22

    referenz_id = c22.reference_candidate()["model_id"]
    aequivalenz = None
    if expected_model_id and bundle["model_id"] != expected_model_id:
        if expected_model_id != referenz_id:
            return {"status": "refused",
                    "reason": ("gebaut wurde %s, erwartet war %s - hier "
                               "entsteht ein anderes Modell als das gemessene"
                               % (bundle["model_id"], expected_model_id)),
                    "log": protokoll + ["Stopkriterium Modell-ID verletzt"],
                    "model_id": bundle["model_id"], "wrote_anything": False}
        aequivalenz = _referenz_bestaetigen(bundle, zeilen, repo_root,
                                            linie_pruefen=False)
        if aequivalenz["refused"]:
            return {"status": "refused",
                    "reason": ("gebaut wurde %s, erwartet war %s - hier "
                               "entsteht ein anderes Modell als das gemessene "
                               "(%s)" % (bundle["model_id"], expected_model_id,
                                         aequivalenz["reason"])),
                    "log": protokoll + ["Stopkriterium Modell-ID verletzt: "
                                        "nicht bitgleich und nicht "
                                        "aequivalent"],
                    "bundle_comparison": aequivalenz["vergleich"],
                    "model_id": bundle["model_id"], "wrote_anything": False}
    elif (not expected_model_id and bundle["model_id"] != referenz_id
          and not os.path.isfile(base._pfad(repo_root, os.path.join(
              BUNDLE_DIR, "%s.json" % bundle["model_id"])))):
        aequivalenz = _referenz_bestaetigen(bundle, zeilen, repo_root,
                                            linie_pruefen=True)
        if aequivalenz["refused"]:
            return {"status": "refused",
                    "reason": ("der Neubau %s ist nicht bitgleich mit dem "
                               "autoritativen Bundle %s und nicht "
                               "aequivalent: %s"
                               % (bundle["model_id"], referenz_id,
                                  aequivalenz["reason"])),
                    "log": protokoll + ["Neubau weder bitgleich noch "
                                        "aequivalent - fail-closed"],
                    "bundle_comparison": aequivalenz["vergleich"],
                    "model_id": bundle["model_id"], "wrote_anything": False}
        if not aequivalenz["accepted"]:
            aequivalenz = None          # eine andere Linie: der bisherige Weg

    if aequivalenz is not None:
        vergleich = aequivalenz["vergleich"]
        protokoll.append(
            "Neubau %s ist nicht bitgleich mit %s; eingefrorener "
            "Aequivalenzvertrag %s: %s"
            % (vergleich["rebuilt_model_id"], vergleich["reference_model_id"],
               vergleich["equivalence"]["tolerance_contract_fingerprint"][:16],
               vergleich["equivalence"]["reason"]))
        protokoll.append("Das autoritative Bundle %s bleibt das Artefakt; "
                         "der Neubau wird weder geschrieben noch registriert"
                         % referenz_id)
        bundle = aequivalenz["bundle"]
        bundle_pfad = aequivalenz["pfad"]
        return _registrieren(bundle, bundle_pfad, urteil, artefakt, protokoll,
                             vergleich, saison_bericht, repo_root, dry_run)

    bundle_pfad = base._pfad(repo_root, os.path.join(
        BUNDLE_DIR, "%s.json" % bundle["model_id"]))
    # DAS BUNDLE IST EIN BAUARTEFAKT, KEINE ZUSTANDSAENDERUNG.
    #
    # Es wird auch im Trockenlauf geschrieben, und zwar aus einem
    # sachlichen Grund: Die Registryvalidierung prueft, dass die
    # Bundledatei existiert und ihr Hash stimmt. Ein Trockenlauf ohne
    # Datei koennte diese Pruefung gar nicht durchlaufen und waere
    # damit kein Trockenlauf der echten Freigabe, sondern eines
    # anderen, harmloseren Vorgangs.
    #
    # Der Dateiname enthaelt den Fingerabdruck beider Stufen. Ein
    # zweiter Lauf mit denselben Eingaben schreibt dieselbe Datei;
    # ein veraendertes Modell bekommt einen anderen Namen. Was der
    # Trockenlauf NICHT anfasst, ist die Registry und das
    # Releaseartefakt - also alles, was Wirkung hat.
    #
    # SEIT V2-C22: NICHT NUR DER NAME, AUCH DER INHALT.
    # Die Modell-ID deckt Koeffizienten, Daten, Messung und zweite Stufe
    # ab, aber nicht die Vertragsbindungen. Eine vorhandene Datei gleichen
    # Namens mit anderer Bindung wurde bis C21 unbesehen registriert. Jetzt
    # muss sie dem Neubau in jedem modellrelevanten Feld gleichen.
    vergleich = {"existing_file": os.path.isfile(bundle_pfad)}
    if not vergleich["existing_file"]:
        write_bundle(bundle, bundle_pfad)
        vergleich["mode"] = "written"
        protokoll.append("Bundle geschrieben und wieder geladen")
    else:
        try:
            with open(bundle_pfad, encoding="utf-8") as datei:
                vorhanden = json.load(datei)
        except (OSError, ValueError) as fehler:
            return {"status": "blocked_by_bundle_mismatch",
                    "reason": "die vorhandene Bundledatei ist unlesbar: %s"
                              % fehler,
                    "log": protokoll, "model_id": bundle["model_id"],
                    "wrote_anything": False}
        alle, modellrelevant = bundle_mismatch(vorhanden, bundle)
        vergleich.update({"differing_fields": alle,
                          "model_fields_differing": modellrelevant})
        if modellrelevant:
            return {"status": "blocked_by_bundle_mismatch",
                    "reason": ("die vorhandene Bundledatei weicht vom "
                               "Neubau in modellrelevanten Feldern ab: %s"
                               % ", ".join(modellrelevant[:5])),
                    "log": protokoll + [
                        "vorhandene Datei weicht ab - fail-closed, die "
                        "Registry wurde NICHT veraendert"],
                    "bundle_comparison": vergleich,
                    "model_id": bundle["model_id"], "wrote_anything": False}
        vergleich["mode"] = "exact"
        protokoll.append("Bundle lag bereits vor, inhaltsgleich mit dem "
                         "Neubau (abweichend nur Baumetadaten: %s)"
                         % (", ".join(alle) or "keine"))

    return _registrieren(bundle, bundle_pfad, urteil, artefakt, protokoll,
                         vergleich, saison_bericht, repo_root, dry_run)


def _registrieren(bundle, bundle_pfad, urteil, artefakt, protokoll,
                  vergleich, saison_bericht, repo_root, dry_run):
    """Registryeintrag bilden und anwenden - fuer beide Wege derselbe."""
    from src.ml import c20_temporal_map as c20

    relativ = os.path.join(BUNDLE_DIR,
                           "%s.json" % bundle["model_id"]).replace(
                               os.sep, "/")
    eintrag = _registry_eintrag(bundle, bundle_pfad, c20.EVALUATION_PATH)
    eintrag["bundle_path"] = relativ

    ergebnis = apply_release(urteil, eintrag, artefakt, relativ,
                             repo_root=repo_root, dry_run=dry_run)
    ergebnis["log"] = protokoll + ergebnis.get("log", [])
    ergebnis["bundle_comparison"] = vergleich
    ergebnis["season_evidence"] = saison_bericht
    return ergebnis


def _referenz_bestaetigen(neubau, zeilen, repo_root, linie_pruefen):
    """
    Der nicht bitgleiche Neubau gegen das gespeicherte Referenzbundle
    (V2-C22, eingefrorener Aequivalenzvertrag).

    `linie_pruefen`: Ohne erwartete Modell-ID gilt der Vertrag nur fuer
    die Linie des Referenzkandidaten (gleicher Kandidat, gleiche
    gebundene Evaluation). Ein Neubau einer anderen Linie - etwa nach
    einer neuen C20-Messung - geht den bisherigen Weg. Laesst sich die
    Linie nicht feststellen, weil das Referenzbundle fehlt oder sein
    Hash nicht stimmt, wird verweigert.

    Rueckgabe: {accepted, refused, reason, bundle, pfad, vergleich}.
    """
    from src.ml import c22_release_equivalence as c22

    gespeichert, pfad, befunde = c22.load_reference_candidate(repo_root)
    vergleich = {"existing_file": gespeichert is not None,
                 "mode": c22.MODE_REFUSED,
                 "reference_model_id": c22.reference_candidate()["model_id"],
                 "rebuilt_model_id": neubau.get("model_id"),
                 "differing_fields": [], "model_fields_differing": [],
                 "tolerated_fields": [], "derived_identity_fields": [],
                 "equivalence": None}
    ergebnis = {"accepted": False, "refused": True, "reason": None,
                "bundle": None, "pfad": pfad, "vergleich": vergleich}
    if befunde:
        ergebnis["reason"] = befunde[0]
        return ergebnis
    if linie_pruefen and not c22.same_lineage(gespeichert, neubau):
        ergebnis.update(refused=False, reason="eine andere Linie")
        return ergebnis

    bericht = c22.compare_bundles(gespeichert, neubau, zeilen)
    vergleich.update({
        "mode": bericht["mode"],
        "differing_fields": bericht["differing_fields"],
        "model_fields_differing": (bericht["structural_mismatches"]
                                   + bericht["numerical_mismatches"]),
        "tolerated_fields": bericht["tolerated_fields"],
        "derived_identity_fields": bericht["derived_identity"],
        "equivalence": bericht,
    })
    if not bericht["equivalent"]:
        ergebnis["reason"] = bericht["reason"]
        return ergebnis
    ergebnis.update(accepted=True, refused=False, reason=bericht["reason"],
                    bundle=gespeichert)
    return ergebnis
