"""
Historische Saisonvalidierung der Champions-League-Ligaphase (V2-C21).

WORUM ES GEHT
-------------
Bis C20 wurde V2 ausschliesslich an EINZELSPIELEN gemessen. Das
Produkt zeigt aber eine TABELLE: erwartete Punkte, Platz, und die
Wahrscheinlichkeiten fuer Achtelfinale, Play-off und Ausscheiden. Der
forensische Audit, mit dem diese Reihe begann, war genau an einer
unplausiblen Tabelle aufgebrochen. Ob die Einzelspielguete sich in eine
brauchbare Tabelle uebersetzt, ist eine eigene Frage - und bis hierher
unbeantwortet.

Dieses Modul beantwortet sie auf den beiden Ligaphasen, die lokal
vollstaendig vorliegen (2024/25 und 2025/26, je 144 Partien, 36
Vereine), und zwar ueber den ECHTEN Saisonpfad:

  - Spielplan aus dem produktiven Planbauer (cl_fixture_plan),
  - Profile aus der produktiven Staerkefabrik zum historischen
    Stichtag (get_cl_team_strengths),
  - Simulation, Tabellenbildung und Tiebreaker aus cl_season_sim,
  - V2 ueber die produktive Laufzeit mit einem Foldbundle, das in einer
    ISOLIERTEN Registry ueber den echten Freigabeweg (apply_release)
    aktiv gesetzt wurde.

Keine zweite, idealisierte Vorhersagekette. Wo die Laufzeit auf die
echte Registry zeigt, wird sie fuer die Dauer eines Laufs auf ein
temporaeres Wurzelverzeichnis umgelenkt; Registrypruefung, Stufen-
pruefung, Freigabepruefung und Bundleladen bleiben dabei unveraendert.

ZWEI PROGNOSEARTEN, NICHT VERMENGT
----------------------------------
  A  Saisonstart: Stichtag vor der ersten Ligaphasenpartie, alle 144
     Partien simuliert, alle Profile an diesem Tag eingefroren.
  B  Aktualisiert: Stichtage nach den Spieltagen 2, 4 und 6. Bekannt
     ist genau, was vor dem Stichtag gespielt wurde; alles andere wird
     simuliert. Die Profile kennen nichts nach dem Stichtag.

Eine Sammlung von Einzelspielprognosen, deren Profile jeweils die
spaetere Saisonhistorie kennen, ist KEINE Saisonstartprognose und wird
hier auch nicht als solche ausgegeben.

WAS DIESES MODUL NICHT IST
--------------------------
Keine unabhaengige Bestaetigung. Beide Saisons sind dieselben, auf denen
die Match-Evaluation gemessen hat. Ein bestandenes Tabellen-Gate ist
Entwicklungsevidenz.
"""

import collections
import contextlib
import datetime as _dt
import functools
import hashlib
import json
import math
import os
import random
import tempfile

CONTRACT_VERSION = "v2-c21.1"

CONTRACT_PATH = "data/ml/c21_season_validation_contract.json"
RESULT_PATH = "data/ml/c21_season_validation.json"

#: Die historische Population. Beide Ligaphasen im 36-Vereine-Format,
#: die lokal vollstaendig vorliegen.
SEASONS = (2024, 2025)

#: Simulationszahl und Seeds - vor der Messung festgelegt.
SIMULATIONS = 10000
SEEDS = (21001, 21002, 21003)

#: Aktualisierte Prognosen nach diesen abgeschlossenen Spieltagen.
UPDATE_AFTER_MATCHDAYS = (2, 4, 6)

#: Die drei Zonen, die das Produkt anzeigt, in ihrer Rangordnung.
ZONES = (("direct", 1, 8), ("playoff", 9, 24), ("out", 25, 36))

#: Toleranzen. Keine davon wird hier neu gewaehlt, siehe contract().
PARITY_TOLERANCE = 1e-9
MC_STABILITY_LIMIT = 0.002
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_SEED = 20260921

BASELINE_NAME = ("V0: aktuelle klassische Engine, ML aus "
                 "(FOOTSIM_ML_MODE=off), dieselben C13-Profile")
CANDIDATE_NAME = ("V2: C20-Modell, je Saison das zeitlich zulaessige "
                  "Foldbundle, aktiv in isolierter Registry")


def _noninferiority_margin():
    from src.ml import cl_evaluate as ce
    return ce.SEVERE_DEGRADATION


def _segment_min_size():
    from src.ml import c15_league_strength as c15
    return c15.SEGMENT_MIN_SIZE


