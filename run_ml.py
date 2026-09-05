"""
CLI fuer die ML-Vorbereitung.

AUFRUF
------
    py run_ml.py --build-dataset
    py run_ml.py --build-dataset --output data/ml/dataset_2023-2025.json
    py run_ml.py --evaluate
    py run_ml.py --evaluate --output data/ml/shadow_eval.json
    py run_ml.py --ablate
    py run_ml.py --ablate --output data/ml/ablation_2023-2025.json
    py run_ml.py --diagnose
    py run_ml.py --diagnose --output data/ml/ablation_diagnostics.json

Vier Aufgaben, je Lauf eine: den Datensatz bauen, das Korrekturmodell
im Schatten auswerten, die Merkmalsgruppen gegeneinander abloesen oder
die zweite Diagnosestufe fahren.

--ablate beantwortet, WOHER die gemessene Verbesserung kommt - aus den
Profilmerkmalen, aus denen die Baseline ohnehin schon rechnet, oder aus
den Belastungsmerkmalen, die sie nicht kennt.

--diagnose setzt dort an, wo die erste Stufe endete. Sie hatte gezeigt,
dass alles aus profile_only stammt, aber nicht, WAS daran wirkt.
Deshalb zerlegt die zweite Stufe diese Menge weiter: ein blosser
Achsenabschnitt, der Ligadurchschnitt allein, die Teamprofile allein.
Dazu kommen gepaarte Vergleiche ZWISCHEN den Varianten - die
Intervalle gegen die Baseline koennen ueberlappen, obwohl die gepaarte
Differenz eindeutig ist.

Beide benutzen dasselbe Walk-forward-Verfahren wie --evaluate und
veraendern daran nichts.

SCHATTEN heisst SCHATTEN. Die Auswertung trainiert offline, misst gegen
die Baseline und schreibt eine JSON-Datei. Sie veraendert nichts an der
API, am Frontend oder am produktiven Simulationspfad, und sie aktiviert
kein Modell. GO3, GO4 und GO5 bleiben unberuehrt.

Ohne --output schreibt das Skript keine Datei, sondern fasst zusammen.
Mit --output schreibt es nur, wenn das Ziel frei ist oder --force
ausdruecklich gesetzt wurde.
"""

import argparse
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Git-Angaben aus dem Backtestlaeufer wiederverwenden. Zwei Fassungen
# derselben Funktion wuerden auseinanderlaufen, und genau dieses Feld
# musste im Backtestlaeufer bereits einmal korrigiert werden.
from run_backtests import git_arbeitsstand, git_commit  # noqa: E402
from src.ml import ablation as ab  # noqa: E402
from src.ml import cl_evaluate as cle  # noqa: E402
from src.ml import dataset as ds  # noqa: E402
from src.ml import evaluate as ev  # noqa: E402
from src.ml import feature_groups as fg  # noqa: E402
from src.ml import model as mdl  # noqa: E402
from src.ml import persist as ps  # noqa: E402

#: Die Quellen, aus denen der Datensatz entsteht. Ausdruecklich im
#: Manifest, weil die Auswahl eine Entscheidung war: data/player_pool
#: steht in .gitignore und faellt deshalb aus.
DATENQUELLEN = ["data/historical"]


def build_payload(leagues, seasons, min_matchday, zeilen, diagnose):
    """
    Manifest, Schema und Zeilen - getrennt.

    Wie beim Backtestlaeufer: Alles Variable steht im Manifest, damit
    zwei Laeufe an rows und schema vergleichbar bleiben.
    """
    stand = git_arbeitsstand()
    schema = ds.build_schema()

    return {
        "manifest": {
            "schema_version": ds.SCHEMA_VERSION,
            "git_commit": git_commit(),
            "git_dirty": None if stand is None else stand["dirty"],
            "git_status": stand,
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "include_cl": diagnose.get("champions_league") is not None,
            "cl_seasons": ([e["season"] for e in
                            diagnose["champions_league"]["per_season"]]
                           if diagnose.get("champions_league") else []),
            "total_rows": diagnose["total_rows"],
            "evaluation_eligible_rows": diagnose["evaluation_eligible_rows"],
            "warmup_rows": diagnose["warmup_rows"],
            "columns": list(ds.SPALTEN),
            "column_count": len(ds.SPALTEN),
            "data_sources": list(DATENQUELLEN),
            "excluded_sources": ["data/player_pool (gitignored, GO5)"],
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "python_version": platform.python_version(),
            "platform": platform.system(),
        },
        "schema": schema,
        "rows": zeilen,
        "diagnostics": {
            "per_league_season": diagnose["per_league_season"],
            "skipped": diagnose["skipped"],
            "cold_start_rows": diagnose["cold_start_rows"],
            "neutral_profile_rows": diagnose["neutral_profile_rows"],
            "rows_without_outcome": diagnose["rows_without_outcome"],
            "champions_league": diagnose.get("champions_league"),
            "missingness": ds.missingness(zeilen),
        },
    }


