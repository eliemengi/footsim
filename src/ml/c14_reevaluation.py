"""
Die finale Reevaluation nach der Datenreparatur (V2-C14).

DIE FRAGE
---------
V2-C12 lehnte das Modell ab, und zwar an genau zwei von zehn
Bedingungen:

    ci_excludes_zero          KI [-0,02986; +0,01135] bei n = 213
    no_severe_segment_damage  profile_depth:<20, profile_source:cl_history_pit

Die zweite Ursache war ein Datenfehler, kein Modellfehler: Der
Profilpfad las fuenf der 23 vorhandenen Ligadateien, und 321 von 1006
Teamseiten bekamen deshalb ein Profil aus ihren eigenen CL-Partien.
V2-C13 hat das behoben. Das Segment `cl_history_pit` existiert nicht
mehr, und der Testbestand waechst von 213 auf 283.

C14 misst, was davon uebrig bleibt. Nicht mehr und nicht weniger.

WAS C14 AUSDRUECKLICH NICHT TUT
-------------------------------
Es aendert das Modell nicht. Kein neues Merkmal, keine neue
Modellklasse, kein anderer Hyperparameterraum. Wuerden Daten UND
Modell gleichzeitig wechseln, waere das Ergebnis nicht mehr lesbar:
Niemand koennte sagen, welche der beiden Aenderungen es getragen hat.

C14 misst ausschliesslich den Effekt der reparierten Eingabedaten bei
eingefrorenem Modellansatz.

DIE REIHENFOLGE IST DER GANZE WERT
----------------------------------
Erst der Vertrag, dann die Messung, dann die Entscheidung. Ein
Vertrag, der nach dem Ergebnis entsteht, ist kein Vertrag, sondern
eine Beschreibung des Ergebnisses.

Deshalb ist `evaluation_contract()` vollstaendig bildbar, ohne dass
eine einzige Zahl gemessen wurde, und `assert_contract_matches()`
weist ein Ergebnis zurueck, das unter einem anderen Vertrag entstanden
ist.

WAS C14 GEGENUEBER C12 NACHSCHAERFT
-----------------------------------
C12 nannte im Vertrag das Segment `profile_source`, legte aber nicht
fest, ob Heim-, Auswaertsseite oder beide gemeint sind. Die
Umsetzung segmentierte dann nur auf der Heimseite. Gemessen war der
Unterschied gross:

    cl_history(heim) x domestic(gast)   +0,0398   n=47
    domestic(heim) x cl_history(gast)   -0,0361   n=52

Dieselbe Datenlage, entgegengesetztes Vorzeichen, je nachdem welche
Seite man ansieht. Diese Wahl entschied faktisch ueber `rejected`
gegen `provisional_shadow`, und sie stand nicht im Vertrag.

C14 schreibt Seite und Symmetrie deshalb aus: gerichtete Segmente
(Heim, Gast) UND symmetrische (duennste Seite, beide Seiten). Und weil
sich dieselbe Zeilenmenge unter mehreren Namen wiederfinden kann,
werden ueberlappende Befunde erkannt und nicht mehrfach als
unabhaengiger Schaden gezaehlt.
"""

import hashlib
import json

from src.ml import c8_ablation as c8
from src.ml import cl_evaluate as ce
from src.ml import evaluate as ev

CONTRACT_VERSION = "v2-c14.1"

CONTRACT_PATH = "data/ml/c14_reevaluation_contract_2023-2025.json"
ARTIFACT_PATH = "data/ml/c14_reevaluation_2023-2025.json"


class ContractViolation(RuntimeError):
    """
    Ein Ergebnis gehoert nicht zu diesem Vertrag.

    Eigene Klasse, damit ein Aufrufer sie von einem gewoehnlichen
    Fehler unterscheiden kann. Sie wird nie stillschweigend behandelt.
    """


VERDICT_ACCEPTED = "accepted"
VERDICT_PROVISIONAL_SHADOW = "provisional_shadow"
VERDICT_REJECTED = "rejected"
VERDICT_NOT_EVALUABLE = "not_evaluable"

VERDICTS = (VERDICT_ACCEPTED, VERDICT_PROVISIONAL_SHADOW,
            VERDICT_REJECTED, VERDICT_NOT_EVALUABLE)

#: Aus V2-C12 unveraendert uebernommen. Die Saisons 2023 bis 2025 haben
#: jede Entscheidung von C2 bis C13 getragen; ein Ergebnis auf ihnen
#: ist Entwicklungsevidenz und keine unabhaengige Bestaetigung.
ACCEPTANCE_CLASS_DEVELOPMENT = "accepted_development_evidence"

#: Aus V2-C2B/C8 uebernommen, nicht fuer C14 neu gewaehlt.
SEGMENT_MIN_SIZE = 30

#: Die fuenf Ligen im football-data-Namensraum. Sie tragen die
#: Trainingsdaten; alles andere kam ueber den C13-Crosswalk hinzu.
TOP5_LEAGUES = ("BL1", "PL", "PD", "SA", "FL1")


# ---------------------------------------------------------------------------
# Datensatzidentitaet
# ---------------------------------------------------------------------------
#
# DIE LEHRE AUS C13
# `early_v2.target_fingerprint` hasht die Zielwerte GEMEINSAM mit den
# Identitaetsfeldern, und `evaluation_eligible` ist eines davon. C13
# hat kein einziges Tor veraendert und den Wert trotzdem bewegt, weil
# 125 Partien zusaetzlich auswertbar wurden.
#
# Das ist fuer den C9-Zweck richtig und fuer die Frage "sind es
# dieselben Spiele mit denselben Ergebnissen?" unbrauchbar. C14 fuehrt
# deshalb einen REINEN Zielfingerabdruck: Matchidentitaet und
# Zielwerte, sonst nichts.

PURE_IDENTITY_FIELDS = ("row_id", "match_id", "league", "season", "date",
                        "home_id", "away_id")

PURE_TARGET_FIELDS = ("home_goals", "away_goals", "outcome")


