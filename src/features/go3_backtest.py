"""
Walk-Forward-Backtest fuer GO 3, mit Ablation der Einzelfaktoren.

DIE FRAGE
---------
Verbessert die Belastungskorrektur die Vorhersage - und wenn ja, welcher
Teil davon? Ohne diese Antwort darf GO 3 nicht aktiv werden. Eine
Korrektur, die plausibel klingt und die Vorhersage verschlechtert, ist
schaedlicher als gar keine.

WALK-FORWARD
------------
Fuer jedes Spiel werden die Teamstaerken ausschliesslich aus Partien
gebildet, die VOR dem Anpfiff lagen. Es gibt keinen Durchgang, in dem
die Endtabelle oder ein spaeteres Ergebnis sichtbar waere. Der Stichtag
wandert mit dem Spielkalender - daher der Name.

Die Profile werden je Spieltermin einmal gebaut, nicht je Spiel: alle
Partien desselben Tages haben denselben Stichtag, und ein Spiel am
Stichtag gilt als nicht bekannt. Das spart den Grossteil der Rechenzeit,
ohne die Zeitsemantik zu veraendern.

ANALYTISCH STATT GEWUERFELT
---------------------------
Die Wahrscheinlichkeiten werden aus der Poisson-Verteilung direkt
berechnet, nicht simuliert. Zwei Gruende: Das Ergebnis ist exakt statt
auf Monte-Carlo-Rauschen genau, und es ist ohne Startwert reproduzierbar.
Bei einem Effekt in der Groessenordnung von einem Prozent waere
Simulationsrauschen sonst groesser als das, was gemessen werden soll.

Die Formel ist dieselbe wie in der Produktion
(team_profile.expected_goals) - es wird kein zweites Modell gebaut.
"""

import math
from collections import defaultdict

from src.features.go3 import (
    CONSTANTS, _clamp, _rest_effect, _congestion_effect,
    _away_effect, _schedule_effect, apply_modifier)
from src.features.workload import quality_weight


#: Maximale Torzahl in der analytischen Summe. Ab hier ist die
#: Restwahrscheinlichkeit kleiner als ein Millionstel und fuer jede
#: Kennzahl bedeutungslos.
MAX_GOALS = 10

#: Die zu vergleichenden Konfigurationen.
#:
#: Jede nennt die Faktoren, die sie einschaltet. "baseline" ist das
#: heutige Modell ohne jede Korrektur und der Massstab fuer alle anderen.
VARIANTS = {
    "baseline": (),
    "rest_only": ("rest",),
    "congestion_only": ("congestion",),
    "schedule_only": ("schedule_strength",),
    "rest_congestion": ("rest", "congestion"),
    "full_go3": ("rest", "congestion", "consecutive_away", "schedule_strength"),
    # Kontrollgruppe: alle Faktoren, aber ohne Qualitaetsgewichtung.
    # Zeigt, ob die Gewichtung ueberhaupt etwas beitraegt oder nur
    # zusaetzliche Komplexitaet ist.
    "full_no_quality_weighting": ("rest", "congestion",
                                  "consecutive_away", "schedule_strength"),
}

#: Welche Variante die Qualitaetsgewichtung abschaltet.
NO_WEIGHTING = "full_no_quality_weighting"