def print_summary(payload, kennzahlen, abdeckung):
    m = payload["manifest"]
    d = payload["diagnostics"]

    print()
    print(f"  Ligen            {', '.join(m['leagues'])}")
    print(f"  Saisons          {', '.join(str(s) for s in m['seasons'])}")
    print(f"  min_matchday     {m['min_matchday']}")
    print(f"  Quellen          {', '.join(m['data_sources'])}")
    print(f"  Spalten          {m['column_count']}")

    stand = m.get("git_status")
    if m.get("git_dirty"):
        print(f"  Git              {(m['git_commit'] or '?')[:12]}  DIRTY: "
              f"{len(stand['modified'])} geaendert, "
              f"{len(stand['untracked'])} unversioniert")
    else:
        print(f"  Git              {(m['git_commit'] or '?')[:12]}")

    print()
    print(f"  Zeilen gesamt              {m['total_rows']}")
    print(f"  davon auswertbar           {m['evaluation_eligible_rows']}")
    print(f"  davon Aufwaermphase        {m['warmup_rows']}")
    print(f"  mit Kaltstartprofil        {d['cold_start_rows']}")
    print(f"  mit neutralem Profil       {d['neutral_profile_rows']}")

    print()
    print(f"  {'Liga':6} {'Saison':>7} {'Zeilen':>7} {'auswertbar':>11} "
          f"{'Aufwaerm':>9} {'Kaltstart':>10}")
    for eintrag in d["per_league_season"]:
        print(f"  {eintrag['league']:6} {eintrag['season']:7} "
              f"{eintrag['rows']:7} {eintrag['evaluation_eligible']:11} "
              f"{eintrag['warmup']:9} {eintrag['cold_start_rows']:10}")

    fehlend = {s: n for s, n in d["missingness"].items() if n}
    print()
    if fehlend:
        print("  Spalten mit fehlenden Werten:")
        for spalte, anzahl in sorted(fehlend.items(),
                                     key=lambda p: (-p[1], p[0])):
            anteil = anzahl / m["total_rows"] * 100
            print(f"     {spalte:38} {anzahl:6} ({anteil:5.1f}%)")
    else:
        print("  Keine Spalte hat fehlende Werte.")

    if abdeckung:
        print()
        print("  Crosswalk-Abdeckung der Pokalspiele in der Zeitleiste:")
        print("  (Nenner: ALLE Partien der Datei inkl. Qualifikationsrunden.")
        print("   Amateurpaarungen sind im football-data-ID-Raum nicht")
        print("   vorhanden - das erklaert eine niedrige Quote, belegt aber")
        print("   NICHT, dass keine Erstligapartie fehlt.)")
        print(f"     {'Wettbewerb':12} {'in Dateien':>11} {'zugeordnet':>11} "
              f"{'Abdeckung':>10}")
        for eintrag in abdeckung:
            quote = ("-" if eintrag["coverage"] is None
                     else f"{eintrag['coverage'] * 100:9.1f}%")
            print(f"     {eintrag['competition']:12} "
                  f"{eintrag['matches_in_files']:11} "
                  f"{eintrag['matches_covered']:11} {quote:>10}")

    cl = d.get("champions_league")
    if cl:
        print()
        print(f"  Champions League: {cl['rows']} Zeilen, davon "
              f"{cl['evaluation_eligible']} auswertbar, "
              f"{cl['excluded']} ausgeschlossen")
        print(f"     {'Saison':>7} {'Zeilen':>7} {'auswertbar':>11}   Stages")
        for eintrag in cl["per_season"]:
            stages = ", ".join(f"{k} {v}" for k, v
                               in sorted(eintrag["stages"].items()))
            print(f"     {eintrag['season']:7} {eintrag['rows']:7} "
                  f"{eintrag['evaluation_eligible']:11}   {stages}")
        print()
        print("     Profilherkunft (je Team-Seite, ueber alle CL-Zeilen):")
        gesamt = sum(cl["per_profile_source"].values()) or 1
        for quelle, anzahl in sorted(cl["per_profile_source"].items(),
                                     key=lambda p: -p[1]):
            print(f"        {quelle:18} {anzahl:5}  ({anzahl / gesamt * 100:5.1f}%)")
        print()
        print("     Ausschlussgruende:")
        for grund, anzahl in sorted(cl["exclusion_reasons"].items(),
                                    key=lambda p: -p[1]):
            print(f"        {anzahl:5}  {grund}")

    if kennzahlen:
        # Die bekannten Erwartungswerte gelten fuer den VOLLEN Umfang -
        # fuenf Ligen, drei Saisons. Bei einem Teillauf waeren sie ein
        # falscher Vergleich und werden deshalb nicht angezeigt.
        voll = (sorted(m["leagues"]) == sorted(ds.DEFAULT_LEAGUES)
                and sorted(m["seasons"]) == sorted(ds.DEFAULT_SEASONS))
        print()
        print("  Baseline ueber die auswertbaren Zeilen:")
        print(f"     n         {kennzahlen['n']}"
              f"{'   (erwartet 4380)' if voll else ''}")
        print(f"     LogLoss   {kennzahlen['log_loss']:.5f}"
              f"{'   (erwartet 1.01598)' if voll else ''}")
        print(f"     Brier     {kennzahlen['brier']:.5f}"
              f"{'   (erwartet 0.60821)' if voll else ''}")
        print(f"     RPS       {kennzahlen['rps']:.5f}"
              f"{'   (erwartet 0.20868)' if voll else ''}")


def _manifest(schema_version):
    """
    Der Manifestblock - alles Variable eines Laufes.

    Eine gemeinsame Funktion fuer Auswertung und Ablation, damit die
    Felder nicht in zwei Fassungen auseinanderlaufen. Genau das ist dem
    Feld git_commit im Backtestlaeufer bereits einmal passiert.
    """
    import sklearn

    stand = git_arbeitsstand()
    return {
        "schema_version": schema_version,
        "dataset_schema_version": ds.SCHEMA_VERSION,
        "git_commit": git_commit(),
        "git_dirty": None if stand is None else stand["dirty"],
        "git_status": stand,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "platform": platform.system(),
    }


def build_evaluation_payload(leagues, seasons, min_matchday, zeilen,
                             ergebnis):
    """
    Das Auswertungsartefakt.

    Drei Bloecke, bewusst getrennt:

      manifest       alles Variable - Commit, Uhrzeit, Fassungen. Diese
                     Felder unterscheiden sich zwangslaeufig zwischen
                     zwei Laeufen.
      configuration  alles vorab Festgelegte - Folds, Alphas, Grenzen,
                     Seed. Diese Felder MUESSEN zwischen zwei Laeufen
                     gleich sein.
      results        die Messung.

    Ohne diese Trennung liesse sich nicht unterscheiden, ob zwei Laeufe
    inhaltlich auseinanderlaufen oder nur zu verschiedenen Zeiten
    stattfanden.
    """
    fehlend = ds.missingness(zeilen)

    return {
        "manifest": _manifest(ev.SCHEMA_VERSION),
        "configuration": {
            "mode": "shadow",
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "rows_total": len(zeilen),
            "rows_evaluation_eligible": sum(
                1 for z in zeilen if z["evaluation_eligible"]),
            "data_sources": list(DATENQUELLEN),
            "outer_folds": [dict(f) for f in ev.OUTER_FOLDS],
            "alpha_candidates": list(mdl.ALPHA_CANDIDATES),
            "baseline_candidate": mdl.NO_CORRECTION,
            "tie_break": "unter gleichauf liegenden Alphas gewinnt das "
                         "groessere; gegenueber der Baseline zaehlt nur "
                         "strikte Verbesserung",
            "selection_metric": "innerer H/D/A-LogLoss",
            "correction_clamp": [mdl.CORRECTION_MIN, mdl.CORRECTION_MAX],
            "lambda_clamp": [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX],
            "bootstrap_seed": ev.BOOTSTRAP_SEED,
            "bootstrap_iterations": ev.BOOTSTRAP_ITERATIONS,
            "delta_convention": "delta = ML - Baseline; negativ bedeutet "
                                "ML besser",
            "feature_columns": ergebnis["feature_columns"],
            "feature_count": len(ergebnis["feature_columns"]),
            "excluded_columns": mdl.excluded_columns(),
            "feature_missingness": {spalte: fehlend.get(spalte, 0)
                                    for spalte in ergebnis["feature_columns"]},
        },
        "results": {
            "folds": ergebnis["folds"],
            "aggregate": ergebnis["aggregate"],
        },
    }