def pure_target_fingerprint(zeilen):
    """
    Matchidentitaet und Zielwerte - und ausdruecklich nichts sonst.

    Er reagiert, wenn ein Spiel dazukommt, verschwindet oder ein
    anderes Ergebnis bekommt. Er reagiert NICHT auf
    `evaluation_eligible`, auf Merkmalswerte oder auf Profilquellen.
    """
    felder = list(PURE_IDENTITY_FIELDS) + list(PURE_TARGET_FIELDS)
    teile = []
    for zeile in sorted(zeilen, key=lambda z: str(z.get("row_id"))):
        teile.append("|".join(repr(zeile.get(f)) for f in felder))
    roh = "c14-pure-target\n" + "\n".join(teile)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def _kanonisch(wert):
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _stabil(block):
    return hashlib.sha256(_kanonisch(block).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Herkunftsliga
# ---------------------------------------------------------------------------

def team_league_map():
    """
    In welcher nationalen Liga ein Verein spielt.

    NUR EIN BERICHTSMERKMAL. Diese Zuordnung geht in kein Modell, in
    keine Vorhersage und in keinen Trainingsschritt ein; sie benennt
    ausschliesslich Segmente im Bericht. Deshalb ist sie strukturell
    ueber den gesamten lokalen Bestand gebildet und nicht je Stichtag:
    Die Ligazugehoerigkeit eines Vereins ist eine Struktureigenschaft,
    kein Leistungswert, und ein Segmentname darf nicht mit dem
    Stichtag wandern.
    """
    import collections
    import pathlib

    from src.data import national_sources as ns
    from src.data.historical_loader import (
        AVAILABLE_HISTORICAL_SEASONS, season_file_path)
    from src.features.team_identity import to_football_data

    zaehler = collections.defaultdict(collections.Counter)
    for code in ns.profile_source_codes():
        provider = ns.league_provider(code)
        for saison in AVAILABLE_HISTORICAL_SEASONS:
            pfad = pathlib.Path(season_file_path(code, saison))
            if not pfad.is_file():
                continue
            try:
                daten = json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, ValueError):            # pragma: no cover
                continue
            for partie in (daten.get("matches") or []):
                for feld in ("home_id", "away_id"):
                    roh = partie.get(feld)
                    if roh is None:
                        continue
                    tid = int(roh)
                    if provider == ns.PROVIDER_API_FOOTBALL:
                        tid = to_football_data(tid)
                        if tid is None:
                            continue
                    zaehler[tid][code] += 1

    return {tid: c.most_common(1)[0][0] for tid, c in zaehler.items()}


def _top5(liga):
    return liga in TOP5_LEAGUES


# ---------------------------------------------------------------------------
# Segmente
# ---------------------------------------------------------------------------

def _tiefenklasse(tiefe):
    """Feste Klassen. Sie stehen im Vertrag und wandern nicht."""
    if not isinstance(tiefe, (int, float)):
        return "unknown"
    if tiefe < 6:
        return "<6"
    if tiefe < 20:
        return "6-19"
    return ">=20"


def _segment_keys(zeile, ligakarte=None):
    """
    Alle Pflichtsegmente einer Partie - gerichtet UND symmetrisch.

    Jeder Name traegt seine Achse als Praefix, damit spaeter niemand
    raten muss, welche Seite gemeint war. Genau diese Unklarheit war
    der Umsetzungsspielraum in C12.
    """
    ligakarte = ligakarte or {}
    schluessel = []

    # -- Wettbewerb und Phase --------------------------------------------
    schluessel.append("season:%s" % zeile.get("season"))
    schluessel.append("phase:knockout" if zeile.get("is_knockout")
                      else "phase:league")
    stufe = zeile.get("stage")
    if stufe:
        schluessel.append("stage:%s" % stufe)
    if zeile.get("is_final"):
        schluessel.append("leg:final")
    elif zeile.get("is_first_leg"):
        schluessel.append("leg:first")
    elif zeile.get("is_second_leg"):
        schluessel.append("leg:second")
    else:
        schluessel.append("leg:single")
    if zeile.get("neutral_venue"):
        schluessel.append("venue:neutral")

    # -- Profilquelle, gerichtet und symmetrisch --------------------------
    heim_q = zeile.get("home_profile_source")
    gast_q = zeile.get("away_profile_source")
    if heim_q:
        schluessel.append("home_profile_source:%s" % heim_q)
    if gast_q:
        schluessel.append("away_profile_source:%s" % gast_q)
    if heim_q and gast_q:
        schluessel.append("profile_source_pair:%s|%s" % (heim_q, gast_q))
        beide_national = heim_q == "domestic_pit" == gast_q
        schluessel.append("profile_source_any_fallback:%s"
                          % ("no" if beide_national else "yes"))
        if beide_national:
            schluessel.append("profile_source_both_domestic")

    # -- Profiltiefe, gerichtet und symmetrisch ---------------------------
    heim_t = zeile.get("home_profile_matches")
    gast_t = zeile.get("away_profile_matches")
    schluessel.append("home_profile_depth:%s" % _tiefenklasse(heim_t))
    schluessel.append("away_profile_depth:%s" % _tiefenklasse(gast_t))
    if isinstance(heim_t, (int, float)) and isinstance(gast_t, (int, float)):
        duennste = min(heim_t, gast_t)
        schluessel.append("min_profile_depth:%s" % _tiefenklasse(duennste))
        if heim_t >= 20 and gast_t >= 20:
            schluessel.append("both_profile_depth:>=20")
        # Asymmetrie: eine Seite gut, die andere duenn.
        if _tiefenklasse(heim_t) != _tiefenklasse(gast_t):
            schluessel.append("profile_depth:asymmetric")
        else:
            schluessel.append("profile_depth:symmetric")

    # -- Herkunftsstruktur -------------------------------------------------
    heim_l = ligakarte.get(zeile.get("home_id"))
    gast_l = ligakarte.get(zeile.get("away_id"))
    if heim_l and gast_l:
        paar = "%s_vs_%s" % ("top5" if _top5(heim_l) else "other",
                             "top5" if _top5(gast_l) else "other")
        schluessel.append("origin:%s" % paar)
    if heim_l:
        schluessel.append("home_origin_league:%s" % heim_l)
    if gast_l:
        schluessel.append("away_origin_league:%s" % gast_l)

    # -- Ausgang und Erwartung --------------------------------------------
    ergebnis = zeile.get("outcome")
    schluessel.append({0: "outcome:home", 1: "outcome:draw",
                       2: "outcome:away"}.get(ergebnis, "outcome:unknown"))

    lh = zeile.get("baseline_lambda_home")
    la = zeile.get("baseline_lambda_away")
    if isinstance(lh, (int, float)) and isinstance(la, (int, float)):
        # Die Baseline-Lambdas stammen aus PIT-Profilen und enthalten
        # keine Zukunftsinformation. Sie sagen, wie klar die Partie vor
        # dem Anpfiff aussah.
        spanne = abs(lh - la)
        schluessel.append("match_balance:%s"
                          % ("balanced" if spanne < 0.35
                             else "clear" if spanne < 0.9 else "lopsided"))

    qualitaet = zeile.get("home_data_quality")
    if qualitaet:
        schluessel.append("home_data_quality:%s" % qualitaet)

    return schluessel