def _poisson_pmf(k, lam):
    """Einzelwahrscheinlichkeit der Poisson-Verteilung."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def outcome_probabilities(xh, xa):
    """
    1X2-Wahrscheinlichkeiten aus zwei Erwartungswerten.

    Unabhaengige Poisson-Verteilungen je Team - dieselbe Annahme, auf der
    auch die Monte-Carlo-Simulation des Projekts beruht. Hier nur
    ausgerechnet statt gewuerfelt.
    """
    heim = [_poisson_pmf(k, xh) for k in range(MAX_GOALS + 1)]
    gast = [_poisson_pmf(k, xa) for k in range(MAX_GOALS + 1)]

    h = d = a = 0.0
    for i, ph in enumerate(heim):
        for j, pa in enumerate(gast):
            p = ph * pa
            if i > j:
                h += p
            elif i == j:
                d += p
            else:
                a += p

    gesamt = h + d + a
    if gesamt <= 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (h / gesamt, d / gesamt, a / gesamt)


def _partial_modifier(features, schedule, league_average, faktoren,
                      qualitaetsgewichtung=True):
    """
    Korrektur aus NUR den genannten Faktoren.

    Das ist der Kern der Ablation: dieselbe Rechenkette wie in der
    Produktion, aber mit abschaltbaren Anteilen. Bewusst dieselben
    Einzelfunktionen aus go3.py - eine Nachbildung wuerde messen, was
    der Backtest gerade NICHT prueft.
    """
    if not faktoren:
        return 0.0, False

    zaehl = features.get("data_quality") or "unavailable"
    pause = features.get("rest_data_quality") or "unavailable"
    plan = (schedule or {}).get("schedule_strength_quality") or "unavailable"

    roh = {
        "rest": (_rest_effect(features), pause),
        "congestion": (_congestion_effect(features), zaehl),
        "consecutive_away": (_away_effect(features), zaehl),
        "schedule_strength": (_schedule_effect(schedule or {}, league_average), plan),
    }

    grenze = CONSTANTS["MAX_SINGLE_EFFECT"]["wert"]
    summe = 0.0
    beschnitten = False
    for name in faktoren:
        wert, klasse = roh[name]
        if qualitaetsgewichtung:
            wert = wert * quality_weight(klasse)
        elif klasse == "unavailable":
            # Auch ohne Gewichtung bleibt "keine Daten" neutral. Alles
            # andere waere kein Kontrollversuch, sondern ein Fehler.
            wert = 0.0
        wert, geclampt = _clamp(wert, grenze)
        beschnitten = beschnitten or geclampt
        summe += wert

    summe, geclampt = _clamp(summe, CONSTANTS["MAX_TOTAL_EFFECT"]["wert"])
    beschnitten = beschnitten or geclampt

    if abs(summe) < CONSTANTS["MIN_APPLY_THRESHOLD"]["wert"]:
        summe = 0.0
    return summe, beschnitten


# ---------------------------------------------------------------------------
# Kennzahlen
# ---------------------------------------------------------------------------

def _log_loss(p, tatsaechlich):
    """Negative Log-Likelihood. Kleiner ist besser."""
    # Abschneiden, damit eine Wahrscheinlichkeit von exakt null nicht
    # zu unendlich fuehrt und einen einzelnen Ausreisser die ganze
    # Kennzahl bestimmen laesst.
    wert = max(min(p[tatsaechlich], 1 - 1e-15), 1e-15)
    return -math.log(wert)


def _brier(p, tatsaechlich):
    """Mehrklassiger Brier-Score. Kleiner ist besser."""
    return sum((p[i] - (1.0 if i == tatsaechlich else 0.0)) ** 2
               for i in range(3))


def _rps(p, tatsaechlich):
    """
    Ranked Probability Score. Kleiner ist besser.

    Fuer Fussballergebnisse aussagekraeftiger als der Brier-Score, weil
    die drei Ausgaenge geordnet sind: Heimsieg, Unentschieden,
    Auswaertssieg. Wer statt eines Heimsiegs ein Unentschieden vorhersagt,
    liegt weniger falsch als wer einen Auswaertssieg vorhersagt - der
    Brier-Score sieht diesen Unterschied nicht.
    """
    kumuliert_p = 0.0
    kumuliert_e = 0.0
    summe = 0.0
    for i in range(2):        # letzte Klasse traegt definitionsgemaess 0 bei
        kumuliert_p += p[i]
        kumuliert_e += 1.0 if i == tatsaechlich else 0.0
        summe += (kumuliert_p - kumuliert_e) ** 2
    return summe / 2.0


class _Accumulator:
    """Sammelt die Kennzahlen einer Variante."""

    def __init__(self):
        self.n = 0
        self.log_loss = 0.0
        self.brier = 0.0
        self.rps = 0.0
        self.treffer = 0
        self.clamps = 0
        self.prob_change = 0.0
        self.max_prob_change = 0.0
        # Kalibrierung: zehn Eimer ueber die vorhergesagte
        # Wahrscheinlichkeit, je Eimer Summe der Vorhersagen und Zahl
        # der tatsaechlichen Eintritte.
        self.bins = defaultdict(lambda: [0.0, 0, 0])

    def add(self, p, tatsaechlich, basis_p=None, clamp=False):
        self.n += 1
        self.log_loss += _log_loss(p, tatsaechlich)
        self.brier += _brier(p, tatsaechlich)
        self.rps += _rps(p, tatsaechlich)
        if max(range(3), key=lambda i: p[i]) == tatsaechlich:
            self.treffer += 1
        if clamp:
            self.clamps += 1
        if basis_p is not None:
            aenderung = max(abs(p[i] - basis_p[i]) for i in range(3))
            self.prob_change += aenderung
            self.max_prob_change = max(self.max_prob_change, aenderung)
        for i in range(3):
            eimer = min(9, int(p[i] * 10))
            self.bins[eimer][0] += p[i]
            self.bins[eimer][1] += 1 if i == tatsaechlich else 0
            self.bins[eimer][2] += 1

    def result(self):
        if not self.n:
            return None
        kalibrierung = []
        abweichung = 0.0
        gesamt = 0
        for eimer in sorted(self.bins):
            summe, eingetreten, anzahl = self.bins[eimer]
            vorhergesagt = summe / anzahl
            beobachtet = eingetreten / anzahl
            kalibrierung.append({
                "bin": f"{eimer/10:.1f}-{(eimer+1)/10:.1f}",
                "predicted": round(vorhergesagt, 4),
                "observed": round(beobachtet, 4),
                "n": anzahl,
            })
            abweichung += abs(vorhergesagt - beobachtet) * anzahl
            gesamt += anzahl
        return {
            "n": self.n,
            "log_loss": round(self.log_loss / self.n, 6),
            "brier": round(self.brier / self.n, 6),
            "rps": round(self.rps / self.n, 6),
            # Trefferquote steht bewusst NUR ergaenzend dabei: sie
            # bewertet nur den wahrscheinlichsten Ausgang und ist
            # gegenueber der Guete der Wahrscheinlichkeit blind.
            "accuracy_supplementary": round(self.treffer / self.n, 4),
            "calibration_error": round(abweichung / gesamt, 6) if gesamt else None,
            "calibration_bins": kalibrierung,
            "avg_probability_change": round(self.prob_change / self.n, 6),
            "max_probability_change": round(self.max_prob_change, 6),
            "clamp_rate": round(self.clamps / self.n, 6),
        }


def _outcome_index(match):
    """0 = Heimsieg, 1 = Unentschieden, 2 = Auswaertssieg."""
    h, a = match.get("home_goals"), match.get("away_goals")
    if h is None or a is None:
        return None
    return 0 if h > a else (1 if h == a else 2)


def _load_situation(features):
    """Grobe Belastungslage fuer die Segmentierung."""
    stufe = features.get("congestion_level")
    if stufe in ("high", "elevated"):
        return stufe
    if features.get("short_rest_flag"):
        return "short_rest"
    return stufe or "unknown"


# ---------------------------------------------------------------------------
# Der Durchlauf
# ---------------------------------------------------------------------------

def _team_strength_scalar(profile):
    """
    Eine Zahl je Team fuer die Spielplanhaerte.

    Angriff mal Kehrwert der Abwehr - dieselbe Zusammenfassung, die auch
    team_analysis fuer den Ligavergleich verwendet. Bewusst keine neue
    Definition von Staerke.
    """
    if not profile:
        return None
    angriff = (profile.get("attack_home", 1.0) + profile.get("attack_away", 1.0)) / 2
    abwehr = (profile.get("defence_home", 1.0) + profile.get("defence_away", 1.0)) / 2
    if abwehr <= 0:
        return None
    return angriff / abwehr


def run_backtest(league_key, season, seasons_for_timeline=None,
                 variants=None, min_matchday=6, scale=1.0):
    """
    Walk-Forward-Backtest EINER Liga-Saison.

    scale:        Diagnosefaktor auf die Korrektur. 1.0 ist der
                  Produktionsstand. Andere Werte dienen der Frage, ob
                  ein ausbleibender Effekt am Betrag oder am Vorzeichen
                  liegt - ein negativer Wert dreht die Richtung um.
                  Fuer den Produktivpfad NICHT verwenden.

    min_matchday: Vor diesem Spieltag sind die Profile noch fast reine
                  Historie und die Belastungsfenster kaum gefuellt. Diese
                  Spiele werden ausgewertet, aber nicht mitgezaehlt -
                  sonst misst man die Anlaufphase statt des Effekts.

    Rueckgabe: {variant: kennzahlen} plus Segmente.
    """
    from datetime import datetime
    from src.data.historical_loader import LEAGUE_CODES, load_season
    from src.features.team_profile import (
        build_season_profiles, expected_goals, neutral_profile)
    from src.features.match_timeline import build_timeline, team_timeline
    from src.features.workload import workload_features, schedule_strength
    from src.features.go3_provider import league_average_strength

    variants = variants or VARIANTS
    api_code = LEAGUE_CODES.get(league_key)
    payload = load_season(api_code, season)
    if not payload:
        return None

    alle = [m for m in (payload.get("matches") or [])
            if m.get("home_goals") is not None and m.get("away_goals") is not None]
    if not alle:
        return None

    zeitleiste, _ = build_timeline(seasons_for_timeline or [season - 1, season])
    team_cache = {}

    def zeitleiste_fuer(team_id):
        if team_id not in team_cache:
            team_cache[team_id] = team_timeline(zeitleiste, team_id)
        return team_cache[team_id]

    # Nach Datum gruppieren: ein Profilaufbau je Spieltermin.
    nach_datum = defaultdict(list)
    for m in alle:
        if m.get("date"):
            nach_datum[m["date"]].append(m)

    zaehler = {name: _Accumulator() for name in variants}
    segmente = defaultdict(lambda: defaultdict(_Accumulator))
    uebersprungen = 0

    for datum in sorted(nach_datum):
        # Punkt-in-Zeit: build_season_profiles filtert selbst auf das,
        # was am Stichtag bekannt war. Ein Spiel am Stichtag gilt dort
        # als nicht bekannt - genau das brauchen wir hier.
        gebaut = build_season_profiles(payload, cutoff=datum)
        profile = gebaut["profiles"]
        # Der Ligadurchschnitt kommt aus DEMSELBEN Aufruf und ist damit
        # ebenfalls stichtagsgefiltert. Ihn getrennt zu berechnen waere
        # eine zweite Quelle, die auseinanderlaufen kann.
        schnitt = gebaut["league_avg"]

        gespielt = schnitt.get("matches") or 0
        je_spieltag = (len(payload.get("teams") or {}) // 2) or 1
        if gespielt < min_matchday * je_spieltag:
            uebersprungen += len(nach_datum[datum])
            continue
        lookup = {}
        for tid, prof in profile.items():
            wert = _team_strength_scalar(prof)
            if wert is not None:
                lookup[tid] = wert
        liga_mittel = league_average_strength(lookup)

        cutoff = datetime.fromisoformat(f"{datum}T12:00:00")

        for match in nach_datum[datum]:
            ergebnis = _outcome_index(match)
            if ergebnis is None:
                continue

            heim_id, gast_id = match.get("home_id"), match.get("away_id")
            heim_profil = profile.get(heim_id) or neutral_profile(heim_id)
            gast_profil = profile.get(gast_id) or neutral_profile(gast_id)

            xh, xa = expected_goals(heim_profil, gast_profil, schnitt)
            basis_p = outcome_probabilities(xh, xa)

            heim_f = workload_features(zeitleiste_fuer(heim_id), cutoff)
            gast_f = workload_features(zeitleiste_fuer(gast_id), cutoff)
            heim_s = schedule_strength(zeitleiste_fuer(heim_id), cutoff, lookup)
            gast_s = schedule_strength(zeitleiste_fuer(gast_id), cutoff, lookup)

            for name, faktoren in variants.items():
                gewichten = (name != NO_WEIGHTING)
                mh, ch = _partial_modifier(heim_f, heim_s, liga_mittel,
                                           faktoren, gewichten)
                ma, ca = _partial_modifier(gast_f, gast_s, liga_mittel,
                                           faktoren, gewichten)
                mh, ma = mh * scale, ma * scale
                if mh == 0.0 and ma == 0.0:
                    p = basis_p
                else:
                    nxh, nxa = expected_goals(
                        apply_modifier(heim_profil, mh),
                        apply_modifier(gast_profil, ma), schnitt)
                    p = outcome_probabilities(nxh, nxa)

                zaehler[name].add(p, ergebnis, basis_p, ch or ca)

                if name in ("baseline", "full_go3"):
                    segmente[f"load:{_load_situation(heim_f)}"][name].add(
                        p, ergebnis, basis_p, ch or ca)
                    segmente[f"quality:{heim_f.get('data_quality')}"][name].add(
                        p, ergebnis, basis_p, ch or ca)
                    segmente[f"competition:{league_key}"][name].add(
                        p, ergebnis, basis_p, ch or ca)

    return {
        "league": league_key,
        "season": season,
        "skipped_warmup": uebersprungen,
        "variants": {name: acc.result() for name, acc in zaehler.items()},
        "segments": {
            seg: {name: acc.result() for name, acc in inner.items()}
            for seg, inner in segmente.items()
        },
    }