def print_evaluation(payload):
    """Die Zusammenfassung auf der Konsole - ehrlich, auch wenn ML verliert."""
    konfiguration = payload["configuration"]
    ergebnis = payload["results"]

    print()
    print(f"  Modus            {konfiguration['mode'].upper()} - kein Modell "
          f"wird aktiviert")
    print(f"  Merkmale         {konfiguration['feature_count']}")
    print(f"  Alphas           {konfiguration['alpha_candidates']} "
          f"+ {konfiguration['baseline_candidate']}")
    print(f"  Vorzeichen       {konfiguration['delta_convention']}")

    for fold in ergebnis["folds"]:
        print()
        if "error" in fold:
            print(f"  {fold['fold']}: {fold['error']}")
            continue

        innen = fold["inner_split"]
        grenze = innen.get("boundary_date")
        print(f"  {fold['fold']}   Training {fold['train_seasons']} "
              f"({fold['train_rows']} Spiele)  ->  Test "
              f"{fold['test_seasons']} ({fold['test_rows']} Spiele)")
        print(f"     innere Wahl    {innen['strategy']}"
              + (f", Grenze {grenze}" if grenze else ""))
        print(f"     gewaehlt       {fold['selected_candidate']}")

        for name in ("log_loss", "brier", "rps"):
            basis = fold["baseline"][name]
            ml = fold["ml"][name]
            print(f"     {name:14} Baseline {basis:.5f}   ML {ml:.5f}   "
                  f"delta {fold[f'delta_{name}']:+.5f}")

        print(f"     Kalibrierung   Baseline "
              f"{fold['baseline']['calibration_error']:.5f}   ML "
              f"{fold['ml']['calibration_error']:.5f}")
        print(f"     Klammerquote   heim "
              f"{fold['clamps']['clamp_rate_home'] * 100:.2f}%   auswaerts "
              f"{fold['clamps']['clamp_rate_away'] * 100:.2f}%")
        print(f"     p-Verschiebung Mittel "
              f"{fold['avg_probability_change']:.5f}   max "
              f"{fold['max_probability_change']:.5f}")

        print(f"     {'Liga':6} {'n':>5} {'Baseline':>10} {'ML':>10} "
              f"{'delta':>10}")
        for eintrag in fold["per_league"]:
            print(f"     {eintrag['league']:6} {eintrag['n']:5} "
                  f"{eintrag['baseline_log_loss']:10.5f} "
                  f"{eintrag['ml_log_loss']:10.5f} "
                  f"{eintrag['delta_log_loss']:+10.5f}")

    zusammen = ergebnis["aggregate"]
    if not zusammen:
        return

    print()
    print(f"  Gesamt ueber {zusammen['n']} Spiele "
          f"(nach Spielen gewichtet, nicht nach Folds gemittelt)")
    for name in ("log_loss", "brier", "rps"):
        intervall = zusammen["bootstrap"][name]
        print(f"     {name:14} Baseline {zusammen['baseline'][name]:.5f}   "
              f"ML {zusammen['ml'][name]:.5f}   "
              f"delta {zusammen[f'delta_{name}']:+.5f}   "
              f"95%-KI [{intervall['ci_low']:+.5f}, "
              f"{intervall['ci_high']:+.5f}]")
    print(f"     Kalibrierung   Baseline "
          f"{zusammen['baseline']['calibration_error']:.5f}   ML "
          f"{zusammen['ml']['calibration_error']:.5f}   "
          f"(gepoolt ueber die zusammengefuehrten Bins)")
    for titel, feld, schluessel in (("Liga", "per_league", "league"),
                                    ("Testsaison", "per_test_season",
                                     "season")):
        print()
        print(f"  Ueber beide Folds, je {titel}:")
        print(f"     {titel:11} {'n':>5} {'Baseline':>10} {'ML':>10} "
              f"{'delta':>10}")
        for eintrag in zusammen[feld]:
            print(f"     {str(eintrag[schluessel]):11} {eintrag['n']:5} "
                  f"{eintrag['baseline_log_loss']:10.5f} "
                  f"{eintrag['ml_log_loss']:10.5f} "
                  f"{eintrag['delta_log_loss']:+10.5f}")

    print()
    print(f"  Deutung: {zusammen['bootstrap']['log_loss']['interpretation']}")