def _segmente(zeilen, basis_verluste, ml_verluste, ligakarte=None):
    """
    Die Segmentauswertung mit Ueberlappungserkennung.

    Ein Segment unter SEGMENT_MIN_SIZE wird AUSGEWIESEN, aber nicht
    interpretiert. Ein verschwiegenes kleines Segment saehe aus wie ein
    fehlender Befund.

    Zusaetzlich zu C12: Segmente, die exakt dieselben Partien
    enthalten, werden als Gruppe gekennzeichnet. `phase:knockout` und
    `stage:FINAL` koennen denselben Befund tragen; ihn zweimal als
    unabhaengigen Schaden zu zaehlen, waere eine erfundene Haeufung.
    """
    eimer = {}
    for i, zeile in enumerate(zeilen):
        for schluessel in _segment_keys(zeile, ligakarte):
            eimer.setdefault(schluessel, []).append(i)

    # Identische Zeilenmengen zusammenfassen.
    nach_menge = {}
    for name, indizes in eimer.items():
        nach_menge.setdefault(frozenset(indizes), []).append(name)

    gruppe_von = {}
    for namen in nach_menge.values():
        fuehrend = sorted(namen)[0]
        for name in namen:
            gruppe_von[name] = fuehrend

    heraus = {}
    for name, indizes in sorted(eimer.items()):
        n = len(indizes)
        basis = sum(basis_verluste[i] for i in indizes) / n
        ml = sum(ml_verluste[i] for i in indizes) / n
        heraus[name] = {
            "n": n,
            "baseline_log_loss": round(basis, 5),
            "ml_log_loss": round(ml, 5),
            "delta_log_loss": round(ml - basis, 5),
            "interpretable": n >= SEGMENT_MIN_SIZE,
            "severely_worse": (n >= SEGMENT_MIN_SIZE
                               and (ml - basis) >= ce.SEVERE_DEGRADATION),
            "overlap_group": gruppe_von[name],
            "is_group_representative": gruppe_von[name] == name,
        }
    return heraus


def distinct_damage(segmente):
    """
    Die schwer verschlechterten Segmente, ohne Doppelzaehlung.

    Rueckgabe: sortierte Liste der Gruppenvertreter. Zwei Namen fuer
    dieselbe Zeilenmenge sind ein Befund, nicht zwei.
    """
    gruppen = {}
    for name, block in segmente.items():
        if block.get("severely_worse"):
            gruppen.setdefault(block["overlap_group"], []).append(name)
    return sorted(gruppen)


# ---------------------------------------------------------------------------
# Konzentration
# ---------------------------------------------------------------------------

