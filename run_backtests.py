"""
Reproduzierbarer Erzeuger fuer die GO3- und GO4.5-Backtests.

AUFRUF
------
    py run_backtests.py --suite go3
    py run_backtests.py --suite go45 --seasons 2024,2025
    py run_backtests.py --suite go3 --output data/go3_neu.json

WARUM ES DIESES SKRIPT GIBT
---------------------------
Die beiden Backtestfunktionen rechnen jeweils EINE Liga-Saison. Die
bekannten Gesamtzahlen - GO3 mit 1,01598 und GO4.5 mit 1,02044 - sind
aber ueber fuenf Ligen und mehrere Saisons aggregiert. Wie diese
Aggregation entstand, stand nirgends im Repository: run_backtest() wurde
ausschliesslich aus Tests aufgerufen, und die beiden Ergebnisdateien
unter data/ hatten keinen committeten Erzeuger.

Damit war der bekannte Stand nicht reproduzierbar - und ein Modell gegen
eine Zahl zu messen, die sich nicht nachrechnen laesst, waere Messung
gegen eine Fiktion.

DIE GEWICHTUNG
--------------
Kennzahlen wie LogLoss sind Mittelwerte JE SPIEL. Ein ungewichteter
Mittelwert ueber Liga-Saisons waere deshalb falsch: Die Bundesliga
bringt 252 Spiele mit, die Premier League 320. Beide gleich zu
gewichten hiesse, ein Bundesligaspiel schwerer zu zaehlen als ein
englisches.

Aggregiert wird deshalb ueber die Spielzahl:

    gesamt = summe(kennzahl_i * n_i) / summe(n_i)

Fuer max_probability_change gilt das Maximum, fuer n die Summe.

EINE EINSCHRAENKUNG, DIE MAN KENNEN MUSS
----------------------------------------
_Accumulator.result() rundet seine Kennzahlen auf sechs Nachkommastellen.
Diese gerundeten Werte sind die Eingabe der Gewichtung hier. Der Fehler
gegenueber einer Aggregation aus den ungerundeten Summen liegt unter
1e-6 und damit weit unterhalb der fuenften Nachkommastelle, in der die
Vergleiche stattfinden. Er wird bewusst in Kauf genommen, um die
bestehenden Funktionen nicht anfassen zu muessen.

WAS DIESES SKRIPT NICHT TUT
---------------------------
Es veraendert weder die Backtestfunktionen noch den produktiven
Simulationspfad. GO3, GO4 und GO5 bleiben in ihrem Modus. Es trainiert
nichts und baut keinen Trainingsdatensatz.

Ohne --output schreibt es KEINE Datei. Mit --output schreibt es nur,
wenn das Ziel frei ist oder --force ausdruecklich gesetzt wurde: Die
vorhandenen Referenzdateien sollen nicht versehentlich verschwinden.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Fassung des Ausgabeformats. Erhoehen, wenn sich die Struktur aendert -
#: sonst laesst sich ein alter Stand spaeter nicht mehr einordnen.
SCHEMA_VERSION = 1

DEFAULT_LEAGUES = ["bl1", "pl", "pd", "sa", "fl1"]
DEFAULT_SEASONS = [2023, 2024, 2025]
DEFAULT_MIN_MATCHDAY = 6

#: Kennzahlen, die ueber die Spielzahl gewichtet werden.
#: Alle sind Mittelwerte je Spiel - deshalb ist die Spielzahl das
#: richtige Gewicht.
#:
#: calibration_error steht bewusst NICHT hier. Er ist kein Mittelwert je
#: Spiel, sondern eine Summe von Absolutbetraegen ueber
#: Wahrscheinlichkeitsbins. Der Betrag muss gebildet werden, NACHDEM die
#: Beobachtungen je Bin zusammengefuehrt sind - siehe
#: merge_calibration_bins().
GEWICHTETE_KENNZAHLEN = (
    "log_loss",
    "brier",
    "rps",
    "accuracy_supplementary",
    "avg_probability_change",
    "clamp_rate",
)

#: Kennzahlen, bei denen das Maximum gilt statt eines Mittelwerts.
MAXIMALE_KENNZAHLEN = ("max_probability_change",)


# ---------------------------------------------------------------------------
# Umgebung
# ---------------------------------------------------------------------------

def git_commit():
    """
    Der Commit, gegen den gemessen wurde.

    Ohne ihn laesst sich ein Ergebnis spaeter keinem Codestand zuordnen -
    und genau daran sind die beiden vorhandenen Dateien gescheitert.
    Ein fehlendes Git ist kein Grund abzubrechen; dann steht hier None.
    """
    try:
        ergebnis = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=30,
        )
        if ergebnis.returncode == 0:
            return ergebnis.stdout.strip()
    except Exception:
        pass
    return None


def git_arbeitsstand():
    """
    Wie weit weicht das Arbeitsverzeichnis vom genannten Commit ab?

    WARUM UNVERSIONIERTE DATEIEN MITZAEHLEN
    ---------------------------------------
    Die erste Fassung liess "??"-Eintraege aus, mit der Begruendung, sie
    veraenderten den Code nicht. Das war falsch: run_backtests.py selbst,
    seine Tests und die Ergebnisdateien waren allesamt unversioniert. Die
    Manifeste meldeten "sauber" fuer Laeufe, deren ausfuehrender Code im
    genannten Commit ueberhaupt nicht enthalten war.

    Genau das macht ein Manifest wertlos: Wer den Commit auscheckt,
    bekommt das Skript nicht, mit dem gemessen wurde. Unversioniert ist
    fuer Reproduzierbarkeit dasselbe wie geaendert - beides bedeutet, dass
    der Commit den Lauf nicht vollstaendig beschreibt.

    Rueckgabe: dict mit dirty, porcelain und den nach Art getrennten
    Pfaden - oder None, wenn Git nicht erreichbar ist.
    """
    try:
        ergebnis = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=30,
        )
        if ergebnis.returncode != 0:
            return None
    except Exception:
        return None

    porcelain = [z for z in ergebnis.stdout.splitlines() if z.strip()]

    staged, modified, untracked, sonstige = [], [], [], []
    for zeile in porcelain:
        marke, pfad = zeile[:2], zeile[3:].strip()
        if marke == "??":
            untracked.append(pfad)
        elif marke[1] != " " and marke[1] != "":
            modified.append(pfad)
        elif marke[0] != " ":
            staged.append(pfad)
        else:
            sonstige.append(pfad)

    return {
        # Jede Abweichung zaehlt - auch unversionierte Dateien.
        "dirty": bool(porcelain),
        "porcelain": porcelain,
        "staged": sorted(staged),
        "modified": sorted(modified),
        "untracked": sorted(untracked),
        "other": sorted(sonstige),
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def merge_calibration_bins(teilergebnisse):
    """
    Fuehrt die Kalibrierungsbins mehrerer Liga-Saisons zusammen.

    WARUM EIN GEWICHTETER MITTELWERT HIER FALSCH WAERE
    --------------------------------------------------
    Der Kalibrierungsfehler ist eine Summe von ABSOLUTBETRAEGEN:

        fehler = summe(|vorhergesagt_b - beobachtet_b| * n_b) / summe(n_b)

    Der Betrag loescht das Vorzeichen. Zwei Liga-Saisons, die im selben
    Bin in ENTGEGENGESETZTE Richtungen abweichen, heben sich in
    Wirklichkeit teilweise auf - im Mittel ihrer Einzelfehler tun sie das
    nicht. Der gewichtete Mittelwert ueberschaetzt den globalen Fehler
    deshalb systematisch.

    Richtig ist: erst die Beobachtungen je Bin zusammenfuehren, dann den
    Betrag bilden.

        vorhergesagt_b = summe(vorhergesagt_i * n_i) / summe(n_i)
        beobachtet_b   = summe(beobachtet_i   * n_i) / summe(n_i)

    EINE UNGENAUIGKEIT, DIE MAN KENNEN MUSS
    ---------------------------------------
    _Accumulator.result() rundet predicted und observed auf VIER
    Nachkommastellen. Aus diesen gerundeten Werten wird hier
    rekonstruiert. Der Rekonstruktionsfehler liegt in der Groessenordnung
    von 5e-5 je Bin und wirkt sich auf den zusammengefuehrten Fehler
    entsprechend gedaempft aus. Fuer eine exakte Rechnung muessten die
    ungerundeten Summen aus dem Akkumulator kommen - das haette eine
    Aenderung an den bestehenden Backtestfunktionen erfordert, die dieser
    Auftrag ausdruecklich vermeiden soll.

    Rueckgabe: (bins, fehler, hinweis). Liefert eine Teilmenge keine
    brauchbaren Bins, ist beides None und hinweis nennt den Grund -
    still auf den falschen Mittelwert zurueckzufallen waere schlimmer als
    keine Zahl.
    """
    gefiltert = [t for t in teilergebnisse if t and t.get("n")]
    if not gefiltert:
        return None, None, "keine Teilergebnisse"

    ohne_bins = [t for t in gefiltert if not t.get("calibration_bins")]
    if ohne_bins:
        return None, None, (
            f"{len(ohne_bins)} von {len(gefiltert)} Teilergebnissen ohne "
            f"calibration_bins - kein gepoolter Wert moeglich")

    # Je Bingrenze die gewichteten Summen sammeln.
    summen = {}
    for teil_ergebnis in gefiltert:
        for eintrag in teil_ergebnis["calibration_bins"]:
            grenze = eintrag.get("bin")
            anzahl = eintrag.get("n") or 0
            if grenze is None or not anzahl:
                continue
            if eintrag.get("predicted") is None or eintrag.get("observed") is None:
                return None, None, f"Bin {grenze} ohne Werte"

            eimer = summen.setdefault(grenze, {"pred": 0.0, "obs": 0.0, "n": 0})
            eimer["pred"] += eintrag["predicted"] * anzahl
            eimer["obs"] += eintrag["observed"] * anzahl
            eimer["n"] += anzahl

    if not summen:
        return None, None, "keine belegten Bins"

    bins = []
    abweichung = 0.0
    gesamt = 0
    for grenze in sorted(summen):
        eimer = summen[grenze]
        vorhergesagt = eimer["pred"] / eimer["n"]
        beobachtet = eimer["obs"] / eimer["n"]
        bins.append({
            "bin": grenze,
            "predicted": round(vorhergesagt, 6),
            "observed": round(beobachtet, 6),
            "n": eimer["n"],
        })
        abweichung += abs(vorhergesagt - beobachtet) * eimer["n"]
        gesamt += eimer["n"]

    return bins, abweichung / gesamt, None


def aggregate_variant(teilergebnisse):
    """
    Fuehrt die Kennzahlen einer Variante ueber mehrere Liga-Saisons zusammen.

    teilergebnisse: Liste der result()-dicts einer Variante.

    Rueckgabe: dict mit denselben Schluesseln, ueber die Spielzahl
    gewichtet. None, wenn nichts auszuwerten war.
    """
    gefiltert = [t for t in teilergebnisse if t and t.get("n")]
    if not gefiltert:
        return None

    gesamt_n = sum(t["n"] for t in gefiltert)
    zusammen = {"n": gesamt_n}

    for schluessel in GEWICHTETE_KENNZAHLEN:
        werte = [(t.get(schluessel), t["n"]) for t in gefiltert
                 if t.get(schluessel) is not None]
        if not werte:
            zusammen[schluessel] = None
            continue
        # Das Gewicht ist die Spielzahl DIESER Teilmenge, nicht die
        # Gesamtzahl - sonst faellt eine Teilmenge ohne diesen Wert
        # faelschlich als Null ins Gewicht.
        summe_n = sum(n for _, n in werte)
        zusammen[schluessel] = sum(w * n for w, n in werte) / summe_n

    for schluessel in MAXIMALE_KENNZAHLEN:
        werte = [t.get(schluessel) for t in gefiltert
                 if t.get(schluessel) is not None]
        zusammen[schluessel] = max(werte) if werte else None

    # Kalibrierung getrennt: erst die Bins zusammenfuehren, dann den
    # Betrag bilden. Siehe merge_calibration_bins().
    bins, fehler, hinweis = merge_calibration_bins(gefiltert)
    zusammen["calibration_error"] = fehler
    zusammen["calibration_bins"] = bins
    if hinweis:
        zusammen["calibration_note"] = hinweis

    return zusammen


def aggregate_all(laeufe):
    """
    Alle Varianten ueber alle Liga-Saisons zusammenfuehren.

    laeufe: Liste der run_backtest()-Rueckgaben.
    """
    nach_variante = {}
    for lauf in laeufe:
        for name, kennzahlen in (lauf.get("variants") or {}).items():
            nach_variante.setdefault(name, []).append(kennzahlen)

    return {name: aggregate_variant(teile)
            for name, teile in sorted(nach_variante.items())}


# ---------------------------------------------------------------------------
# Ausfuehrung
# ---------------------------------------------------------------------------

def run_suite(suite, leagues, seasons, min_matchday, fortschritt=None):
    """
    Fuehrt eine Suite ueber alle Liga-Saison-Kombinationen aus.

    Rueckgabe: (laeufe, uebersprungen). uebersprungen enthaelt die
    Kombinationen ohne Daten - sie sind kein Fehler, aber sie gehoeren
    sichtbar ins Ergebnis, damit niemand eine Luecke fuer eine Messung
    haelt.
    """
    if suite == "go3":
        from src.features.go3_backtest import run_backtest
    elif suite == "go45":
        from src.features.go45_backtest import run_backtest
    else:
        raise ValueError(f"unbekannte Suite: {suite}")

    laeufe = []
    uebersprungen = []

    for season in seasons:
        for league in leagues:
            if fortschritt:
                fortschritt(league, season)

            if suite == "go3":
                # seasons_for_timeline ausdruecklich setzen statt den
                # Standard zu nehmen: Der Zeitleistenumfang gehoert zu
                # den Parametern, die ein Ergebnis erklaeren.
                ergebnis = run_backtest(
                    league, season,
                    seasons_for_timeline=[season - 1, season],
                    min_matchday=min_matchday)
            else:
                ergebnis = run_backtest(
                    league, season, min_matchday=min_matchday)

            if not ergebnis:
                uebersprungen.append({"league": league, "season": season,
                                      "reason": "keine Saisondaten"})
                continue
            laeufe.append(ergebnis)

    return laeufe, uebersprungen


def build_payload(suite, leagues, seasons, min_matchday, laeufe, uebersprungen):
    """
    Baut die Ausgabe.

    Der Aufbau trennt bewusst zwei Dinge:

        results   deterministisch. Zweimal derselbe Aufruf auf demselben
                  Datenstand ergibt bitgleich dasselbe.
        manifest  Zeitstempel, Python-Fassung, Git-Stand. Aendert sich
                  bei jedem Lauf und darf deshalb nie in einen Vergleich
                  zweier Ergebnisse geraten.

    Ohne diese Trennung waere ein Reproduzierbarkeitsvergleich unmoeglich:
    Der Zeitstempel allein wuerde jeden Lauf verschieden aussehen lassen.
    """
    aggregat = aggregate_all(laeufe)

    je_liga_saison = []
    for lauf in laeufe:
        eintrag = {
            "league": lauf.get("league"),
            "season": lauf.get("season"),
            "skipped_warmup": lauf.get("skipped_warmup"),
            "variants": lauf.get("variants"),
        }
        # GO4.5 fuehrt zusaetzliche Abdeckungsangaben. Sie erklaeren die
        # Spielzahl und gehoeren deshalb mit ins Ergebnis.
        for feld in ("player_pool_season", "matches_without_team_mapping",
                     "transfer_events", "squad_membership_known", "coverage"):
            if feld in lauf:
                eintrag[feld] = lauf[feld]
        je_liga_saison.append(eintrag)

    varianten = sorted(aggregat)
    basis_n = (aggregat.get("baseline") or {}).get("n")

    stand = git_arbeitsstand()

    return {
        "manifest": {
            "schema_version": SCHEMA_VERSION,
            "suite": suite,
            "git_commit": git_commit(),
            # Eindeutig benannt und in beide Richtungen ehrlich: dirty
            # ist die Aussage, git_status der Beleg dafuer. Ein Lauf mit
            # geaendertem ODER unversioniertem Code ist niemals sauber.
            "git_dirty": None if stand is None else stand["dirty"],
            "git_status": stand,
            "leagues": list(leagues),
            "seasons": list(seasons),
            "min_matchday": min_matchday,
            "matches_evaluated": basis_n,
            "league_seasons_run": len(laeufe),
            "league_seasons_skipped": len(uebersprungen),
            "variants": varianten,
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "python_version": platform.python_version(),
            "platform": platform.system(),
        },
        "results": {
            "aggregate": aggregat,
            "per_league_season": je_liga_saison,
            "skipped": uebersprungen,
        },
    }


# ---------------------------------------------------------------------------
# Ausgabe
# ---------------------------------------------------------------------------

def print_summary(payload):
    """Eine Zusammenfassung, die ohne die JSON-Datei auskommt."""
    m = payload["manifest"]
    aggregat = payload["results"]["aggregate"]

    print()
    print(f"  Suite            {m['suite']}")
    print(f"  Ligen            {', '.join(m['leagues'])}")
    print(f"  Saisons          {', '.join(str(s) for s in m['seasons'])}")
    print(f"  min_matchday     {m['min_matchday']}")
    print(f"  Liga-Saisons     {m['league_seasons_run']} gelaufen, "
          f"{m['league_seasons_skipped']} uebersprungen")
    print(f"  Spiele bewertet  {m['matches_evaluated']}")
    stand = m.get("git_status")
    zusatz = ""
    if m.get("git_dirty"):
        zusatz = (f"  DIRTY: {len(stand['modified'])} geaendert, "
                  f"{len(stand['staged'])} vorgemerkt, "
                  f"{len(stand['untracked'])} unversioniert")
    elif m.get("git_dirty") is None:
        zusatz = "  (Git-Stand nicht ermittelbar)"
    print(f"  Git              {(m['git_commit'] or 'unbekannt')[:12]}{zusatz}")
    if m.get("git_dirty"):
        print("                   Der Commit allein beschreibt diesen Lauf "
              "nicht vollstaendig.")
    print()

    basis = aggregat.get("baseline")
    kopf = (f"  {'Variante':28} {'n':>6} {'LogLoss':>10} {'Brier':>9} "
            f"{'RPS':>9} {'Kalib':>9}")
    if basis:
        kopf += f" {'d LogLoss':>11}"
    print(kopf)
    print("  " + "-" * (len(kopf) - 2))

    for name in sorted(aggregat):
        k = aggregat[name]
        if not k:
            continue
        # Ein fehlender Kalibrierungswert wird als solcher gezeigt, nicht
        # als Null - sonst sieht eine Luecke wie ein perfekter Wert aus.
        kalib = (f"{k['calibration_error']:9.5f}"
                 if k.get("calibration_error") is not None else "        -")
        zeile = (f"  {name:28} {k['n']:6} {k['log_loss']:10.5f} "
                 f"{k['brier']:9.5f} {k['rps']:9.5f} {kalib}")
        if basis and name != "baseline":
            delta = k["log_loss"] - basis["log_loss"]
            marke = "besser" if delta < 0 else "schlechter"
            zeile += f" {delta:+11.5f}  {marke}"
        print(zeile)

    hinweise = [(name, k["calibration_note"])
                for name, k in sorted(aggregat.items())
                if k and k.get("calibration_note")]
    if hinweise:
        print()
        print("  Kalibrierung nicht bestimmbar:")
        for name, hinweis in hinweise:
            print(f"     {name}: {hinweis}")

    if payload["results"]["skipped"]:
        print()
        print("  Uebersprungen:")
        for eintrag in payload["results"]["skipped"]:
            print(f"     {eintrag['league']} {eintrag['season']}: "
                  f"{eintrag['reason']}")


def write_payload(payload, pfad, force):
    """
    Schreibt das Ergebnis - aber niemals stillschweigend ueber Bestehendes.

    Die vorhandenen Referenzdateien unter data/ sind der einzige Beleg
    fuer den bisherigen Messstand. Sie ohne ausdrueckliche Ansage zu
    ersetzen, waere der teuerste denkbare Fehler dieses Skripts.
    """
    if os.path.exists(pfad) and not force:
        print()
        print(f"  ABBRUCH: {pfad} existiert bereits.")
        print("  Es wurde NICHTS geschrieben.")
        print("  Zum bewussten Ersetzen: --force, sonst anderen Pfad waehlen.")
        return False

    verzeichnis = os.path.dirname(os.path.abspath(pfad))
    os.makedirs(verzeichnis, exist_ok=True)

    # Atomar: erst vollstaendig danebenschreiben, dann ersetzen. Ein
    # Abbruch mitten im Schreiben hinterlaesst sonst eine halbe Datei,
    # die aussieht wie ein Ergebnis.
    temporaer = pfad + ".tmp"
    with open(temporaer, "w", encoding="utf-8") as datei:
        json.dump(payload, datei, indent=2, ensure_ascii=False, sort_keys=True)
        datei.write("\n")
    os.replace(temporaer, pfad)

    print()
    print(f"  Geschrieben: {pfad} ({os.path.getsize(pfad) / 1024:.1f} KB)")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_leagues(wert):
    teile = [t.strip() for t in str(wert).split(",") if t.strip()]
    if not teile:
        raise argparse.ArgumentTypeError("keine Liga angegeben")
    return teile


def parse_seasons(wert):
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
        description="Fuehrt die GO3-/GO4.5-Backtests reproduzierbar aus.")
    parser.add_argument("--suite", required=True, choices=("go3", "go45"),
                        help="welche Backtestsuite laufen soll")
    parser.add_argument("--leagues", type=parse_leagues,
                        default=list(DEFAULT_LEAGUES),
                        help="Ligen, kommagetrennt (Standard: "
                             + ",".join(DEFAULT_LEAGUES) + ")")
    parser.add_argument("--seasons", type=parse_seasons,
                        default=list(DEFAULT_SEASONS),
                        help="Saisons, kommagetrennt (Standard: "
                             + ",".join(str(s) for s in DEFAULT_SEASONS) + ")")
    parser.add_argument("--min-matchday", type=int,
                        default=DEFAULT_MIN_MATCHDAY, dest="min_matchday",
                        help="Spiele vor diesem Spieltag zaehlen nicht mit "
                             f"(Standard: {DEFAULT_MIN_MATCHDAY})")
    parser.add_argument("--output", type=str, default=None,
                        help="Zieldatei. Ohne diese Angabe wird NICHTS "
                             "geschrieben, sondern nur zusammengefasst.")
    parser.add_argument("--force", action="store_true",
                        help="eine vorhandene Zieldatei ersetzen")
    parser.add_argument("--quiet", action="store_true",
                        help="keinen Fortschritt je Liga-Saison ausgeben")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.min_matchday < 0:
        print("  --min-matchday darf nicht negativ sein.")
        return 2
    if args.force and not args.output:
        print("  --force ergibt ohne --output keinen Sinn.")
        return 2

    print(f"\n  Backtest {args.suite}: "
          f"{len(args.leagues)} Ligen x {len(args.seasons)} Saisons")
    if not args.output:
        print("  Kein --output: es wird nichts geschrieben.")

    def fortschritt(league, season):
        if not args.quiet:
            print(f"     {league} {season} ...", flush=True)

    laeufe, uebersprungen = run_suite(
        args.suite, args.leagues, args.seasons, args.min_matchday,
        fortschritt=fortschritt)

    if not laeufe:
        print("\n  Keine einzige Liga-Saison lieferte Daten.")
        return 1

    payload = build_payload(args.suite, args.leagues, args.seasons,
                            args.min_matchday, laeufe, uebersprungen)
    print_summary(payload)

    if args.output:
        if not write_payload(payload, args.output, args.force):
            return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