def _stabil(block):
    text = json.dumps(block, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Der Vertrag
# ---------------------------------------------------------------------------

def contract():
    """Die Regeln der Saisonvalidierung - ohne eine einzige Messung."""
    from src.ml import c20_temporal_map as c20
    from src.predict import cl_season_sim as css

    marge = _noninferiority_margin()
    return {
        "version": CONTRACT_VERSION,
        "question": ("Uebersetzt sich V2 in eine Ligaphasenprognose, die "
                     "nicht schwer schlechter ist als die aktuelle "
                     "klassische Engine?"),
        "evidence_class": ("Entwicklungsevidenz - dieselben Saisons wie die "
                           "Match-Evaluation, kein unangetasteter Holdout"),

        "population": {
            "seasons": list(SEASONS),
            "competition": "Champions League, Ligaphase",
            "matches_per_season": 144,
            "teams_per_season": 36,
            "source": "lokale Saisondateien data/historical/CL_<saison>.json",
            "network": False,
            "all_matches_simulated": True,
            "match_evaluation_overlap": (
                "Die Match-Evaluation umfasst 283 der 288 Partien. Die "
                "fuenf fehlenden (alle 2025/26) fielen dort wegen "
                "Profiltiefe unter 6 Partien heraus. Eine Tabelle ist ohne "
                "sie nicht berechenbar; hier werden sie mit der "
                "produktiven Rueckfallsemantik mitsimuliert und nicht "
                "ausgeschlossen."),
        },

        "forecast_types": {
            "A_season_start": {
                "cutoff": ("prediction_cutoff(Datum der ersten "
                           "Ligaphasenpartie) - C10-Stichtag, vor jedem "
                           "Anpfiff dieses Tages"),
                "known_results": 0,
                "simulated": 144,
            },
            "B_updated": {
                "after_matchdays": list(UPDATE_AFTER_MATCHDAYS),
                "cutoff": ("prediction_cutoff(erstes Datum des Spieltags "
                           "k+1)"),
                "known": ("eine Partie gilt als bekannt, wenn ihr Datum "
                          "vor dem Stichtag liegt; entschieden wird nach "
                          "Datum, nicht nach Spieltag - eine verschobene "
                          "Partie bleibt offen"),
            },
            "profiles": ("ausschliesslich aus Partien vor dem Stichtag "
                         "(get_cl_team_strengths mit historischem cutoff, "
                         "C10)"),
            "target": "die tatsaechliche Abschlusstabelle der Ligaphase",
        },

        "models": {
            "baseline": BASELINE_NAME,
            "candidate": CANDIDATE_NAME,
            "fold_per_season": {"2024": "cl_2024 (Training 2023)",
                                "2025": "cl_2025 (Training 2023, 2024)"},
            "map_contract": c20.CONTRACT_VERSION,
            "map_contract_fingerprint": c20.contract_fingerprint(),
            "production_bundle_on_earlier_seasons": "ausgeschlossen",
            "activation": ("Foldbundle ueber apply_release(dry_run=False) "
                           "in einem temporaeren Wurzelverzeichnis; die "
                           "echte Registry wird nicht beruehrt"),
        },

        "simulation": {
            "simulations": SIMULATIONS,
            "seeds": list(SEEDS),
            "engine": "src.predict.cl_season_sim.simulate_cl_league_phase",
        },

        "ranking": {
            "tiebreak_criteria": list(css.TIEBREAK_CRITERIA),
            "missing_criteria": list(css.TIEBREAK_MISSING),
            "missing_handling": ("deterministischer Rueckfall auf die "
                                 "Team-ID, gemeldet statt geraten"),
            "zones": [list(z) for z in ZONES],
            "actual_table": ("aus den 144 lokalen Ergebnissen mit derselben "
                             "Rangfunktion wie die Simulation"),
        },

        "missing_profiles_and_leagues": (
            "produktive Kaskade: nationale Historie, CL-Historie, "
            "Neutralprofil; zweite Stufe nach C20: fehlender Verein "
            "neutral, Liga ohne Parameter mit Beitrag 0. Keine Partie und "
            "kein Verein wird ausgeschlossen."),

        "metrics": {
            "primary": {
                "name": "zone_rps",
                "definition": ("Ranked Probability Score ueber die drei "
                               "geordneten Zonen je Verein, gemittelt"),
                "why": ("streng richtige Bewertungsregel fuer genau die "
                        "Wahrscheinlichkeiten, die das Produkt zeigt; die "
                        "Zonen sind geordnet, ein Verein im falschen "
                        "Nachbarbereich kostet weniger als einer am "
                        "anderen Ende"),
                "scope": "Prognoseart A, beide Saisons gepoolt, Mittel "
                         "ueber die Seeds",
            },
            "secondary": ["brier_top8", "brier_top24", "points_mae",
                          "position_spearman", "goals_for_mae",
                          "total_goals"],
            "resolution_note": ("Zonenwahrscheinlichkeiten und erwartete "
                                "Punkte werden so bewertet, wie das "
                                "Produkt sie ausgibt (0,1 Prozentpunkte "
                                "bzw. 0,1 Punkte); V0 und V2 tragen "
                                "dieselbe Rundung"),
        },

        "gates": {
            "S1_primary_noninferior": (
                "zone_rps(V2) - zone_rps(V0), A gepoolt, < %s" % marge),
            "S2_no_season_severely_worse": (
                "fuer jede Saison: Differenz zone_rps, A, < %s" % marge),
            "S3_updated_forecasts_noninferior": (
                "zone_rps, B gepoolt ueber alle Stichtage beider "
                "Saisons, Differenz < %s" % marge),
            "S4_qualification_not_severely_worse": (
                "brier_top8 und brier_top24, A gepoolt, jeweils "
                "Differenz < %s" % marge),
            "S5_monte_carlo_stable": (
                "Spannweite der primaeren Differenz ueber die Seeds "
                "<= %s" % MC_STABILITY_LIMIT),
            "S6_technical_integrity": (
                "je Stichtag 144 Partien, 8 je Verein, bekannte plus "
                "offene Partien vollstaendig; Lambdas des Saisonpfads "
                "gleich denen des Einzelspielpfads bis %s; keine "
                "Profilquelle nach dem Stichtag; echte Registry und "
                "echtes Modellverzeichnis unveraendert" % PARITY_TOLERANCE),
        },
        "thresholds": {
            "noninferiority_margin": marge,
            "noninferiority_origin": (
                "cl_evaluate.SEVERE_DEGRADATION, die Grenze fuer 'schwer "
                "verschlechtert' aus dem C16-Vertrag - uebernommen, nicht "
                "neu gewaehlt"),
            "mc_stability_limit": MC_STABILITY_LIMIT,
            "mc_stability_origin": (
                "ein Fuenftel der Nichtunterlegenheitsgrenze, damit kein "
                "Gate-Entscheid vom Seed abhaengen kann"),
            "parity_tolerance": PARITY_TOLERANCE,
            "parity_origin": "wie C18 bis C20",
        },

        "why_noninferiority": (
            "Die Ueberlegenheit von V2 ist auf Spielebene bereits mit elf "
            "Gates gemessen. 72 Vereinssaisons tragen keinen "
            "Ueberlegenheitsnachweis; gefragt ist, ob die Tabelle dadurch "
            "schwer schlechter wird. Genau das war der Ausgangsbefund des "
            "forensischen Audits."),

        "risk_diagnostics": {
            "pre_registered": ["Vereine mit Herkunftsliga PD",
                               "Vereine mit Herkunftsliga SA"],
            "why": ("aus C20 bekannte Match-Segmente home_origin_league:PD "
                    "und away_origin_league:SA"),
            "not_equivalent": (
                "Ein Match-Segment ist keine Vereinsmenge: Heim- und "
                "Auswaertsspiele desselben Vereins fallen in der Tabelle "
                "zusammen. Berichtet werden Tabellenmetriken der Vereine "
                "dieser Ligen, ausdruecklich nicht als Ersatz der "
                "Match-Segmente."),
            "gated": False,
            "why_not_gated": ("SEGMENT_MIN_SIZE = %d aus C15; je Liga "
                              "liegen weniger Vereinssaisons vor"
                              % _segment_min_size()),
        },

        "uncertainty": {
            "monte_carlo": "Streuung ueber die drei Seeds",
            "generalisation": (
                "Mit zwei Saisons nicht schaetzbar. Ein gepaarter "
                "Bootstrap ueber Vereine je Saison wird BESCHREIBEND "
                "berichtet; er repliziert keine Saisons, weil die "
                "Tabellenplaetze innerhalb einer Saison gekoppelt sind. "
                "Entschieden wird auf dem Punktschaetzer."),
            "bootstrap": {"iterations": BOOTSTRAP_ITERATIONS,
                          "seed": BOOTSTRAP_SEED},
        },

        "decision": ("accepted genau dann, wenn S1 bis S6 erfuellt sind; "
                     "sonst rejected. Kein Gate, keine Schwelle und keine "
                     "Population wird nach der Messung veraendert."),
    }


def contract_fingerprint():
    return _stabil(contract())


# ---------------------------------------------------------------------------
# Population und Stichtage
# ---------------------------------------------------------------------------

def league_phase(season):
    """Die lokalen Ligaphasenpartien einer Saison, unveraendert."""
    from src.data.historical_loader import season_file_path

    with open(season_file_path("CL", season), encoding="utf-8") as datei:
        daten = json.load(datei)
    return [m for m in daten.get("matches") or []
            if m.get("stage") == "LEAGUE_STAGE"]


def fold_for(season):
    from src.ml import cl_evaluate as ce
    treffer = [f for f in ce.OUTER_FOLDS if f["test_season"] == season]
    if len(treffer) != 1:
        raise ValueError("kein eindeutiger Fold fuer Saison %s" % season)
    return treffer[0]


def cutoffs(season):
    """
    Die vorab festgelegten Stichtage einer Saison.

    Rueckgabe: Liste von (name, stichtag). Der erste ist die
    Saisonstartprognose, die weiteren folgen auf die Spieltage in
    UPDATE_AFTER_MATCHDAYS.
    """
    from src.ml import dataset as ds

    partien = league_phase(season)
    erster = min(m["date"] for m in partien)
    heraus = [("A_season_start", ds.prediction_cutoff(erster))]
    for k in UPDATE_AFTER_MATCHDAYS:
        naechster = min(m["date"] for m in partien
                        if m["matchday"] == k + 1)
        heraus.append(("B_after_md%d" % k, ds.prediction_cutoff(naechster)))
    return heraus


def _eingabe_fuer_planbauer(partien, stichtag):
    """
    Die lokalen Partien in der Form, die der Planbauer liest.

    Ausschliesslich Feldnamen werden angepasst; entschieden wird allein
    nach dem Datum, ob ein Ergebnis zum Stichtag bekannt war.
    """
    grenze = stichtag.date().isoformat()
    heraus = []
    for m in partien:
        bekannt = m["date"] < grenze
        heraus.append({
            "id": m["match_id"], "stage": "LEAGUE_STAGE",
            "matchday": m["matchday"], "utc_date": m["date"],
            "status": "FINISHED" if bekannt else "SCHEDULED",
            "home_id": m["home_id"], "away_id": m["away_id"],
            "home_team": None, "away_team": None,
            "home_goals": m["home_goals"] if bekannt else None,
            "away_goals": m["away_goals"] if bekannt else None,
        })
    return heraus


def plan_at(season, stichtag):
    """
    Der produktive Ligaphasenplan zum historischen Stichtag.

    cl_fixture_plan holt seine Partien sonst beim Anbieter. Hier wird
    ihm fuer die Dauer des Aufrufs die lokale Saisondatei gereicht; die
    Planlogik selbst (Ligaphase, Duplikate, Abdeckung, Status) bleibt
    die produktive.
    """
    from src.predict import cl_fixture_plan as cfp

    eingabe = _eingabe_fuer_planbauer(league_phase(season), stichtag)
    original = cfp.get_all_matches
    cfp.get_all_matches = (lambda code, season=None, only_finished=False:
                           list(eingabe))
    try:
        return cfp.build_cl_league_phase_plan(season=season)
    finally:
        cfp.get_all_matches = original


def actual_table(season):
    """
    Die tatsaechliche Abschlusstabelle - mit der Rangfunktion der
    Simulation, damit Ziel und Prognose dieselben Regeln haben.

    Meldet ausdruecklich, ob an einer Zonengrenze erst der
    deterministische Rueckfall entschieden hat.
    """
    from src.predict import cl_season_sim as css

    partien = league_phase(season)
    team_ids = sorted({m["home_id"] for m in partien}
                      | {m["away_id"] for m in partien})
    fixtures = [{"home_id": m["home_id"], "away_id": m["away_id"],
                 "home_goals": m["home_goals"],
                 "away_goals": m["away_goals"]} for m in partien]
    tabelle = css.build_base_table(team_ids, fixtures)
    gegner = css.build_opponent_map(fixtures)
    reihenfolge, rueckfall = css._rank_table(
        team_ids, tabelle, gegner, {t: str(t) for t in team_ids})

    def schluessel(t):
        zeile = tabelle[t]
        op = [tabelle[g] for g in gegner.get(t, ())]
        return (zeile["pts"], zeile["gd"], zeile["gf"], zeile["away_goals"],
                zeile["wins"], zeile["away_wins"],
                sum(o["pts"] for o in op), sum(o["gd"] for o in op),
                sum(o["gf"] for o in op))

    grenzen = {}
    for letzte in (ZONES[0][2], ZONES[1][2]):
        a, b = reihenfolge[letzte - 1], reihenfolge[letzte]
        grenzen[str(letzte)] = {
            "tied_on_all_criteria": schluessel(a) == schluessel(b)}

    heraus = {}
    for platz, t in enumerate(reihenfolge, start=1):
        zeile = tabelle[t]
        heraus[t] = {"position": platz, "points": zeile["pts"],
                     "gf": zeile["gf"], "ga": zeile["ga"],
                     "zone": zone_index(platz)}
    return heraus, {"fallback_used": bool(rueckfall),
                    "zone_boundaries": grenzen}


def zone_index(platz):
    for i, (_name, von, bis) in enumerate(ZONES):
        if von <= platz <= bis:
            return i
    raise ValueError("Platz %s ausserhalb der Zonen" % platz)


# ---------------------------------------------------------------------------
# Isolierte Aktivierung ueber den echten Freigabeweg
# ---------------------------------------------------------------------------

def fold_bundle(season, zeilen, evaluation):
    """Das zeitlich zulaessige Foldbundle einer Saison (C20-Weg)."""
    from src.ml import c16_release as rel
    from src.ml import c20_temporal_map as c20

    fold = fold_for(season)
    bundle, _diag = rel.build_final_bundle(
        zeilen, c20.fold_map(fold), evaluation,
        seasons=tuple(fold["train_seasons"]),
        map_upto_season=c20.fold_upto(fold), map_contract=c20)
    return bundle


@contextlib.contextmanager
def isolated_activation(bundle, evaluation):
    """
    Setzt ein Bundle in einer TEMPORAEREN Registry aktiv - ueber den
    produktiven Freigabeweg - und lenkt die Laufzeit fuer die Dauer des
    Blocks dorthin um.

    Umgelenkt werden genau zwei Stellen: die Wurzel, von der
    model_registry.active_entry liest, und die Wurzel, unter der die
    Laufzeit das aktive Bundle aufloest. Alles andere - Registry-
    validierung, Freigabepruefung, Bundleladen, Stufenpruefung - laeuft
    unveraendert. Die echte Registry wird weder gelesen noch geschrieben.
    """
    from src.ml import c16_release as rel
    from src.ml import c20_temporal_map as c20
    from src.ml import inference as inf
    from src.ml import model_registry as mr

    echt_active_entry = mr.active_entry
    echt_root = inf._REPO_ROOT
    with tempfile.TemporaryDirectory() as wurzel:
        relativ = "data/ml/models/%s.json" % bundle["model_id"]
        os.makedirs(os.path.join(wurzel, "data", "ml", "models"))
        rel.write_bundle(bundle, os.path.join(wurzel, relativ))
        mr.write_registry(mr.empty_registry(), repo_root=wurzel)
        eintrag = rel._registry_eintrag(
            bundle, os.path.join(wurzel, relativ), c20.EVALUATION_PATH)
        eintrag["bundle_path"] = relativ
        freigabe = rel.apply_release(
            evaluation["decision"], eintrag, evaluation, relativ,
            repo_root=wurzel, dry_run=False)
        if freigabe.get("status") != "applied":
            raise RuntimeError("isolierte Aktivierung verweigert: %s"
                               % freigabe.get("reason"))
        mr.active_entry = functools.partial(echt_active_entry,
                                            repo_root=wurzel)
        inf._REPO_ROOT = wurzel
        inf.reset_model_cache()
        try:
            yield {"root": wurzel, "release": freigabe}
        finally:
            mr.active_entry = echt_active_entry
            inf._REPO_ROOT = echt_root
            inf.reset_model_cache()


@contextlib.contextmanager
def ml_mode(modus):
    """Betriebsart nur fuer die Dauer des Blocks."""
    alt = {k: os.environ.get(k) for k in ("FOOTSIM_ML_MODE",
                                          "FOOTSIM_ML_WEIGHT")}
    os.environ["FOOTSIM_ML_MODE"] = modus
    os.environ["FOOTSIM_ML_WEIGHT"] = "1.0"
    try:
        yield
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Metriken
# ---------------------------------------------------------------------------

def zone_probabilities(eintrag):
    roh = [eintrag["direct_pct"], eintrag["playoff_pct"],
           eintrag["eliminated_pct"]]
    summe = sum(roh)
    if summe <= 0:
        raise ValueError("Zonenwahrscheinlichkeiten fehlen")
    return [r / summe for r in roh]


def rps(wahrsch, zone):
    kum_f = kum_o = 0.0
    summe = 0.0
    for i in range(len(wahrsch) - 1):
        kum_f += wahrsch[i]
        kum_o += 1.0 if zone == i else 0.0
        summe += (kum_f - kum_o) ** 2
    return summe / (len(wahrsch) - 1)


def _rang(werte):
    reihenfolge = sorted(range(len(werte)), key=lambda i: werte[i])
    raenge = [0.0] * len(werte)
    i = 0
    while i < len(reihenfolge):
        j = i
        while (j + 1 < len(reihenfolge)
               and werte[reihenfolge[j + 1]] == werte[reihenfolge[i]]):
            j += 1
        mittel = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            raenge[reihenfolge[k]] = mittel
        i = j + 1
    return raenge


def spearman(a, b):
    ra, rb = _rang(a), _rang(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    kov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return kov / (va * vb) if va and vb else None


def team_scores(eintraege, tatsaechlich):
    """Je Verein die bewerteten Groessen - Grundlage aller Mittelwerte."""
    heraus = {}
    for e in eintraege:
        t = e["team_id"]
        ist = tatsaechlich[t]
        p = zone_probabilities(e)
        heraus[t] = {
            "zone_rps": rps(p, ist["zone"]),
            "brier_top8": (p[0] - (1.0 if ist["position"] <= 8 else 0.0)) ** 2,
            "brier_top24": ((p[0] + p[1])
                            - (1.0 if ist["position"] <= 24 else 0.0)) ** 2,
            "points_abs_error": abs(e["expected_points"] - ist["points"]),
            "goals_for_abs_error": abs(e["expected_goals_for"] - ist["gf"]),
            "expected_points": e["expected_points"],
            "expected_position": e["expected_position"],
            "expected_goals_for": e["expected_goals_for"],
            "p_zones": [round(x, 4) for x in p],
            "actual_position": ist["position"],
            "actual_points": ist["points"],
            "actual_zone": ist["zone"],
        }
    return heraus


def summarise(scores):
    teams = sorted(scores)
    n = len(teams)
    mittel = lambda k: sum(scores[t][k] for t in teams) / n
    return {
        "teams": n,
        "zone_rps": mittel("zone_rps"),
        "brier_top8": mittel("brier_top8"),
        "brier_top24": mittel("brier_top24"),
        "points_mae": mittel("points_abs_error"),
        "goals_for_mae": mittel("goals_for_abs_error"),
        "position_spearman": spearman(
            [scores[t]["expected_position"] for t in teams],
            [scores[t]["actual_position"] for t in teams]),
        "expected_total_goals": sum(scores[t]["expected_goals_for"]
                                    for t in teams),
    }


def paired_bootstrap(differenzen_je_saison, iterationen=BOOTSTRAP_ITERATIONS,
                     seed=BOOTSTRAP_SEED):
    """
    BESCHREIBENDES Intervall der gepaarten Differenz.

    Resampelt Vereine je Saison. Das ist ausdruecklich KEINE
    Replikation von Saisons: Die Plaetze einer Saison sind gekoppelt,
    und zwei Saisons erlauben keine Aussage ueber die Generalisierung.
    """
    rng = random.Random(seed)
    mittel = []
    for _ in range(iterationen):
        werte = []
        for diffs in differenzen_je_saison:
            werte.extend(rng.choice(diffs) for _ in diffs)
        mittel.append(sum(werte) / len(werte))
    mittel.sort()
    return {"low": mittel[int(0.025 * iterationen)],
            "high": mittel[int(0.975 * iterationen) - 1],
            "note": "beschreibend, keine Saisonreplikation"}


# ---------------------------------------------------------------------------
# Entscheidung
# ---------------------------------------------------------------------------

def decide(auswertung):
    """
    Die Gates des eingefrorenen Vertrags, genau in dieser Form.

    auswertung braucht:
      delta_primary_pooled, delta_primary_by_season {saison: wert},
      delta_updated_pooled, delta_brier_top8, delta_brier_top24,
      delta_primary_by_seed [werte], technical_ok, technical_findings
    """
    marge = _noninferiority_margin()
    je_seed = auswertung["delta_primary_by_seed"]
    spannweite = max(je_seed) - min(je_seed)
    bedingungen = {
        "S1_primary_noninferior":
            auswertung["delta_primary_pooled"] < marge,
        "S2_no_season_severely_worse":
            all(d < marge for d in
                auswertung["delta_primary_by_season"].values()),
        "S3_updated_forecasts_noninferior":
            auswertung["delta_updated_pooled"] < marge,
        "S4_qualification_not_severely_worse":
            (auswertung["delta_brier_top8"] < marge
             and auswertung["delta_brier_top24"] < marge),
        "S5_monte_carlo_stable": spannweite <= MC_STABILITY_LIMIT,
        "S6_technical_integrity": bool(auswertung["technical_ok"]),
    }
    return {
        "verdict": "accepted" if all(bedingungen.values()) else "rejected",
        "conditions": bedingungen,
        "failed_conditions": sorted(k for k, v in bedingungen.items()
                                    if not v),
        "measured": {
            "S1": auswertung["delta_primary_pooled"],
            "S2": auswertung["delta_primary_by_season"],
            "S3": auswertung["delta_updated_pooled"],
            "S4": {"top8": auswertung["delta_brier_top8"],
                   "top24": auswertung["delta_brier_top24"]},
            "S5_range": spannweite,
            "S6": auswertung.get("technical_findings") or [],
        },
        "limits": {"noninferiority_margin": marge,
                   "mc_stability_limit": MC_STABILITY_LIMIT},
        "evidence_class": "Entwicklungsevidenz",
        "contract_fingerprint": contract_fingerprint(),
    }


# ---------------------------------------------------------------------------
# Artefakte
# ---------------------------------------------------------------------------

def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def write_json(relativ, dokument):
    """Atomar schreiben, nie ueberschreiben."""
    ziel = os.path.join(_repo_root(), relativ)
    if os.path.exists(ziel):
        raise FileExistsError("%s existiert bereits" % relativ)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    tmp = ziel + ".tmp"
    with open(tmp, "w", encoding="utf-8") as datei:
        json.dump(dokument, datei, ensure_ascii=False, indent=1,
                  sort_keys=True, default=str)
        datei.write("\n")
    os.replace(tmp, ziel)
    return ziel


def build_contract_artifact():
    from src.ml import c19_league_map as c19

    return {
        "artifact": "v2-c21 season validation contract",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": c19._git(),
        "contract": contract(),
        "contract_fingerprint": contract_fingerprint(),
        "frozen_before_measurement": True,
        "cutoffs": {str(s): [(n, c.isoformat()) for n, c in cutoffs(s)]
                    for s in SEASONS},
    }


# ---------------------------------------------------------------------------
# Der Messablauf
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _lambda_spion():
    """
    Zeichnet jede Lambda-Entscheidung der Laufzeit auf - im Saison- UND
    im Einzelspielpfad. Beide importieren resolve_simulation_lambdas
    unter eigenem Namen; genau diese Namen werden umgelenkt.
    """
    from src.predict import cl_match_sim as cms
    from src.predict import cl_season_sim as css

    protokoll = []
    echt = css.resolve_simulation_lambdas

    def spion(*a, **kw):
        ergebnis = echt(*a, **kw)
        hp = kw.get("home_profile") or {}
        ap = kw.get("away_profile") or {}
        protokoll.append({
            "home_id": hp.get("team_id"), "away_id": ap.get("team_id"),
            "lambda_home": ergebnis["lambda_home"],
            "lambda_away": ergebnis["lambda_away"],
            "applied": ergebnis["ml_applied_to_production"],
            "model_id": ergebnis.get("model_id"),
            "league_stage": (ergebnis.get("league_stage") or {}).get(
                "status")})
        return ergebnis

    css.resolve_simulation_lambdas = spion
    cms.resolve_simulation_lambdas = spion
    try:
        yield protokoll
    finally:
        css.resolve_simulation_lambdas = echt
        cms.resolve_simulation_lambdas = echt


def _plan_pruefen(plan, stichtag):
    befunde = []
    if len(plan["fixtures"]) != 144:
        befunde.append("Partien %d statt 144" % len(plan["fixtures"]))
    je_team = collections.Counter()
    for f in plan["fixtures"]:
        je_team[f["home_id"]] += 1
        je_team[f["away_id"]] += 1
    if len(je_team) != 36 or set(je_team.values()) != {8}:
        befunde.append("nicht 36 Vereine mit je 8 Partien")
    if len(plan["finished_matches"]) + len(plan["remaining_matches"]) != 144:
        befunde.append("bekannt plus offen ungleich 144")
    grenze = stichtag.date().isoformat()
    if any(m["utc_date"] >= grenze for m in plan["finished_matches"]):
        befunde.append("bekanntes Ergebnis am oder nach dem Stichtag")
    if any(m["utc_date"] < grenze for m in plan["remaining_matches"]):
        befunde.append("offene Partie vor dem Stichtag")
    return befunde


def _stichtag_pruefen(staerken, stichtag):
    """Keine CL-Partie der Profilquelle darf am Stichtag oder danach liegen."""
    herkunft = staerken.get("provenance") or {}
    bis = (herkunft.get("matches_through_date")
           or herkunft.get("matches_through"))
    if bis and str(bis)[:10] >= stichtag.date().isoformat():
        return ["CL-Profilquelle reicht bis %s, Stichtag %s"
                % (bis, stichtag.isoformat())]
    return []


def run_validation(zeilen=None):
    """
    Die vollstaendige Saisonvalidierung nach dem eingefrorenen Vertrag.

    Rueckgabe: das Ergebnisartefakt (ohne Rohdaten).
    """
    from src.features.pit_profiles import PitProfileRepository
    from src.features.strength_provider import get_cl_team_strengths
    from src.ml import c20_temporal_map as c20
    from src.ml import dataset as ds
    from src.ml import model_registry as mr
    from src.predict import cl_match_sim as cms
    from src.predict import cl_season_sim as css

    with open(os.path.join(_repo_root(), CONTRACT_PATH),
              encoding="utf-8") as datei:
        eingefroren = json.load(datei)
    if eingefroren["contract_fingerprint"] != contract_fingerprint():
        raise RuntimeError("Vertrag im Code weicht vom eingefrorenen ab")

    registry_vorher = mr.registry_fingerprint(mr.load_registry())
    modelle_dir = os.path.join(_repo_root(), "data", "ml", "models")
    modelle_vorher = sorted(os.listdir(modelle_dir))

    if zeilen is None:
        zeilen, _d = ds.build_dataset(include_cl=True)
    with open(os.path.join(_repo_root(), c20.EVALUATION_PATH),
              encoding="utf-8") as datei:
        evaluation = json.load(datei)

    repository = PitProfileRepository()
    technik = []
    je_lauf = {}
    paritaet = {"compared": 0, "max_abs_diff": 0.0, "by_cutoff": {}}
    bindung = {}
    stichtag_log = {}

    for saison in SEASONS:
        tatsaechlich, rang_info = actual_table(saison)
        karte = c20.fold_map(fold_for(saison))
        stichtage = cutoffs(saison)
        plaene, staerken = {}, {}
        for name, stichtag in stichtage:
            plan = plan_at(saison, stichtag)
            technik += ["%s %s: %s" % (saison, name, b)
                        for b in _plan_pruefen(plan, stichtag)]
            st = get_cl_team_strengths(season=saison, cutoff=stichtag,
                                       repository=repository)
            technik += ["%s %s: %s" % (saison, name, b)
                        for b in _stichtag_pruefen(st, stichtag)]
            herkunft = st.get("provenance") or {}
            stichtag_log["%s %s" % (saison, name)] = {
                "cutoff": stichtag.isoformat(),
                "known_results": len(plan["finished_matches"]),
                "simulated": len(plan["remaining_matches"]),
                "cl_profile_matches_through": str(
                    herkunft.get("matches_through_date")
                    or herkunft.get("matches_through")),
            }
            plaene[name], staerken[name] = plan, st

        def laufen(modus):
            for name, _stichtag in stichtage:
                for seed in SEEDS:
                    r = css.simulate_cl_league_phase(
                        plaene[name], simulations=SIMULATIONS,
                        season=saison, seed=seed, strengths=staerken[name])
                    je_lauf[(saison, name, modus, seed)] = {
                        "scores": team_scores(r["entries"], tatsaechlich),
                        "ml": r["ml"], "fixtures": r["fixtures_simulated"]}

        with ml_mode("off"):
            laufen("off")

        bundle = fold_bundle(saison, zeilen, evaluation)
        with isolated_activation(bundle, evaluation) as iso:
            aktiv, _g = mr.active_entry()
            fold = fold_for(saison)
            bindung[str(saison)] = {
                "fold": fold["name"],
                "train_seasons": list(fold["train_seasons"]),
                "model_id": bundle["model_id"],
                "active_in_isolated_registry": aktiv["model_id"],
                "isolated_release_status": iso["release"]["status"],
                "gamma": bundle["league_strength"]["gamma"],
                "league_alpha": bundle["league_strength"]["alpha"],
                "base_alpha": bundle["alpha"],
                "team_leagues": len(bundle["league_strength"]["team_leagues"]),
                "map_upto_season": bundle["league_strength"][
                    "team_leagues_provenance"]["upto_season"],
            }
            with ml_mode("active"):
                laufen("active")
                for name, stichtag in stichtage:
                    with _lambda_spion() as saison_log:
                        css.simulate_cl_league_phase(
                            plaene[name], simulations=1, season=saison,
                            seed=0, strengths=staerken[name])
                    with _lambda_spion() as einzel_log:
                        for f in plaene[name]["remaining_matches"]:
                            cms.simulate_cl_league_phase_match(
                                str(f["home_id"]), str(f["away_id"]),
                                home_id=f["home_id"], away_id=f["away_id"],
                                season=saison, simulations=1,
                                use_seed=True, kickoff=stichtag)
                    s_map = {(e["home_id"], e["away_id"]): e
                             for e in saison_log}
                    maxd, vergl = 0.0, 0
                    for e in einzel_log:
                        s = s_map.get((e["home_id"], e["away_id"]))
                        if s is None:
                            technik.append(
                                "%s %s: Partie %s-%s fehlt im Saisonpfad"
                                % (saison, name, e["home_id"], e["away_id"]))
                            continue
                        vergl += 1
                        maxd = max(maxd,
                                   abs(s["lambda_home"] - e["lambda_home"]),
                                   abs(s["lambda_away"] - e["lambda_away"]))
                        if (s["model_id"] != bundle["model_id"]
                                or e["model_id"] != bundle["model_id"]):
                            technik.append("%s %s: Modell-ID weicht ab"
                                           % (saison, name))
                    offen = len(plaene[name]["remaining_matches"])
                    if vergl != offen:
                        technik.append("%s %s: %d von %d Partien verglichen"
                                       % (saison, name, vergl, offen))
                    if maxd > PARITY_TOLERANCE:
                        technik.append("%s %s: Paritaet %.3e"
                                       % (saison, name, maxd))
                    paritaet["compared"] += vergl
                    paritaet["max_abs_diff"] = max(paritaet["max_abs_diff"],
                                                   maxd)
                    paritaet["by_cutoff"]["%s %s" % (saison, name)] = {
                        "compared": vergl, "max_abs_diff": maxd}

        je_lauf[(saison, "_actual")] = {"table": tatsaechlich,
                                        "ranking": rang_info,
                                        "fold_map": karte}

    if mr.registry_fingerprint(mr.load_registry()) != registry_vorher:
        technik.append("echte Registry veraendert")
    if sorted(os.listdir(modelle_dir)) != modelle_vorher:
        technik.append("echtes Modellverzeichnis veraendert")

    ergebnis = _auswerten(je_lauf, technik, paritaet, bindung)
    ergebnis["cutoff_log"] = stichtag_log
    return ergebnis


def _mittel_ueber_seeds(je_lauf, saison, name, modus):
    """Vereinswerte, ueber die Seeds gemittelt."""
    teams = list(je_lauf[(saison, name, modus, SEEDS[0])]["scores"])
    heraus = {}
    for t in teams:
        werte = [je_lauf[(saison, name, modus, s)]["scores"][t]
                 for s in SEEDS]
        zeile = {}
        for k in werte[0]:
            if isinstance(werte[0][k], (int, float)) and not isinstance(
                    werte[0][k], bool):
                zeile[k] = sum(w[k] for w in werte) / len(werte)
            else:
                zeile[k] = werte[0][k]
        heraus[t] = zeile
    return heraus


def _auswerten(je_lauf, technik, paritaet, bindung):
    stichtag_namen = [n for n, _c in cutoffs(SEASONS[0])]
    tabellen = {}
    for saison in SEASONS:
        for name in stichtag_namen:
            for modus in ("off", "active"):
                tabellen[(saison, name, modus)] = _mittel_ueber_seeds(
                    je_lauf, saison, name, modus)

    def pool(namen, modus, metrik):
        werte = []
        for saison in SEASONS:
            for name in namen:
                werte += [v[metrik] for v in
                          tabellen[(saison, name, modus)].values()]
        return sum(werte) / len(werte)

    a = ["A_season_start"]
    b = [n for n in stichtag_namen if n.startswith("B_")]

    def delta(namen, metrik):
        return pool(namen, "active", metrik) - pool(namen, "off", metrik)

    je_seed = []
    for seed in SEEDS:
        v2 = [x["zone_rps"] for s in SEASONS for x in
              je_lauf[(s, "A_season_start", "active", seed)][
                  "scores"].values()]
        v0 = [x["zone_rps"] for s in SEASONS for x in
              je_lauf[(s, "A_season_start", "off", seed)]["scores"].values()]
        je_seed.append(sum(v2) / len(v2) - sum(v0) / len(v0))

    je_saison = {}
    for saison in SEASONS:
        v2 = tabellen[(saison, "A_season_start", "active")]
        v0 = tabellen[(saison, "A_season_start", "off")]
        je_saison[str(saison)] = (
            sum(v["zone_rps"] for v in v2.values()) / len(v2)
            - sum(v["zone_rps"] for v in v0.values()) / len(v0))

    auswertung = {
        "delta_primary_pooled": delta(a, "zone_rps"),
        "delta_primary_by_season": je_saison,
        "delta_updated_pooled": delta(b, "zone_rps"),
        "delta_brier_top8": delta(a, "brier_top8"),
        "delta_brier_top24": delta(a, "brier_top24"),
        "delta_primary_by_seed": je_seed,
        "technical_ok": not technik,
        "technical_findings": technik,
    }
    urteil = decide(auswertung)

    differenzen = [[tabellen[(s, "A_season_start", "active")][t]["zone_rps"]
                    - tabellen[(s, "A_season_start", "off")][t]["zone_rps"]
                    for t in tabellen[(s, "A_season_start", "off")]]
                   for s in SEASONS]

    uebersicht = {}
    for saison in SEASONS:
        for name in stichtag_namen:
            for modus in ("off", "active"):
                zus = summarise(tabellen[(saison, name, modus)])
                seeds = [summarise(je_lauf[(saison, name, modus, s)]["scores"])
                         for s in SEEDS]
                zus["seed_range_zone_rps"] = (
                    max(x["zone_rps"] for x in seeds)
                    - min(x["zone_rps"] for x in seeds))
                zus["ml"] = je_lauf[(saison, name, modus, SEEDS[0])]["ml"]
                uebersicht["%s|%s|%s" % (saison, name, modus)] = zus

    risiko = {}
    for liga in ("PD", "SA"):
        werte = collections.defaultdict(list)
        for saison in SEASONS:
            karte = je_lauf[(saison, "_actual")]["fold_map"]
            v2 = tabellen[(saison, "A_season_start", "active")]
            v0 = tabellen[(saison, "A_season_start", "off")]
            for t in v0:
                if karte.get(t) != liga:
                    continue
                werte["d_rps"].append(v2[t]["zone_rps"] - v0[t]["zone_rps"])
                werte["d_points_err"].append(
                    v2[t]["points_abs_error"] - v0[t]["points_abs_error"])
                werte["d_expected_points"].append(
                    v2[t]["expected_points"] - v0[t]["expected_points"])
                werte["actual_minus_v2_points"].append(
                    v2[t]["actual_points"] - v2[t]["expected_points"])
                werte["actual_minus_v0_points"].append(
                    v0[t]["actual_points"] - v0[t]["expected_points"])
        n = len(werte["d_rps"])
        mittel = lambda k: (sum(werte[k]) / n) if n else None
        risiko[liga] = {
            "team_seasons": n,
            "interpretable": n >= _segment_min_size(),
            "mean_delta_zone_rps": mittel("d_rps"),
            "mean_delta_points_abs_error": mittel("d_points_err"),
            "mean_v2_minus_v0_expected_points": mittel("d_expected_points"),
            "mean_actual_minus_v2_points": mittel("actual_minus_v2_points"),
            "mean_actual_minus_v0_points": mittel("actual_minus_v0_points"),
        }

    vereine = {}
    for saison in SEASONS:
        for t, ist in je_lauf[(saison, "_actual")]["table"].items():
            v0 = tabellen[(saison, "A_season_start", "off")][t]
            v2 = tabellen[(saison, "A_season_start", "active")][t]
            vereine.setdefault(str(saison), []).append({
                "team_id": t,
                "league": je_lauf[(saison, "_actual")]["fold_map"].get(t),
                "actual_position": ist["position"],
                "actual_points": ist["points"],
                "v0_expected_points": round(v0["expected_points"], 2),
                "v2_expected_points": round(v2["expected_points"], 2),
                "v0_expected_position": round(v0["expected_position"], 2),
                "v2_expected_position": round(v2["expected_position"], 2),
                "v0_p_zones": v0["p_zones"], "v2_p_zones": v2["p_zones"],
                "v0_zone_rps": round(v0["zone_rps"], 5),
                "v2_zone_rps": round(v2["zone_rps"], 5),
            })

    return {
        "artifact": "v2-c21 season validation",
        "schema_version": CONTRACT_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "contract_fingerprint": contract_fingerprint(),
        "decision": urteil,
        "summary": uebersicht,
        "bootstrap_primary": paired_bootstrap(differenzen),
        "risk_diagnostics": risiko,
        "parity": paritaet,
        "binding": bindung,
        "actual_tables": {str(s): je_lauf[(s, "_actual")]["ranking"]
                          for s in SEASONS},
        "teams_season_start": vereine,
        "technical_findings": technik,
    }


# ---------------------------------------------------------------------------
# Die Saisonfreigabe als Nachweis im Freigabeweg (V2-C22)
# ---------------------------------------------------------------------------

def _lesen(wurzel, relativ):
    pfad = os.path.join(wurzel, relativ)
    if not os.path.isfile(pfad):
        return None, "fehlt: %s" % relativ
    try:
        with open(pfad, encoding="utf-8") as datei:
            return json.load(datei), None
    except (OSError, ValueError):
        return None, "ist unlesbar: %s" % relativ


def release_evidence(zeilen, evaluation, repo_root=None):
    """
    Traegt die C21-Saisonfreigabe GENAU diesen Modellstand?

    Bis C21 war das eine Voraussetzung im Runbook. Der Freigabeweg
    selbst las nur die C20-Match-Messung; ein fehlendes, abgelehntes
    oder zu einem anderen Stand gehoerendes Saisonartefakt haette die
    Freigabe nicht verhindert.

    Geprueft wird, billig zuerst:
      - Vertrag und Ergebnis liegen vor und sind lesbar,
      - der eingefrorene Vertrag gleicht dem im Code, und er wurde vor
        dem Ergebnis eingefroren,
      - das Ergebnis ist an diesen Vertrag gebunden, `accepted`, jede
        der sechs Bedingungen erfuellt, keine technischen Befunde,
      - der Vertrag bindet denselben Zuordnungsvertrag wie die
        C20-Messung, die das Bundle tragen wird,
    und zuletzt die eigentliche Modellbindung:
      - beide Foldmodelle, auf denen C21 gemessen hat, entstehen aus
        denselben Daten und derselben C20-Messung bitgleich wieder. Die
        Modell-ID bezieht Daten, Koeffizienten, Messung und zweite Stufe
        ein; ein Ergebnis, das zu einem anderen Stand gehoert, faellt
        hier auf.

    Der eingefrorene Vertrag wird nicht veraendert; diese Funktion ist
    kein Teil von contract().

    Rueckgabe: (ok, befunde, bericht).
    """
    from src.ml import c20_temporal_map as c20

    wurzel = repo_root or _repo_root()
    befunde = []
    vertrag, fehler_v = _lesen(wurzel, CONTRACT_PATH)
    ergebnis, fehler_e = _lesen(wurzel, RESULT_PATH)
    if fehler_v:
        befunde.append("das C21-Vertragsartefakt %s" % fehler_v)
    if fehler_e:
        befunde.append("das C21-Ergebnis %s" % fehler_e)
    if befunde:
        return False, befunde, {}

    code_fp = contract_fingerprint()
    if vertrag.get("contract_fingerprint") != code_fp:
        befunde.append("der eingefrorene C21-Vertrag gleicht nicht dem "
                       "Vertrag im Code")
    if vertrag.get("frozen_before_measurement") is not True:
        befunde.append("der C21-Vertrag ist nicht als vor der Messung "
                       "eingefroren ausgewiesen")
    if (ergebnis.get("artifact") != "v2-c21 season validation"
            or ergebnis.get("schema_version") != CONTRACT_VERSION):
        befunde.append("das C21-Ergebnis hat nicht die erwartete Fassung")
    urteil = ergebnis.get("decision") or {}
    if (ergebnis.get("contract_fingerprint") != code_fp
            or urteil.get("contract_fingerprint") != code_fp):
        befunde.append("das C21-Ergebnis ist nicht an den geltenden "
                       "C21-Vertrag gebunden")
    if urteil.get("verdict") != "accepted":
        befunde.append("das C21-Urteil lautet %r, nicht accepted"
                       % urteil.get("verdict"))
    bedingungen = urteil.get("conditions") or {}
    erwartet = set(contract()["gates"])
    if (urteil.get("failed_conditions")
            or set(bedingungen) != erwartet
            or not all(v is True for v in bedingungen.values())):
        befunde.append("nicht alle C21-Bedingungen S1 bis S6 sind erfuellt")
    if ergebnis.get("technical_findings"):
        befunde.append("das C21-Ergebnis traegt technische Befunde")
    eingefroren, entstanden = vertrag.get("created_at"), ergebnis.get(
        "created_at")
    if not (eingefroren and entstanden and str(eingefroren)
            < str(entstanden)):
        befunde.append("der C21-Vertrag wurde nicht nachweislich vor dem "
                       "Ergebnis eingefroren")
    karte = ((vertrag.get("contract") or {}).get("models") or {}).get(
        "map_contract_fingerprint")
    if (karte != c20.contract_fingerprint()
            or karte != (evaluation.get("map_contract") or {}).get(
                "contract_fingerprint")):
        befunde.append("C21 wurde nicht unter demselben Zuordnungsvertrag "
                       "gemessen wie die C20-Messung")
    if befunde:
        return False, befunde, {}

    bindung = ergebnis.get("binding") or {}
    gebaut = {}
    for saison in SEASONS:
        eintrag = bindung.get(str(saison)) or {}
        fold = fold_for(saison)
        if (eintrag.get("isolated_release_status") != "applied"
                or not eintrag.get("model_id")
                or eintrag.get("active_in_isolated_registry")
                != eintrag.get("model_id")):
            befunde.append("Saison %s: das gemessene Foldmodell war nicht "
                           "nachweislich aktiv" % saison)
            continue
        if (list(eintrag.get("train_seasons") or [])
                != list(fold["train_seasons"])
                or eintrag.get("map_upto_season") != c20.fold_upto(fold)):
            befunde.append("Saison %s: Trainingssaisons oder Kartengrenze "
                           "passen nicht zum Fold" % saison)
            continue
        try:
            neu = fold_bundle(saison, zeilen, evaluation)["model_id"]
        except Exception as fehler:                      # fail-closed
            befunde.append("Saison %s: das Foldmodell ist nicht baubar: %s"
                           % (saison, fehler))
            continue
        gebaut[str(saison)] = neu
        if neu != eintrag["model_id"]:
            befunde.append("Saison %s: C21 mass %s, derselbe Stand baut %s"
                           % (saison, eintrag["model_id"], neu))

    return (not befunde), befunde, {
        "verdict": urteil.get("verdict"),
        "contract_fingerprint": code_fp,
        "result_created_at": entstanden,
        "fold_models": [gebaut.get(str(s), "-") for s in SEASONS],
    }