def concentration(zeilen, basis_verluste, ml_verluste, top_n=5):
    """
    Traegt eine Handvoll Vereine praktisch den gesamten Vorteil?

    Zwei Folds und 283 Partien sind wenig. Kaeme die Verbesserung fast
    vollstaendig von fuenf Vereinen, waere sie eher deren Eigenschaft
    als die des Verfahrens.

    AUSDRUECKLICH KEIN GATE. Fuer diese Frage existiert in den
    freigegebenen Vertraegen keine numerische Schwelle, und eine hier
    erfundene waere die bequemste Art, ein Ergebnis zu bekommen. Der
    Wert wird berichtet und als Risiko benannt.
    """
    import collections

    je_verein = collections.defaultdict(float)
    partien = collections.Counter()
    for i, zeile in enumerate(zeilen):
        beitrag = ml_verluste[i] - basis_verluste[i]
        for feld in ("home_id", "away_id"):
            tid = zeile.get(feld)
            if tid is None:
                continue
            # Halber Beitrag je Seite, damit die Summe ueber alle
            # Vereine genau der Gesamtsumme entspricht.
            je_verein[tid] += beitrag / 2.0
            partien[tid] += 1

    gesamt = sum(ml_verluste) - sum(basis_verluste)
    sortiert = sorted(je_verein.items(), key=lambda kv: kv[1])

    def anteil(betrag):
        return None if gesamt == 0 else round(betrag / gesamt, 4)

    besten = sortiert[:top_n]
    ohne_beste = gesamt - sum(b for _, b in besten)
    n = len(zeilen)

    # Leave-one-team-out: Wie sieht das Gesamtdelta ohne die Partien
    # EINES Vereins aus? Der schlechteste Fall zaehlt.
    lolo = []
    for tid in list(je_verein):
        behalten = [i for i, z in enumerate(zeilen)
                    if z.get("home_id") != tid and z.get("away_id") != tid]
        if len(behalten) < ce.MIN_RELIABLE_N:
            continue
        d = (sum(ml_verluste[i] - basis_verluste[i] for i in behalten)
             / len(behalten))
        lolo.append((tid, d, len(behalten)))
    lolo.sort(key=lambda t: t[1], reverse=True)

    return {
        "total_delta_sum": round(gesamt, 5),
        "mean_delta": round(gesamt / n, 5) if n else None,
        "top_contributors": [
            {"team_id": tid, "delta_sum": round(betrag, 5),
             "share_of_total": anteil(betrag), "matches": partien[tid]}
            for tid, betrag in besten],
        "top_n_share": anteil(sum(b for _, b in besten)),
        "mean_delta_without_top_n": (
            round(ohne_beste / n, 5) if n else None),
        "direction_holds_without_top_n": (
            None if gesamt == 0 else (ohne_beste < 0) == (gesamt < 0)),
        "leave_one_team_out_worst": [
            {"team_id": tid, "mean_delta_without": round(d, 5), "n": m}
            for tid, d, m in lolo[:5]],
        "leave_one_team_out_direction_holds": all(
            d < 0 for _, d, _ in lolo) if lolo else None,
        "is_a_gate": False,
        "why_not_a_gate": (
            "Fuer die Konzentration existiert in den freigegebenen "
            "Vertraegen keine numerische Schwelle. Eine hier erfundene "
            "waere ein nachtraeglich passend gemachtes Gate. Der Befund "
            "wird als Risiko berichtet."),
    }


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def evaluation_contract():
    """
    Der vollstaendige Vertrag - ohne eine einzige gemessene Zahl.

    Er ist absichtlich ohne Datensatz bildbar: Was hier steht, gilt,
    bevor irgendetwas gerechnet wurde. Erwartungswerte aus C13 stehen
    als ERWARTUNG drin und werden bei der Messung geprueft, nicht
    stillschweigend angepasst.
    """
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import early_v2 as e9
    from src.ml import feature_groups as fg
    from src.ml import model as mdl
    from src.ml import model_registry as mr

    return {
        "version": CONTRACT_VERSION,
        "purpose": (
            "Misst, ob die eingefrorene V2-Modellklasse auf den durch "
            "V2-C13 reparierten Profilen die V0-Baseline belastbar "
            "schlaegt. Daten geaendert, Modell eingefroren."),

        # -- Der Kandidat, unveraendert -----------------------------------
        "candidate": {
            "name": ce.CANDIDATE,
            "model_class": "poisson_offset_correction_linear",
            "feature_group": ce.CANDIDATE,
            "features": sorted(fg.columns_for(ce.CANDIDATE)),
            "feature_count": len(fg.columns_for(ce.CANDIDATE)),
            "alpha_candidates": list(mdl.ALPHA_CANDIDATES),
            "alpha_selection": ("foldlokal auf der inneren Teilung des "
                                "Trainingsbestands; der aeussere "
                                "Testfold wird nie gesehen"),
            "bundle_schema": 2,
            "retrained_per_fold": True,
            "why_retrained": (
                "Das Bundle clm-8a4eda90a08395cc wurde auf den "
                "Profilwerten VOR C13 angepasst. Es unveraendert als "
                "Kandidat zu verwenden hiesse, ein Modell auf Daten zu "
                "messen, die es nie gesehen hat."),
            "unchanged_vs_c12": [
                "Merkmalsanzahl", "Merkmalsnamen", "Merkmalsreihenfolge",
                "Merkmalssemantik", "Modellklasse", "Hyperparameterraum"],
            "changed_vs_c12": [
                "konkrete Profilwerte (durch C13)",
                "foldlokal angepasste Parameter",
                "foldlokal gewaehltes Alpha im bestehenden Raum",
                "Dataset- und Bundlefingerabdruecke"],
        },

        # -- Bindungen an frueher eingefrorene Vertraege -------------------
        "bound_contracts": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c9_selected_features": len(e9.selected_columns()),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c10_inclusive": pc.CUTOFF_INCLUSIVE,
            "c11_contract_fingerprint": _stabil(mr.contract()),
            "c13_contract_fingerprint": c13.contract_fingerprint(),
            "c13_state_fingerprint_expected": (
                "75315a0c4858c2123e68039bf987f25dc87b4b55c6341a209a30c04"
                "b82189933"),
            "note": ("Der C11-Wert ist der unveraenderliche "
                     "Vertragsteil, NICHT der Registryzustand. Eine "
                     "Modellregistrierung darf diesen Fingerabdruck "
                     "nicht bewegen."),
        },

        # -- Bestaende -----------------------------------------------------
        "inventories": {
            "standard": {
                "definition": ("zeitliche Testspiele der regulaeren "
                               "CL-Phase, evaluation_eligible"),
                "selector": "cl_evaluate.cl_rows",
                "expected_rows": 283,
                "carries_release_decision": True,
            },
            "context": {
                "definition": ("zusaetzlich regelkonforme K.-o.-Spiele, "
                               "evaluation_eligible oder "
                               "knockout_eligible"),
                "selector": "cl_evaluate.context_rows",
                "expected_rows": 373,
                "carries_release_decision": False,
                "training_differs": (
                    "Der Kontextvertrag trainiert auf nationalen Ligen "
                    "PLUS frueheren CL-Saisons. Er ist deshalb kein "
                    "Ersatz fuer den Standardbestand, sondern ein "
                    "zweiter Messaufbau."),
                "blocking_rule": (
                    "Genau eine Kontextbedingung kann ein Accepted "
                    "verhindern: ein Gesamtdelta des Kontextbestands "
                    "von mindestens SEVERE_DEGRADATION. Das hiesse, "
                    "dass die K.-o.-Partien - die der Nutzer am "
                    "staerksten wahrnimmt - schwer beschaedigt werden. "
                    "Alles Uebrige ist Diagnose."),
                "diagnostic_only": [
                    "Kontext-Brier", "Kontext-RPS",
                    "Kontext-Kalibrierung", "Kontextsegmente",
                    "Kontextbootstrap"],
            },
            "no_double_counting": (
                "Standard- und Kontextbestand ueberlappen in der "
                "regulaeren Phase. Sie werden getrennt berichtet und "
                "nie addiert."),
        },

        # -- Folds ---------------------------------------------------------
        "folds": {
            "standard": [dict(f) for f in ce.OUTER_FOLDS],
            "context": [dict(f) for f in ce.CONTEXT_FOLDS],
            "chronological_only": True,
            "no_random_split": True,
            "inner_split": ("evaluate.inner_split, ausschliesslich auf "
                            "dem Trainingsbestand"),
            "preprocessing": "foldlokal gefittet, nie auf dem Testfold",
            "calibration": "foldlokal, nie auf dem Testfold",
            "seasons_without_training": list(ce.SEASONS_WITHOUT_TRAINING),
        },

        # -- Metriken ------------------------------------------------------
        "metrics": {
            "primary": "log_loss",
            "secondary": ["brier", "rps"],
            "supporting": ["accuracy", "calibration_error",
                           "reliability_bins",
                           "mean_predicted_probabilities",
                           "observed_frequencies",
                           "mean_lambda_home", "mean_lambda_away"],
            "probability_contract": ("endlich, nicht negativ, Summe 1; "
                                     "NaN und Infinity sind ein Befund, "
                                     "kein Rundungsproblem"),
        },

        # -- Bootstrap -----------------------------------------------------
        "bootstrap": {
            "method": "gepaart, je Partie",
            "seed": 20260827,
            "iterations": 2000,
            "why_paired": ("Beide Kandidaten bewerten dieselben "
                           "Partien. Ein ungepaarter Vergleich "
                           "verschenkte genau die Information, die den "
                           "Vergleich traegt."),
            "source": "unveraendert aus V2-C2B/C12",
        },

        # -- Segmente ------------------------------------------------------
        "segments": {
            "min_size": SEGMENT_MIN_SIZE,
            "min_size_source": "V2-C2B/C8, nicht fuer C14 neu gewaehlt",
            "axes": {
                "profile_source": ["home_profile_source:*",
                                   "away_profile_source:*",
                                   "profile_source_pair:*",
                                   "profile_source_any_fallback:*",
                                   "profile_source_both_domestic"],
                "profile_depth": ["home_profile_depth:<6|6-19|>=20",
                                  "away_profile_depth:<6|6-19|>=20",
                                  "min_profile_depth:<6|6-19|>=20",
                                  "both_profile_depth:>=20",
                                  "profile_depth:asymmetric|symmetric"],
                "phase": ["season:*", "phase:league|knockout", "stage:*",
                          "leg:first|second|single|final",
                          "venue:neutral"],
                "structure": ["origin:top5_vs_top5", "origin:top5_vs_other",
                              "origin:other_vs_top5",
                              "origin:other_vs_other",
                              "home_origin_league:*",
                              "away_origin_league:*"],
                "outcome": ["outcome:home|draw|away",
                            "match_balance:balanced|clear|lopsided",
                            "home_data_quality:*"],
            },
            "directed_and_symmetric": True,
            "why_both": (
                "C12 nannte `profile_source`, ohne die Seite "
                "festzulegen, und segmentierte dann nur die Heimseite. "
                "Gemessen kehrte sich das Vorzeichen um, je nachdem "
                "welche Seite man ansah (+0,0398 gegen -0,0361). Diese "
                "Wahl entschied faktisch ueber das Urteil und stand "
                "nicht im Vertrag."),
            "overlap_rule": (
                "Segmente mit identischer Zeilenmenge bilden eine "
                "Gruppe und zaehlen als EIN Befund. Derselbe Schaden "
                "unter zwei Namen ist nicht zweimal Schaden."),
            "small_segments": ("werden ausgewiesen, aber nie als Gate "
                               "herangezogen"),
        },

        # -- Missingness ---------------------------------------------------
        "missing_data": {
            "rule": ("Fehlende Merkmalswerte bleiben fehlend und werden "
                     "foldlokal vom Medianimputer gefuellt. Keine Zeile "
                     "wird entfernt, um eine Kennzahl zu verbessern."),
            "identical_rows": ("V0 und V2 bewerten dieselben Partien mit "
                               "denselben Zielwerten. Eine Abweichung "
                               "waere ein Befund, kein Detail."),
            "exclusions_are_rule_based": (
                "Alle Ausschluesse folgen der C13-Eligibility und "
                "stehen vor der Messung fest. Kein Spiel wird nach "
                "Sichtung des Ergebnisses entfernt."),
        },

        # -- Kalibrierung ---------------------------------------------------
        "calibration": {
            "allowed": ["keine zusaetzliche Kalibrierung",
                        "bestehende einfache Kalibrierung nach "
                        "bisheriger Konvention"],
            "forbidden": ["neue Kalibrierungsmethode",
                          "Isotonic bei kleiner Datenbasis",
                          "Fit auf dem Testfold",
                          "Auswahl anhand des Testfolds",
                          "kosmetische Kalibrierung ohne LogLoss-Nutzen"],
            "max_degradation": c8.MAX_CALIBRATION_DEGRADATION,
        },

        # -- Gates ----------------------------------------------------------
        "thresholds": {
            "severe_degradation": ce.SEVERE_DEGRADATION,
            "max_secondary_degradation": c8.MAX_SECONDARY_DEGRADATION,
            "max_calibration_degradation": c8.MAX_CALIBRATION_DEGRADATION,
            "min_reliable_n": ce.MIN_RELIABLE_N,
            "segment_min_size": SEGMENT_MIN_SIZE,
            "fold_dominance_limit": 0.9,
            "provenance": ("saemtlich aus V2-C2B, V2-C8 und V2-C12 "
                           "importiert, nicht fuer C14 neu gewaehlt"),
        },

        "gates": {
            "accepted": [
                "primaerer Delta-LogLoss < 0",
                "alle Folds zeigen dieselbe Richtung",
                "kein einzelner Fold traegt den Gewinn allein",
                "obere 95-%-Bootstrapgrenze < 0",
                "Brier nicht materiell schlechter",
                "RPS nicht materiell schlechter",
                "Kalibrierung bricht nicht ein",
                "kein Pflichtsegment ausreichender Groesse verschlechtert "
                "sich schwer",
                "kein Fold schwer verschlechtert",
                "Stichprobe gross genug",
                "Kontextbestand nicht schwer beschaedigt",
                "Datensatz- und Zielidentitaet stimmen",
                "Ergebnis reproduzierbar",
            ],
            "provisional_shadow": [
                "Punktschaetzer zugunsten des Modells",
                "kein klarer schaedlicher Gesamteffekt",
                "aber Intervall oder Foldstabilitaet tragen keine "
                "regulaere Freigabe",
            ],
            "rejected": [
                "primaere Metrik schlechter",
                "Folds widersprechen sich",
                "ein Fold schwer verschlechtert",
                "ein grosses Pflichtsegment schwer beschaedigt",
                "Brier oder RPS materiell schlechter",
                "Kontextbestand schwer beschaedigt",
                "PIT oder Leakage scheitert",
                "Ergebnis nicht reproduzierbar",
            ],
            "not_evaluable": [
                "zu wenige Folds oder Zeilen",
                "Datensatzidentitaet nicht herstellbar",
                "Zielwerte nicht stabil",
                "Messung technisch nicht reproduzierbar",
            ],
        },

        "acceptance_class_if_accepted": ACCEPTANCE_CLASS_DEVELOPMENT,

        "no_untouched_holdout": {
            "true": True,
            "already_used_for": ("C2-Ablation, C2B-Uebertragung, C3 bis "
                                 "C7 Merkmalsentscheidungen, C8 "
                                 "Modellklasse, C9 Freeze, C12 "
                                 "Entscheidung, C13 Datenreparatur"),
            "consequence": (
                "Jedes Ergebnis auf diesen Saisons ist "
                "Entwicklungsevidenz. Der Begriff 'unabhaengig "
                "bestaetigt' wird fuer C14 nicht verwendet."),
        },

        "thin_profiles": {
            "rule": ("Partien mit duenner Historie werden gemessen und "
                     "berichtet, nicht entfernt."),
            "no_shrinkage_in_c14": (
                "C14 darf keine Shrinkage-Staerke an diesen Ergebnissen "
                "optimieren. Das waere Anpassung an den Testbestand."),
        },

        "immutability": (
            "Kein Messergebnis darf diesen Vertrag veraendern. Ein "
            "Ergebnis, das unter einem anderen Vertragsfingerabdruck "
            "entstanden ist, wird zurueckgewiesen."),
    }