def build_ablation_payload(leagues, seasons, min_matchday, zeilen, ergebnis,
                           varianten=fg.VARIANTS, aufgabe="ablation",
                           paare=()):
    """
    Das Ablationsartefakt - derselbe Dreiklang wie bei der Auswertung.

    configuration traegt ausdruecklich dieselben vorab festgelegten
    Felder wie das Auswertungsartefakt: Folds, Alphas, Clamps, Seed.
    Nur so laesst sich spaeter belegen, dass die Ablation NICHT unter
    anderen Bedingungen gelaufen ist als die Messung, die sie erklaeren
    soll.

    Dieselbe Funktion baut beide Stufen. Zwei Fassungen wuerden
    auseinanderlaufen, und dann waere nicht mehr zu belegen, dass Stufe
    zwei unter denselben Bedingungen lief wie Stufe eins - worauf ihre
    ganze Aussage beruht.

    varianten beschreibt, was gerechnet WURDE, und ergebnis traegt, was
    dabei herauskam. Beide kommen vom Aufrufer, und ein Aufrufer, der
    das Ergebnis der Diagnosestufe mit der Variantenliste der ersten
    Stufe kombiniert, erzeugt ein vollstaendig plausibles, aber falsch
    beschriftetes Artefakt. Deshalb wird der Gleichlauf geprueft, statt
    ihm zu vertrauen.
    """
    gerechnet = [zeile["variant"] for zeile in ergebnis["comparison"]]
    angekuendigt = [v["name"] for v in varianten]
    if gerechnet != angekuendigt:
        raise ValueError(
            f"das Artefakt wuerde {angekuendigt} ankuendigen, gerechnet "
            f"wurde aber {gerechnet}")

    return {
        "manifest": {
            **_manifest(ab.SCHEMA_VERSION),
            "feature_groups_schema_version": fg.SCHEMA_VERSION,
            "evaluation_schema_version": ev.SCHEMA_VERSION,
        },
        "configuration": {
            "mode": "shadow",
            "task": aufgabe,
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "rows_total": len(zeilen),
            "rows_evaluation_eligible": sum(
                1 for z in zeilen if z["evaluation_eligible"]),
            "data_sources": list(DATENQUELLEN),
            "outer_folds": [dict(f) for f in ev.OUTER_FOLDS],
            "alpha_candidates": list(mdl.ALPHA_CANDIDATES),
            "baseline_candidate": mdl.NO_CORRECTION,
            "selection_metric": "innerer H/D/A-LogLoss",
            "selection_scope": "ausschliesslich innerhalb des jeweiligen "
                               "Trainingsfolds - kein Testspiel geht in "
                               "die Wahl ein",
            "correction_clamp": [mdl.CORRECTION_MIN, mdl.CORRECTION_MAX],
            "lambda_clamp": [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX],
            "bootstrap_seed": ev.BOOTSTRAP_SEED,
            "bootstrap_iterations": ev.BOOTSTRAP_ITERATIONS,
            "delta_convention": "delta = ML - Baseline; negativ bedeutet "
                                "ML besser",
            "variant_order": [v["name"] for v in varianten],
            "variants": [dict(v) for v in varianten],
            "paired_comparisons": [{"variant": a, "reference": b}
                                   for a, b in paare],
            "feature_groups": ergebnis["feature_groups"],
            "excluded_columns": mdl.excluded_columns(),
        },
        "results": {
            "comparison": ergebnis["comparison"],
            "attribution": ergebnis["attribution"],
            "paired_comparisons": ergebnis["paired_comparisons"],
            "test_match_count": ergebnis["test_match_count"],
            "variants": ergebnis["variants"],
        },
    }


def print_ablation(payload):
    """Die Ablation auf der Konsole - vollstaendig, auch wo nichts wirkt."""
    konfiguration = payload["configuration"]
    ergebnis = payload["results"]
    gruppen = konfiguration["feature_groups"]

    print()
    print(f"  Modus            {konfiguration['mode'].upper()} - kein Modell "
          f"wird aktiviert")
    print(f"  Verfahren        unveraendert: {len(konfiguration['outer_folds'])} "
          f"aeussere Folds, Alphawahl {konfiguration['selection_scope']}")
    print(f"  Vorzeichen       {konfiguration['delta_convention']}")

    print()
    print("  Merkmalsgruppen:")
    for name in gruppen["group_order"]:
        print(f"     {name:19} {gruppen['counts'][name]:3} Merkmale")
        nicht = gruppen["not_modelled"].get(name) or []
        for eintrag in nicht:
            print(f"        nicht modelliert: {eintrag['column']} "
                  f"({eintrag['reason']})")
    print(f"     {'summe':19} {gruppen['total_model_features']:3} Merkmale "
          f"- vollstaendige, ueberschneidungsfreie Zerlegung")

    for variante in ergebnis["variants"]:
        print()
        print(f"  {variante['variant']}   ({variante['feature_count']} "
              f"Merkmale)")
        print(f"     {variante['description']}")
        for eintrag in variante["selected_candidates"]:
            print(f"     {eintrag['fold']}: gewaehlt {eintrag['selected']}")
        for fold in variante["folds"]:
            if "error" in fold:
                print(f"     {fold['fold']}: {fold['error']}")
                continue
            print(f"     {fold['fold']}  Test {fold['test_seasons']} "
                  f"({fold['test_rows']} Spiele)   "
                  f"LogLoss {fold['ml']['log_loss']:.5f}   "
                  f"delta {fold['delta_log_loss']:+.5f}")

    print()
    print("  Vergleich ueber beide Folds (nach Spielen gewichtet):")
    print(f"     {'Variante':23} {'n':>5} {'Merkm':>6} {'LogLoss':>9} "
          f"{'dLogLoss':>10} {'dBrier':>10} {'dRPS':>10} "
          f"{'95%-KI LogLoss':>24}")
    for zeile in ergebnis["comparison"]:
        intervall = (f"[{zeile['log_loss_ci_low']:+.5f}, "
                     f"{zeile['log_loss_ci_high']:+.5f}]"
                     if "log_loss_ci_low" in zeile else "-")
        print(f"     {zeile['variant']:23} {zeile['n']:5} "
              f"{zeile['feature_count']:6} {zeile['ml_log_loss']:9.5f} "
              f"{zeile['delta_log_loss']:+10.5f} "
              f"{zeile['delta_brier']:+10.5f} "
              f"{zeile['delta_rps']:+10.5f} {intervall:>24}")

    print()
    print("  Je Liga, ueber beide Folds (delta LogLoss):")
    ligen = sorted({eintrag["league"]
                    for variante in ergebnis["variants"]
                    if variante.get("aggregate")
                    for eintrag in variante["aggregate"]["per_league"]})
    kopf = "".join(f"{liga:>12}" for liga in ligen)
    print(f"     {'Variante':23}{kopf}")
    for variante in ergebnis["variants"]:
        zusammen = variante.get("aggregate")
        if not zusammen:
            continue
        nach_liga = {e["league"]: e["delta_log_loss"]
                     for e in zusammen["per_league"]}
        werte = "".join(f"{nach_liga[liga]:+12.5f}" if liga in nach_liga
                        else f"{'-':>12}" for liga in ligen)
        print(f"     {variante['variant']:23}{werte}")

    print()
    print("  Je Testsaison, ueber beide Folds (delta LogLoss):")
    saisons = sorted({eintrag["season"]
                      for variante in ergebnis["variants"]
                      if variante.get("aggregate")
                      for eintrag in variante["aggregate"]["per_test_season"]})
    kopf = "".join(f"{saison:>12}" for saison in saisons)
    print(f"     {'Variante':23}{kopf}")
    for variante in ergebnis["variants"]:
        zusammen = variante.get("aggregate")
        if not zusammen:
            continue
        nach_saison = {e["season"]: e["delta_log_loss"]
                       for e in zusammen["per_test_season"]}
        werte = "".join(f"{nach_saison[s]:+12.5f}" if s in nach_saison
                        else f"{'-':>12}" for s in saisons)
        print(f"     {variante['variant']:23}{werte}")

    _print_koeffizienten(ergebnis["variants"])
    _print_paarvergleiche(ergebnis.get("paired_comparisons") or [])

    zuordnung = ergebnis.get("attribution")
    if zuordnung:
        print()
        print(f"  Anteil am Delta von {zuordnung['reference']} "
              f"({zuordnung['reference_delta_log_loss']:+.5f}):")
        for eintrag in (zuordnung.get("shares") or []):
            anteil = eintrag["share_of_reference"]
            print(f"     {eintrag['variant']:23} "
                  f"{eintrag['delta_log_loss']:+.5f}   "
                  + (f"{anteil * 100:6.1f}%" if anteil is not None else "-"))
        print(f"     {zuordnung['note']}")


def _print_paarvergleiche(vergleiche):
    """
    Die gepaarten Vergleiche ZWISCHEN Varianten.

    Sie beantworten, was zwei Intervalle gegen die Baseline nicht
    beantworten koennen: ob sich zwei Varianten voneinander
    unterscheiden. Ueberlappende Intervalle gegen die Baseline sind
    kein Gegenbeweis - die gepaarte Differenz kann trotzdem eindeutig
    sein.
    """
    if not vergleiche:
        return

    print()
    print("  Gepaarte Vergleiche zwischen Varianten "
          "(delta = erste - zweite, negativ heisst erste besser):")
    print(f"     {'Variante':23} {'gegen':23} {'n':>5} {'delta':>10} "
          f"{'95%-KI':>24}   Deutung")
    for eintrag in vergleiche:
        intervall = eintrag.get("bootstrap")
        if not intervall:
            print(f"     {eintrag['variant']:23} {eintrag['reference']:23} "
                  f"{eintrag['n']:5}   kein Intervall")
            continue
        spanne = (f"[{intervall['ci_low']:+.5f}, "
                  f"{intervall['ci_high']:+.5f}]")
        print(f"     {eintrag['variant']:23} {eintrag['reference']:23} "
              f"{eintrag['n']:5} {eintrag['delta_log_loss']:+10.5f} "
              f"{spanne:>24}   {intervall['interpretation']}")


def _print_koeffizienten(varianten, anzahl=5):
    """
    Die staerksten Koeffizienten je Variante und Seite.

    Sie beziehen sich auf SKALIERTE Merkmale - ein Koeffizient ist die
    Wirkung einer Standardabweichung, nicht einer Einheit. Und er
    beschreibt einen beobachteten Zusammenhang, keine Ursache.
    """
    print()
    print(f"  Staerkste Koeffizienten je Variante (letzter Fold, "
          f"skalierte Merkmale, |Wert| absteigend, max. {anzahl}):")
    for variante in varianten:
        gefunden = [fold for fold in variante["folds"]
                    if fold.get("coefficients")]
        if not gefunden:
            print(f"     {variante['variant']:23} kein Modell angepasst "
                  f"(no_correction gewaehlt)")
            continue

        fold = gefunden[-1]
        print(f"     {variante['variant']} ({fold['fold']}):")
        for seite in ("home", "away"):
            werte = fold["coefficients"][seite]
            paare = sorted(werte["by_feature"],
                           key=lambda p: -abs(p["coefficient"]))[:anzahl]
            # Ein merkmalsfreies Modell hat Koeffizienten, aber keine
            # zu Merkmalen. Ohne diesen Zweig stuende hier eine leere
            # Zeile - und die liest sich wie ein Fehler, obwohl der
            # Achsenabschnitt genau das Ergebnis IST.
            text = ("   ".join(f"{p['feature']} {p['coefficient']:+.4f}"
                               for p in paare) if paare
                    else f"nur Achsenabschnitt {werte['intercept']:+.4f} "
                         f"(Faktor {math.exp(werte['intercept']):.4f})")
            print(f"        {seite:5} {text}")



def load_dataset_rows(pfad):
    """
    Zeilen aus einem vorhandenen Datensatzartefakt.

    Der Weg ueber eine Datei ist die ausdrueckliche Alternative zum Bau
    im Prozess: Er erlaubt, einen genau bekannten Bestand erneut zu
    bewerten, statt ihn jedes Mal neu abzuleiten.
    """
    with open(pfad, encoding="utf-8") as datei:
        payload = json.load(datei)

    zeilen = payload.get("rows")
    if not zeilen:
        raise ValueError(f"{pfad} enthaelt keine Zeilen")

    fassung = (payload.get("manifest") or {}).get("schema_version")
    if fassung != ds.SCHEMA_VERSION:
        raise ValueError(
            f"{pfad} traegt Datensatzfassung {fassung}, erwartet wird "
            f"{ds.SCHEMA_VERSION} - die Spalten waeren nicht dieselben")
    if not [z for z in zeilen if z.get("league") == "cl"]:
        raise ValueError(
            f"{pfad} enthaelt keine CL-Zeilen - mit --include-cl bauen")
    return zeilen