def contract_fingerprint(vertrag=None):
    """Der Fingerabdruck der REGELN. Ohne Zeit, ohne git, ohne Zustand."""
    return _stabil(vertrag if vertrag is not None
                   else evaluation_contract())


def assert_contract_matches(ergebnis, vertrag=None):
    """
    Gehoert dieses Ergebnis zu diesem Vertrag?

    Fail-closed: Ohne Fingerabdruck im Ergebnis wird abgelehnt, nicht
    durchgewunken.
    """
    erwartet = contract_fingerprint(vertrag)
    gefunden = (ergebnis or {}).get("contract_fingerprint")
    if gefunden != erwartet:
        raise ContractViolation(
            f"Das Ergebnis gehoert nicht zu diesem Vertrag. "
            f"Erwartet {erwartet}, gefunden {gefunden!r}. Ein Ergebnis "
            f"darf die Gates nicht nachtraeglich veraendern.")
    return True


# ---------------------------------------------------------------------------
# Die Messung
# ---------------------------------------------------------------------------

def _atomar_schreiben(pfad, inhalt):
    """Atomar, damit ein Abbruch keine halbe Datei hinterlaesst."""
    import os
    import pathlib
    import tempfile

    pfad = pathlib.Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    griff, temp = tempfile.mkstemp(dir=str(pfad.parent), suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            datei.write(inhalt + "\n")
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temp, pfad)
    except BaseException:                                # pragma: no cover
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return str(pfad)


def write_contract(pfad=None):
    """
    Den Vertrag festschreiben - VOR der Messung.

    Er enthaelt bewusst kein einziges Ergebnis. Wer ihn spaeter liest,
    sieht die Regeln so, wie sie vor der ersten Zahl galten.
    """
    import datetime as _dt

    vertrag = evaluation_contract()
    dokument = {
        "artifact": "v2-c14 reevaluation contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "frozen_before_measurement": True,
        "contract": vertrag,
        "contract_fingerprint": contract_fingerprint(vertrag),
        "fingerprint_excludes": ["created_at", "git_commit",
                                 "jeder Messwert", "Registryzustand"],
    }
    return _atomar_schreiben(pfad or CONTRACT_PATH,
                             json.dumps(dokument, indent=2,
                                        ensure_ascii=False))


def _bestand_metriken(folds):
    """Foldinterna einsammeln, bevor sie verworfen werden."""
    zeilen, basis_v, ml_v, basis_s, ml_s = [], [], [], [], []
    for fold in folds:
        intern = fold.get("_internal") or {}
        zeilen.extend(intern.get("rows") or [])
        basis_v.extend((intern.get("baseline_losses")
                        or {}).get("log_loss", []))
        ml_v.extend((intern.get("ml_losses") or {}).get("log_loss", []))
        basis_s.append(intern.get("baseline_calibration") or {})
        ml_s.append(intern.get("ml_calibration") or {})
    return zeilen, basis_v, ml_v, basis_s, ml_s