def build_cl_evaluation_payload(leagues, seasons, min_matchday, zeilen,
                                ergebnis, quelle):
    """
    Das Artefakt des CL-Shadow-Backtests.

    Derselbe Dreiklang wie bei den uebrigen Aufgaben. configuration
    traegt alles vorab Festgelegte - Folds, Kandidat, Merkmalsliste,
    Alphas, Seed und die Urteilsregeln. Nur so laesst sich spaeter
    belegen, dass die Regeln VOR dem Ergebnis standen.
    """
    return {
        "manifest": {
            **_manifest(cle.SCHEMA_VERSION),
            "evaluation_schema_version": ev.SCHEMA_VERSION,
            "feature_groups_schema_version": fg.SCHEMA_VERSION,
            "dataset_fingerprint": cle.dataset_fingerprint(zeilen),
            "dataset_source": quelle,
        },
        "configuration": {
            "mode": "shadow",
            "task": "cl_shadow_backtest",
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "data_sources": list(DATENQUELLEN),
            "candidate": ergebnis["candidate"],
            "candidate_fixed_before_run": True,
            "feature_columns": ergebnis["feature_columns"],
            "feature_count": ergebnis["feature_count"],
            "outer_folds": [dict(f) for f in cle.OUTER_FOLDS],
            "seasons_without_training_fold": list(
                cle.SEASONS_WITHOUT_TRAINING),
            "training_scope": "ausschliesslich nationale Ligazeilen",
            "test_scope": "ausschliesslich auswertbare CL-Zeilen "
                          "(regulaere Phase)",
            "alpha_candidates": list(mdl.ALPHA_CANDIDATES),
            "baseline_candidate": mdl.NO_CORRECTION,
            "selection_metric": "innerer H/D/A-LogLoss",
            "selection_scope": "innere zeitliche Teilung der Ligadaten - "
                               "kein CL-Spiel geht in die Wahl ein",
            "correction_clamp": [mdl.CORRECTION_MIN, mdl.CORRECTION_MAX],
            "lambda_clamp": [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX],
            "bootstrap_seed": ev.BOOTSTRAP_SEED,
            "bootstrap_iterations": ev.BOOTSTRAP_ITERATIONS,
            "delta_convention": "delta = ML - Baseline; negativ bedeutet "
                                "ML besser",
            "min_reliable_n": cle.MIN_RELIABLE_N,
            "depth_bins": [list(b) for b in cle.DEPTH_BINS],
            "decision_rules": ergebnis["verdict"]["criteria"],
        },
        "results": {
            "folds": ergebnis["folds"],
            "aggregate": ergebnis["aggregate"],
            "exclusions": ergebnis["exclusions"],
            "verdict": ergebnis["verdict"],
        },
    }


def print_cl_evaluation(payload):
    """Der CL-Backtest auf der Konsole - ehrlich, auch wenn ML verliert."""
    k = payload["configuration"]
    r = payload["results"]

    print()
    print(f"  Modus            {k['mode'].upper()} - kein Modell wird "
          f"aktiviert")
    print(f"  Kandidat         {k['candidate']} ({k['feature_count']} "
          f"Merkmale, vorab festgelegt)")
    print(f"  Training         {k['training_scope']}")
    print(f"  Test             {k['test_scope']}")
    print(f"  Alphawahl        {k['selection_scope']}")
    print(f"  Vorzeichen       {k['delta_convention']}")

    aus = r["exclusions"]
    print()
    print(f"  CL-Zeilen geladen {aus['cl_rows_loaded']}, auswertbar "
          f"{aus['cl_rows_eligible']}, ausgeschlossen "
          f"{aus['cl_rows_excluded']}")
    for grund, anzahl in sorted(aus["exclusion_reasons"].items(),
                                key=lambda p: -p[1]):
        print(f"     {anzahl:5}  {grund}")
    for saison, anzahl in aus["seasons_without_training_fold"].items():
        print(f"     {anzahl:5}  CL {saison}: keine frueher liegende "
              f"Trainingssaison - nicht als Fold verwendet")

    for fold in r["folds"]:
        print()
        if "error" in fold:
            print(f"  {fold['fold']}: {fold['error']}")
            continue
        print(f"  {fold['fold']}   Training Liga {fold['train_seasons']} "
              f"({fold['train_rows']} Spiele)  ->  Test CL "
              f"{fold['test_season']} ({fold['test_rows']} Spiele)")
        print(f"     innere Wahl    {fold['inner_split']['strategy']}")
        print(f"     gewaehlt       {fold['selected_candidate']}")
        for name in ("log_loss", "brier", "rps"):
            print(f"     {name:14} Baseline {fold['baseline'][name]:.5f}   "
                  f"ML {fold['ml'][name]:.5f}   "
                  f"delta {fold[f'delta_{name}']:+.5f}")
        print(f"     Klammerquote   heim "
              f"{fold['clamps']['clamp_rate_home'] * 100:.2f}%   auswaerts "
              f"{fold['clamps']['clamp_rate_away'] * 100:.2f}%")
        roh = fold["clamps"].get("raw_factor_home")
        if roh:
            weg = fold["clamps"]["raw_factor_away"]
            print(f"     Korrekturfaktor heim  min {roh['min']:.3f} "
                  f"median {roh['median']:.3f} max {roh['max']:.3f}")
            print(f"     Korrekturfaktor gast  min {weg['min']:.3f} "
                  f"median {weg['median']:.3f} max {weg['max']:.3f}")
        mw = fold["mean_probabilities"]
        print(f"     mittlere p     Baseline H/D/A "
              f"{mw['baseline']['home']:.3f}/{mw['baseline']['draw']:.3f}/"
              f"{mw['baseline']['away']:.3f}   ML "
              f"{mw['ml']['home']:.3f}/{mw['ml']['draw']:.3f}/"
              f"{mw['ml']['away']:.3f}   beobachtet "
              f"{mw['observed']['home']:.3f}/{mw['observed']['draw']:.3f}/"
              f"{mw['observed']['away']:.3f}")

    z = r["aggregate"]
    if not z:
        print("\n  Kein auswertbarer Fold.")
        return

    print()
    print(f"  Gesamt ueber {z['n']} CL-Spiele (nach Spielen gewichtet)")
    for name in ("log_loss", "brier", "rps"):
        i = z["bootstrap"][name]
        print(f"     {name:14} Baseline {z['baseline'][name]:.5f}   "
              f"ML {z['ml'][name]:.5f}   delta {z[f'delta_{name}']:+.5f}   "
              f"95%-KI [{i['ci_low']:+.5f}, {i['ci_high']:+.5f}]")
    print(f"     Kalibrierung   Baseline "
          f"{z['baseline']['calibration_error']:.5f}   ML "
          f"{z['ml']['calibration_error']:.5f}")

    for titel, feld, schluessel in (
            ("Testsaison", "per_test_season", "season"),
            ("Profilherkunft", "per_profile_source", "profile_source"),
            ("Profiltiefe", "per_profile_depth", "profile_depth")):
        print()
        print(f"  Je {titel}:")
        print(f"     {titel:30} {'n':>5} {'Baseline':>10} {'ML':>10} "
              f"{'delta':>10}   Hinweis")
        for e in r["aggregate"][feld]:
            hinweis = e["note"] or ""
            print(f"     {str(e[schluessel]):30} {e['n']:5} "
                  f"{e['baseline_log_loss']:10.5f} {e['ml_log_loss']:10.5f} "
                  f"{e['delta_log_loss']:+10.5f}   {hinweis}")

    u = r["verdict"]
    print()
    print(f"  URTEIL: {u['verdict']}")
    for grund in u["reasons"]:
        print(f"     - {grund}")