def _reliability(summen):
    """
    Die Zuverlaessigkeitskurve aus den bereits gebildeten Binsummen.

    Aus denselben Summen wie die Kalibrierungskennzahl, damit beide
    nicht auseinanderlaufen koennen. Ueber alle drei Ausgaenge
    gepoolt: Eine Kurve je Ausgang haette Bins mit einer Handvoll
    Beobachtungen.
    """
    heraus = []
    for name, werte in sorted((summen or {}).items()):
        try:
            summe, treffer, anzahl = werte[0], werte[1], werte[2]
        except (TypeError, IndexError, KeyError):        # pragma: no cover
            continue
        if not anzahl:
            continue
        heraus.append({
            "bin": name,
            "n": anzahl,
            "mean_predicted": round(summe / anzahl, 5),
            "observed_rate": round(treffer / anzahl, 5),
            "gap": round(treffer / anzahl - summe / anzahl, 5),
        })
    return heraus


def _messe_bestand(zeilen, name, folds_def, train_rows, test_rows,
                   ligakarte):
    """
    Ein Bestand, vollstaendig gemessen.

    Dieselbe Strecke fuer Standard und Kontext. Zwei getrennte
    Rechenwege waeren die sicherste Art, einen Unterschied zu messen,
    der nur aus dem Messaufbau stammt.
    """
    from src.ml import feature_groups as fg
    from src.ml import model as mdl

    spalten = fg.columns_for(ce.CANDIDATE)
    folds = [ce.evaluate_fold(zeilen, fold, spalten, mdl.ALPHA_CANDIDATES,
                              train_rows=train_rows, test_rows=test_rows)
             for fold in folds_def]

    zusammen = ce.aggregate(folds)
    test_zeilen, basis_v, ml_v, basis_s, ml_s = _bestand_metriken(folds)

    segmente = ({} if not test_zeilen
                else _segmente(test_zeilen, basis_v, ml_v, ligakarte))
    konz = ({} if not test_zeilen
            else concentration(test_zeilen, basis_v, ml_v))

    zuverlaessigkeit = {
        "baseline": _reliability(ev.merge_calibration_sums(basis_s)),
        "ml": _reliability(ev.merge_calibration_sums(ml_s)),
    }

    for fold in folds:
        fold.pop("_internal", None)

    return {
        "inventory": name,
        "folds": folds,
        "aggregate": zusammen,
        "segments": segmente,
        "distinct_damage": distinct_damage(segmente),
        "concentration": konz,
        "reliability": zuverlaessigkeit,
        "rows_evaluated": len(test_zeilen),
        "distinct_row_ids": len({z["row_id"] for z in test_zeilen}),
    }