def print_model_bundle(bundle, pfad):
    """Die Zusammenfassung des Trainings - mit sichtbarem Statusvermerk."""
    t = bundle["training"]
    f = bundle["provenance"]["dataset_fingerprint"]
    c3 = bundle["provenance"]["c3_verdict"]

    print()
    print("  " + "=" * 62)
    print("  SHADOW ONLY   -   C3 INCONCLUSIVE   -   NOT PRODUCTION APPROVED")
    print("  " + "=" * 62)
    print()
    print(f"  Modell-ID        {bundle['model_id']}")
    print(f"  Familie          {bundle['model_family']}")
    print(f"  Kandidat         {bundle['candidate']}")
    print(f"  Merkmale         {bundle['feature_count']} "
          f"({bundle['features'][0]} ... {bundle['features'][-1]})")
    print(f"  Alpha            {bundle['alpha']}   "
          f"aus {bundle['alpha_candidates']}")
    print(f"  Alphawahl        {t['inner_split']['strategy']}")
    print(f"  Training         {t['rows']} Zeilen, Saisons {t['seasons']}")
    print(f"  Umfang           {t['scope']} - Ligen {t['leagues']}")
    print(f"  Fingerprint      {f['sha256'][:32]}...  "
          f"({f['rows']} Zeilen, {f['column_count']} Spalten)")
    print(f"  Integritaet      sha256 "
          f"{bundle['integrity']['models_sha256'][:32]}...")
    print(f"  Ziel             {pfad}")
    print()
    print(f"  C3-Herkunft      {c3['verdict']}  delta LogLoss "
          f"{c3['delta_log_loss']:+.5f}  KI {c3['ci_95']}  "
          f"n={c3['test_matches']}")
    print(f"                   {c3['meaning']}")
    print()
    print("  Dieses Bundle ist NICHT fuer Nutzerprognosen freigegeben.")
    print("  Es aktiviert nichts und veraendert keine Simulation.")


def write_payload(payload, pfad, force):
    """Schreibt den Datensatz - niemals stillschweigend ueber Bestehendes."""
    if os.path.exists(pfad) and not force:
        print()
        print(f"  ABBRUCH: {pfad} existiert bereits.")
        print("  Es wurde NICHTS geschrieben.")
        print("  Zum bewussten Ersetzen: --force, sonst anderen Pfad waehlen.")
        return False

    os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)

    # Atomar: erst vollstaendig danebenschreiben, dann ersetzen.
    temporaer = pfad + ".tmp"
    with open(temporaer, "w", encoding="utf-8") as datei:
        json.dump(payload, datei, indent=2, ensure_ascii=False, sort_keys=True)
        datei.write("\n")
    os.replace(temporaer, pfad)

    print()
    print(f"  Geschrieben: {pfad} ({os.path.getsize(pfad) / 1024 / 1024:.1f} MB)")
    return True


def parse_liste(wert):
    teile = [t.strip() for t in str(wert).split(",") if t.strip()]
    if not teile:
        raise argparse.ArgumentTypeError("leere Liste")
    return teile


def parse_saisons(wert):
    teile = []
    for roh in str(wert).split(","):
        roh = roh.strip()
        if not roh:
            continue
        try:
            teile.append(int(roh))
        except ValueError:
            raise argparse.ArgumentTypeError(f"keine Saison: {roh!r}")
    if not teile:
        raise argparse.ArgumentTypeError("keine Saison angegeben")
    return teile


def build_parser():
    parser = argparse.ArgumentParser(
        description="ML-Vorbereitung fuer FootSim.")
    parser.add_argument("--build-dataset", action="store_true",
                        dest="build_dataset",
                        help="den Point-in-Time-Datensatz erzeugen")
    parser.add_argument("--evaluate", action="store_true",
                        help="das Korrekturmodell im Schatten auswerten "
                             "(Walk-forward, ohne jede Aktivierung)")
    parser.add_argument("--ablate", action="store_true",
                        help="die Merkmalsgruppen gegeneinander abloesen: "
                             + ", ".join(fg.VARIANT_ORDER))
    parser.add_argument("--train-cl-model", action="store_true",
                        dest="train_cl_model",
                        help="das CL-Schattenmodell trainieren und als "
                             "versioniertes Bundle speichern. Aktiviert "
                             "nichts - shadow only.")
    parser.add_argument("--model-output", type=str, default=None,
                        dest="model_output",
                        help="Zieldatei des Modellbundles (nur mit "
                             "--train-cl-model)")
    parser.add_argument("--evaluate-cl", action="store_true",
                        dest="evaluate_cl",
                        help="Champions-League-Shadow-Backtest: Training "
                             "Liga, Test CL. Kandidat steht vorab fest.")
    parser.add_argument("--dataset", type=str, default=None,
                        help="vorhandenes Datensatzartefakt als Eingabe "
                             "(nur mit --evaluate-cl). Ohne Angabe wird der "
                             "Datensatz im Prozess gebaut.")
    parser.add_argument("--diagnose", action="store_true",
                        help="zweite Diagnosestufe - trennt Rekalibrierung "
                             "von Teamprofilinformation: "
                             + ", ".join(fg.DIAGNOSTIC_VARIANT_ORDER))
    parser.add_argument("--leagues", type=parse_liste,
                        default=list(ds.DEFAULT_LEAGUES),
                        help="Ligen, kommagetrennt (Standard: "
                             + ",".join(ds.DEFAULT_LEAGUES) + ")")
    parser.add_argument("--seasons", type=parse_saisons,
                        default=list(ds.DEFAULT_SEASONS),
                        help="Saisons, kommagetrennt (Standard: "
                             + ",".join(str(s) for s in ds.DEFAULT_SEASONS) + ")")
    parser.add_argument("--min-matchday", type=int,
                        default=ds.DEFAULT_MIN_MATCHDAY, dest="min_matchday",
                        help="Grenze fuer evaluation_eligible "
                             f"(Standard: {ds.DEFAULT_MIN_MATCHDAY})")
    parser.add_argument("--output", type=str, default=None,
                        help="Zieldatei. Ohne diese Angabe wird NICHTS "
                             "geschrieben.")
    parser.add_argument("--force", action="store_true",
                        help="eine vorhandene Zieldatei ersetzen")
    parser.add_argument("--no-coverage", action="store_true",
                        dest="no_coverage",
                        help="die Crosswalk-Diagnose ueberspringen")
    parser.add_argument("--include-cl", action="store_true",
                        dest="include_cl",
                        help="Champions-League-Zeilen mitbauen. NUR mit "
                             "--build-dataset zulaessig - siehe main().")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    # Jede Aufgabe schreibt nach --output. Ein gemeinsamer Lauf muesste
    # alle Ausgaben bis auf eine verwerfen.
    aufgaben = [name for name, gewaehlt in (
        ("--build-dataset", args.build_dataset),
        ("--evaluate", args.evaluate),
        ("--ablate", args.ablate),
        ("--diagnose", args.diagnose),
        ("--evaluate-cl", args.evaluate_cl),
        ("--train-cl-model", args.train_cl_model)) if gewaehlt]

    if not aufgaben:
        print("\n  Nichts zu tun. --build-dataset, --evaluate, --ablate, "
              "--diagnose, --evaluate-cl oder --train-cl-model angeben.\n")
        return 2
    if len(aufgaben) > 1:
        print(f"  Je Lauf eine Aufgabe, angegeben waren: "
              f"{', '.join(aufgaben)}.")
        return 2
    if args.min_matchday < 0:
        print("  --min-matchday darf nicht negativ sein.")
        return 2
    if args.force and not args.output:
        print("  --force ergibt ohne --output keinen Sinn.")
        return 2
    if args.dataset and not (args.evaluate_cl or args.train_cl_model):
        print("  --dataset ist nur mit --evaluate-cl oder "
              "--train-cl-model zulaessig.")
        return 2
    if args.model_output and not args.train_cl_model:
        print("  --model-output ist nur mit --train-cl-model zulaessig.")
        return 2
    if args.train_cl_model and not args.model_output:
        print("  --train-cl-model braucht --model-output.")
        return 2
    if args.include_cl and not args.build_dataset:
        # Der Riegel ist kein Formalismus. Auswertung, Ablation und
        # Diagnose waehlen ihre Folds ueber die Saison - CL-Zeilen
        # traegen dieselben Saisonnummern und geriete damit still in
        # die Ligamessung. Jede bisher berichtete Zahl waere danach
        # eine andere, ohne dass es jemand saehe.
        print("  --include-cl ist nur mit --build-dataset zulaessig: "
              "CL-Zeilen gehoeren nicht in die Ligaauswertung.")
        return 2

    aufgabe = {"--evaluate": "Auswertung", "--ablate": "Ablation",
               "--diagnose": "Ablation Stufe 2",
               "--evaluate-cl": "CL-Shadow-Backtest",
               "--train-cl-model": "CL-Modelltraining (Shadow)",
               "--build-dataset": "Datensatz"}[aufgaben[0]]
    print(f"\n  {aufgabe}: {len(args.leagues)} Ligen x "
          f"{len(args.seasons)} Saisons")
    # --train-cl-model schreibt ueber --model-output und hat seinen
    # eigenen Schreibweg. Der Hinweis auf --output waere dort schlicht
    # falsch - das Bundle wird sehr wohl geschrieben.
    if not args.output and not args.train_cl_model:
        print("  Kein --output: es wird nichts geschrieben.")

    if (args.evaluate_cl or args.train_cl_model) and args.dataset:
        quelle = {"kind": "file", "path": args.dataset}
        zeilen = load_dataset_rows(args.dataset)
        diagnose = None
    else:
        # Der CL-Backtest braucht CL-Zeilen; sonst gilt der Schalter.
        mit_cl = args.include_cl or args.evaluate_cl or args.train_cl_model
        quelle = {"kind": "in_process", "include_cl": mit_cl,
                  "leagues": list(args.leagues),
                  "seasons": list(args.seasons)}
        zeilen, diagnose = ds.build_dataset(
            args.leagues, args.seasons, args.min_matchday, include_cl=mit_cl)

    if not zeilen:
        print("\n  Keine einzige Zeile entstanden.")
        return 1

    if args.evaluate:
        ergebnis = ev.run_evaluation(zeilen)
        payload = build_evaluation_payload(
            args.leagues, args.seasons, args.min_matchday, zeilen, ergebnis)
        print_evaluation(payload)
    elif args.ablate:
        ergebnis = ab.run_ablation(zeilen)
        payload = build_ablation_payload(
            args.leagues, args.seasons, args.min_matchday, zeilen, ergebnis)
        print_ablation(payload)
    elif args.evaluate_cl:
        ergebnis = cle.run_cl_evaluation(zeilen)
        payload = build_cl_evaluation_payload(
            args.leagues, args.seasons, args.min_matchday, zeilen, ergebnis,
            quelle)
        print_cl_evaluation(payload)
    elif args.train_cl_model:
        # Ein verweigertes Ueberschreiben oder ein verletzter Guard ist
        # ein Bedienfehler, kein Absturz. Der Nutzer bekommt die
        # Begruendung, nicht einen Traceback.
        try:
            bundle = ps.train_cl_model(zeilen)
            ps.save_bundle(bundle, args.model_output, args.force)
        except ps.ModelBundleError as fehler:
            print(f"\n  ABBRUCH: {fehler}\n")
            return 1
        print_model_bundle(bundle, args.model_output)
        print()
        return 0
    elif args.diagnose:
        ergebnis = ab.run_ablation(zeilen, varianten=fg.DIAGNOSTIC_VARIANTS,
                                   paare=ab.PAIRED_COMPARISONS)
        payload = build_ablation_payload(
            args.leagues, args.seasons, args.min_matchday, zeilen, ergebnis,
            varianten=fg.DIAGNOSTIC_VARIANTS, aufgabe="ablation_diagnostics",
            paare=ab.PAIRED_COMPARISONS)
        print_ablation(payload)
    else:
        payload = build_payload(args.leagues, args.seasons, args.min_matchday,
                                zeilen, diagnose)
        # Getrennt: Der bekannte Vergleichswert 1.01598 gilt fuer
        # Ligaspiele. Waeren CL-Zeilen mit drin, verglichen wir gegen
        # eine Zahl, die es so nie gab.
        liga_zeilen = [z for z in zeilen if z["league"] != "cl"]
        kennzahlen = ds.baseline_metrics(liga_zeilen)
        abdeckung = (None if args.no_coverage
                     else ds.crosswalk_coverage(args.seasons))
        print_summary(payload, kennzahlen, abdeckung)

    if args.output:
        if not write_payload(payload, args.output, args.force):
            return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