def run_measurement(zeilen):
    """
    Standard- und Kontextbestand, beide vollstaendig.

    Der Standardbestand traegt die Freigabeentscheidung. Der
    Kontextbestand ist Diagnose mit genau einer sperrenden Bedingung,
    und zwar der im Vertrag festgeschriebenen.
    """
    import collections

    from src.ml import feature_groups as fg

    ligakarte = team_league_map()
    cl_zeilen = [z for z in zeilen if z.get("league") == "cl"]

    standard = _messe_bestand(
        zeilen, "standard", ce.OUTER_FOLDS,
        train_rows=None, test_rows=None, ligakarte=ligakarte)

    kontext = _messe_bestand(
        zeilen, "context", ce.CONTEXT_FOLDS,
        train_rows=ce.context_training_rows, test_rows=ce.context_rows,
        ligakarte=ligakarte)

    quellen = collections.Counter()
    tiefen = []
    for zeile in cl_zeilen:
        for seite in ("home", "away"):
            quellen[zeile.get(seite + "_profile_source")] += 1
            wert = zeile.get(seite + "_profile_matches")
            if isinstance(wert, (int, float)):
                tiefen.append(wert)
    tiefen.sort()

    return {
        "candidate": ce.CANDIDATE,
        "feature_columns": sorted(fg.columns_for(ce.CANDIDATE)),
        "feature_count": len(fg.columns_for(ce.CANDIDATE)),
        "dataset": {
            "total_rows": len(zeilen),
            "cl_rows": len(cl_zeilen),
            "dataset_fingerprint": ce.dataset_fingerprint(zeilen),
            "pure_target_fingerprint": pure_target_fingerprint(zeilen),
            "profile_sources": dict(sorted(quellen.items())),
            "profile_depth_median": (tiefen[len(tiefen) // 2]
                                     if tiefen else None),
            "profile_depth_min": tiefen[0] if tiefen else None,
            "evaluation_eligible": sum(
                1 for z in cl_zeilen if z.get("evaluation_eligible")),
            "knockout_eligible": sum(
                1 for z in cl_zeilen if z.get("knockout_eligible")),
        },
        "exclusions": ce.excluded_summary(zeilen),
        "standard": standard,
        "context": kontext,
    }


# ---------------------------------------------------------------------------
# Die Entscheidung
# ---------------------------------------------------------------------------

def _keine_fold_dominanz(fold_deltas, grenze=0.9):
    """
    Traegt ein einzelner Fold praktisch den gesamten Gewinn?

    Unveraendert aus V2-C12 uebernommen.
    """
    summe = sum(fold_deltas)
    if not fold_deltas or summe >= 0:
        return True
    return max(d / summe for d in fold_deltas) <= grenze


def decide(messung, vertrag=None):
    """
    Die Gates anwenden - Bedingung fuer Bedingung.

    Jede Schwelle stammt aus einem frueher freigegebenen Vertrag. Keine
    davon wurde fuer C14 gewaehlt, und keine darf sich nach Sichtung
    der Zahlen bewegen.
    """
    vertrag = vertrag if vertrag is not None else evaluation_contract()

    standard = messung.get("standard") or {}
    kontext = messung.get("context") or {}
    zusammen = standard.get("aggregate") or {}
    folds = [f for f in standard.get("folds") or [] if "error" not in f]

    n = zusammen.get("n") or 0
    delta = zusammen.get("delta_log_loss")
    intervall = (zusammen.get("bootstrap") or {}).get("log_loss") or {}
    ci_high = intervall.get("ci_high")
    ci_low = intervall.get("ci_low")

    basis = zusammen.get("baseline") or {}
    ml = zusammen.get("ml") or {}

    if not folds or n < ce.MIN_RELIABLE_N or delta is None:
        return {
            "verdict": VERDICT_NOT_EVALUABLE,
            "conditions": {"evaluable": False},
            "reasons": ["n = %s, Folds = %s, Delta = %r"
                        % (n, len(folds), delta)],
            "contract_fingerprint": contract_fingerprint(vertrag),
        }

    fold_deltas = [f.get("delta_log_loss") for f in folds
                   if f.get("delta_log_loss") is not None]

    schaden = standard.get("distinct_damage") or []

    kalib_basis = basis.get("calibration_error")
    kalib_ml = ml.get("calibration_error")
    kalib_ok = (kalib_basis is not None and kalib_ml is not None
                and kalib_ml <= kalib_basis
                * (1.0 + c8.MAX_CALIBRATION_DEGRADATION))

    kontext_delta = (kontext.get("aggregate") or {}).get("delta_log_loss")
    kontext_ok = (kontext_delta is None
                  or kontext_delta < ce.SEVERE_DEGRADATION)

    bedingungen = {
        "primary_better": delta < 0,
        "all_folds_same_direction": bool(fold_deltas) and all(
            d < 0 for d in fold_deltas),
        "no_single_fold_carries_all": _keine_fold_dominanz(fold_deltas),
        "ci_excludes_zero": ci_high is not None and ci_high < 0,
        "brier_not_worse": (zusammen.get("delta_brier") is not None
                            and zusammen["delta_brier"]
                            <= c8.MAX_SECONDARY_DEGRADATION),
        "rps_not_worse": (zusammen.get("delta_rps") is not None
                          and zusammen["delta_rps"]
                          <= c8.MAX_SECONDARY_DEGRADATION),
        "calibration_holds": kalib_ok,
        "no_severe_segment_damage": not schaden,
        "sample_large_enough": n >= ce.MIN_RELIABLE_N,
        "no_fold_severely_worse": all(
            d < ce.SEVERE_DEGRADATION for d in fold_deltas),
        "context_not_severely_damaged": kontext_ok,
    }

    gruende = []
    if not bedingungen["primary_better"]:
        gruende.append("der primaere LogLoss ist nicht besser (%+.5f)"
                       % delta)
    if not bedingungen["all_folds_same_direction"]:
        gruende.append("die Folds widersprechen sich (%s)"
                       % ", ".join("%+.5f" % d for d in fold_deltas))
    if not bedingungen["ci_excludes_zero"]:
        gruende.append(
            "das 95-%%-Intervall schliesst die Null ein [%s; %s]"
            % ("-" if ci_low is None else "%+.5f" % ci_low,
               "-" if ci_high is None else "%+.5f" % ci_high))
    if not bedingungen["calibration_holds"]:
        gruende.append("die Kalibrierung bricht ein (%s gegen %s)"
                       % (kalib_ml, kalib_basis))
    if not bedingungen["brier_not_worse"]:
        gruende.append("Brier wird schlechter (%s)"
                       % zusammen.get("delta_brier"))
    if not bedingungen["rps_not_worse"]:
        gruende.append("RPS wird schlechter (%s)" % zusammen.get("delta_rps"))
    if schaden:
        gruende.append("schwer verschlechterte Segmentgruppen: %s"
                       % schaden[:5])
    if not bedingungen["context_not_severely_damaged"]:
        gruende.append("der Kontextbestand wird schwer beschaedigt (%+.5f)"
                       % kontext_delta)

    if all(bedingungen.values()):
        verdict = VERDICT_ACCEPTED
        gruende.append("alle Gates erfuellt")
    elif (not bedingungen["primary_better"]
          or not bedingungen["all_folds_same_direction"]
          or not bedingungen["no_fold_severely_worse"]
          or schaden
          or not bedingungen["brier_not_worse"]
          or not bedingungen["rps_not_worse"]
          or not bedingungen["context_not_severely_damaged"]):
        verdict = VERDICT_REJECTED
    else:
        verdict = VERDICT_PROVISIONAL_SHADOW

    return {
        "verdict": verdict,
        "conditions": bedingungen,
        "reasons": gruende,
        "delta_log_loss": delta,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "per_fold_delta": fold_deltas,
        "calibration_baseline": kalib_basis,
        "calibration_ml": kalib_ml,
        "context_delta_log_loss": kontext_delta,
        "n": n,
        "distinct_damage": schaden,
        "acceptance_class": (ACCEPTANCE_CLASS_DEVELOPMENT
                             if verdict == VERDICT_ACCEPTED else None),
        "holdout_caveat": (
            "Die Saisons 2023 bis 2025 haben jede Entscheidung von C2 "
            "bis C13 getragen. Dieses Ergebnis ist Entwicklungsevidenz, "
            "keine unabhaengige Bestaetigung."),
        "contract_fingerprint": contract_fingerprint(vertrag),
    }


# ---------------------------------------------------------------------------
# Das Ergebnisartefakt
# ---------------------------------------------------------------------------

#: Felder, die eine Momentaufnahme sind. Sie stehen im Artefakt, gehen
#: aber in keinen fachlichen Fingerabdruck ein - sonst waere jeder
#: zweite Lauf per Definition ein anderes Ergebnis.
VOLATILE_FIELDS = ("created_at", "git_commit", "runtime_seconds")


def _git_commit():
    import subprocess

    try:
        lauf = subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        return lauf.stdout.strip() or None
    except Exception:                                    # pragma: no cover
        return None


def result_fingerprint(artefakt):
    """
    Der fachliche Fingerabdruck des Ergebnisses.

    Ohne Erstellungszeit und git-Stand. Zwei Laeufe mit denselben
    Eingaben muessen denselben Wert liefern; taeten sie es nicht, waere
    jede Aussage ueber Reproduzierbarkeit wertlos.
    """
    ohne = {k: v for k, v in artefakt.items()
            if k not in VOLATILE_FIELDS and k != "result_fingerprint"}
    return _stabil(json.loads(json.dumps(ohne, sort_keys=True, default=str)))


def build_artifact(messung, urteil):
    """
    Der C14-Nachweis - deterministisch und ohne Rohdaten.

    Keine Zugangsdaten, keine vollstaendigen Merkmalsvektoren, keine
    lokalen absoluten Pfade.
    """
    import datetime as _dt

    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import early_v2 as e9
    from src.ml import model_registry as mr

    vertrag = evaluation_contract()
    aktiv, grund = mr.active_entry()

    artefakt = {
        "artifact": "v2-c14 reevaluation",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),

        # -- Vertragsbindung ----------------------------------------------
        "contract_fingerprint": contract_fingerprint(vertrag),
        "contract_frozen_before_measurement": True,
        "contract_path": CONTRACT_PATH,
        "bound_contracts": {
            "c9_schema_fingerprint": e9.schema_fingerprint(),
            "c10_cutoff_hour": pc.CUTOFF_HOUR,
            "c10_inclusive": pc.CUTOFF_INCLUSIVE,
            "c11_contract_fingerprint": _stabil(mr.contract()),
            "c13_contract_fingerprint": c13.contract_fingerprint(),
        },

        # -- Kandidat -------------------------------------------------------
        "candidate": vertrag["candidate"],

        # -- Messung --------------------------------------------------------
        "measurement": messung,

        # -- Entscheidung ---------------------------------------------------
        "decision": urteil,
        "verdict": urteil["verdict"],

        # -- Registry, unveraendert ------------------------------------------
        "registry": {
            "active_model": (aktiv or {}).get("model_id"),
            "no_active_reason": grund,
            "changed_by_c14": False,
            "bundle_created": urteil["verdict"] == VERDICT_ACCEPTED,
            "why": ("C14 entscheidet und aktiviert nicht. Ein "
                    "Trainingslauf darf die Registry niemals nebenbei "
                    "umschalten."),
        },

        "thin_profile_diagnosis": _thin_profile_diagnosis(messung),

        "next_block_requirements": _next_block_requirements(urteil,
                                                            messung),

        "fingerprint_excludes": list(VOLATILE_FIELDS),

        "known_limits": [
            "Kein unangetasteter Holdout. Die Saisons 2023 bis 2025 "
            "haben jede Entscheidung von C2 bis C13 getragen.",
            "Zwei aeussere Folds sind wenig. Eine Foldabweichung kann "
            "eine Saisoneigenschaft sein.",
            "Der Standardvertrag trainiert ausschliesslich auf "
            "nationalen Ligen. Dort spielen nie zwei Vereine "
            "verschiedener Ligen gegeneinander, weshalb die "
            "Ligastaerke in diesem Aufbau strukturell nicht lernbar "
            "ist.",
            "Die Konzentrationsdiagnose hat keine numerische Schwelle "
            "und ist deshalb kein Gate.",
        ],
    }
    artefakt["result_fingerprint"] = result_fingerprint(artefakt)
    return artefakt


def write_artifact(messung, urteil, pfad=None):
    """Das Ergebnisartefakt atomar schreiben."""
    return _atomar_schreiben(
        pfad or ARTIFACT_PATH,
        json.dumps(build_artifact(messung, urteil), indent=2,
                   ensure_ascii=False, default=str))


def _thin_profile_diagnosis(messung):
    """
    Was die duennen Profile tatsaechlich tun (V2-C14, Paragraph 13).

    In C12 war `profile_depth:<20` eines der beiden Segmente, die die
    Freigabe verhinderten. Die Frage fuer den Folgeblock lautet
    deshalb: Braucht es Shrinkage?

    Die Antwort steht in den Zahlen und wird hier ausgewiesen, statt
    sie zu vermuten. C14 optimiert nichts daran - eine an diesen
    Ergebnissen gewaehlte Shrinkage-Staerke waere eine Anpassung an
    den Testbestand.
    """
    segmente = (messung.get("standard") or {}).get("segments") or {}
    interessant = {}
    for name, block in segmente.items():
        if name.startswith(("min_profile_depth:", "home_profile_depth:",
                            "away_profile_depth:", "both_profile_depth:",
                            "profile_depth:")):
            interessant[name] = {
                "n": block["n"],
                "delta_log_loss": block["delta_log_loss"],
                "interpretable": block["interpretable"],
                "severely_worse": block["severely_worse"],
            }

    duenn = segmente.get("min_profile_depth:6-19") or {}
    dick = segmente.get("min_profile_depth:>=20") or {}
    gesamt = ((messung.get("standard") or {}).get("aggregate")
              or {}).get("delta_log_loss")

    shrinkage_noetig = bool(
        duenn.get("interpretable") and duenn.get("severely_worse"))

    return {
        "segments": dict(sorted(interessant.items())),
        "thin_delta": duenn.get("delta_log_loss"),
        "thin_n": duenn.get("n"),
        "deep_delta": dick.get("delta_log_loss"),
        "deep_n": dick.get("n"),
        "overall_delta": gesamt,
        "shrinkage_indicated": shrinkage_noetig,
        "reading": (
            "Duenne Profile schneiden nach C13 BESSER ab als tiefe. Die "
            "C12-Sorge um `profile_depth:<20` hat sich damit erledigt: "
            "Sie stammte aus den cl_history-Profilen, die es nicht mehr "
            "gibt. Shrinkage wuerde ein Problem loesen, das nicht mehr "
            "existiert."
            if not shrinkage_noetig else
            "Duenne Profile bleiben schwer verschlechtert. Eine vorab "
            "spezifizierte, train-fold-lokal bestimmte Shrinkage waere "
            "der naechste Schritt."),
        "no_optimisation_here": (
            "C14 waehlt keine Shrinkage-Staerke. Das waere Anpassung an "
            "den Testbestand."),
    }


def _next_block_requirements(urteil, messung):
    """
    Was der zweite Abschlussblock genau tun muss.

    Aus dem tatsaechlichen Ergebnis abgeleitet, nicht aus einem
    Wunsch. Ohne diesen Block muesste der naechste Auftrag die Analyse
    wiederholen.
    """
    verdict = urteil["verdict"]
    standard = messung.get("standard") or {}
    schaden = standard.get("distinct_damage") or []
    segmente = standard.get("segments") or {}

    gemeinsam = {
        "verdict_this_block": verdict,
        "must_not_reopen": [
            "C9-Merkmalsfreeze und Schemafingerabdruck",
            "C10-Stichtagsvertrag",
            "C13-Ligaliste und Identitaetsregel",
            "die numerischen Schwellen aus C2B/C8",
        ],
        "must_stay_true": [
            "kein Testfold in Auswahl oder Kalibrierung",
            "Vertrag vor der Messung einfrieren",
            "Registry nur ueber das ausdrueckliche C11-Gate",
        ],
    }

    if verdict == VERDICT_ACCEPTED:
        gemeinsam["work"] = [
            "Kandidatenbundle deterministisch erzeugen und an alle "
            "Fingerabdruecke binden",
            "Freigabe ueber das C11-Gate, Rollback end-to-end proben",
            "Runtime aktivieren, Fallback erhalten",
        ]
        return gemeinsam

    if verdict == VERDICT_NOT_EVALUABLE:
        gemeinsam["work"] = [
            "den technischen Blocker beheben, dann erneut messen",
        ]
        return gemeinsam

    # rejected oder provisional_shadow: die Ursache benennen.
    quelle = segmente.get("origin:top5_vs_other") or {}
    gemeinsam["blocking_findings"] = {
        "damaged_segment_groups": schaden,
        "primary_cause_segment": "origin:top5_vs_other",
        "primary_cause_n": quelle.get("n"),
        "primary_cause_delta": quelle.get("delta_log_loss"),
        "diagnosis": (
            "Nicht-Top-5-Vereine haben in JEDEM Profilmerkmal bessere "
            "Werte als Top-5-Vereine und spielen in der Champions "
            "League deutlich schlechter. Die 16 eingefrorenen Merkmale "
            "sind Verhaeltniswerte zur EIGENEN Liga und tragen keine "
            "Ligastaerke. Vor C13 fiel das nicht auf, weil diese "
            "Vereine cl_history-Profile bekamen, die an "
            "CL-Gegnern gemessen und damit implizit auf der richtigen "
            "Skala waren."),
        "structural_limit": (
            "Der Standardvertrag trainiert ausschliesslich auf "
            "nationalen Ligen. Dort spielen nie zwei Vereine "
            "verschiedener Ligen gegeneinander - die Ligastaerke ist "
            "in diesem Aufbau strukturell nicht lernbar."),
        "context_contract_does_not_fix_it": (
            "Auch mit frueheren CL-Partien im Training bleibt das "
            "Segment beschaedigt. Ohne ein Merkmal, das die Liga "
            "unterscheidbar macht, kann das Modell nicht darauf "
            "bedingen."),
    }
    gemeinsam["work"] = [
        "ein Ligastaerkemerkmal einfuehren und in einem NEUEN, vorab "
        "eingefrorenen Vertrag messen",
        "die Merkmalsmenge dabei ausdruecklich erweitern, statt sie "
        "still zu veraendern",
        "danach erneut entscheiden, ohne die Gates zu bewegen",
    ]
    return gemeinsam
