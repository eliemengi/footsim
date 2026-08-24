"""
GO 3: Belastung und Spielplanhaerte als vorsichtige Korrektur der Teamstaerke.

WAS DIESES MODUL IST
--------------------
Die einzige Stelle, an der aus Belastungsmerkmalen (workload.py) eine
Veraenderung der Simulationsstaerke wird. Wer wissen will, wie stark
GO 3 wirken kann, liest die Konstantentabelle unten - und sonst nichts.

DREI SICHERUNGEN
----------------
1. Jede Konstante hat einen dokumentierten Zweck, einen Wertebereich und
   eine Begruendung. Keine unbenannte Zahl im Code.
2. Jeder Einzeleffekt ist begrenzt (MAX_SINGLE_EFFECT), und die Summe
   aller Effekte noch einmal (MAX_TOTAL_EFFECT). Das Clamping ist hart:
   es wird nicht gewarnt, sondern beschnitten - und die Beschneidung
   wird gemeldet.
3. Die Datenqualitaet gewichtet den Effekt. "unavailable" heisst exakt
   null, nicht "ein bisschen".

DER MODUS
---------
    off      GO 3 rechnet nicht. Simulation exakt wie vorher.
    shadow   GO 3 rechnet vollstaendig, aendert aber NICHTS an der
             Simulation. Die Werte sind nur in der Diagnose sichtbar.
    active   GO 3 wirkt.

Voreinstellung ist shadow. Eine Korrektur, die noch nicht im Backtest
belegt ist, darf keine Vorhersage veraendern - sichtbar sein darf sie
trotzdem, sonst liesse sie sich nie beurteilen.

WARUM DIE EFFEKTE SO KLEIN SIND
-------------------------------
Belastung ist ein Randeinfluss, kein Hauptfaktor. Die Teamstaerke
erklaert den Ausgang eines Spiels um Groessenordnungen besser als die
Frage, ob drei oder vier Tage Pause waren. Ein Modell, das Muedigkeit
zweistellig gewichtet, wuerde bekannte Zusammenhaenge durch eine
schwache Groesse ueberschreiben. Die Obergrenzen unten sind deshalb
bewusst niedrig angesetzt und gehoeren zu den Groessen, die der
Backtest belegen muss, bevor der Modus auf active geht.
"""

import os

from src.features.workload import quality_weight


# ---------------------------------------------------------------------------
# Betriebsmodus
# ---------------------------------------------------------------------------

MODES = ("off", "shadow", "active")

#: Sichere Voreinstellung. Siehe Modulkopf.
DEFAULT_MODE = "shadow"

#: Umgebungsvariable, mit der sich der Modus setzen laesst.
MODE_ENV_VAR = "FOOTSIM_GO3_MODE"


def current_mode():
    """
    Aktiver GO-3-Modus.

    Ein unbekannter Wert faellt bewusst auf die sichere Voreinstellung
    zurueck, statt zu werfen: eine vertippte Umgebungsvariable darf die
    Anwendung nicht lahmlegen, aber auch nicht heimlich aktivieren.
    """
    gesetzt = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    return gesetzt if gesetzt in MODES else DEFAULT_MODE


# ---------------------------------------------------------------------------
# Konstanten - die vollstaendige Tabelle
# ---------------------------------------------------------------------------
#
# Format je Eintrag:
#   zweck                 Wofuer die Zahl da ist
#   bereich               Zulaessiger Wertebereich
#   begruendung           Warum genau dieser Wert
#
# Die Tabelle ist maschinenlesbar, damit Tests sie pruefen koennen und
# die Diagnose sie ausgeben kann, ohne dass irgendwo eine zweite,
# abweichende Beschreibung entsteht.

CONSTANTS = {
    "REFERENCE_REST_HOURS": {
        "wert": 168,
        "zweck": "Pause, bei der kein Effekt entsteht (neutraler Punkt).",
        "bereich": (96, 240),
        "begruendung": (
            "Aus der Zeitleiste gemessen, nicht geschaetzt: ueber 12.220 "
            "Teamspiele der Saisons 2023-2025 liegt der MEDIAN der Pause "
            "bei exakt 168 Stunden - dem Samstag-Samstag-Rhythmus. Der "
            "neutrale Punkt gehoert dorthin, wo der Normalfall liegt. "
            "Eine niedrigere Referenz haette die Haelfte aller Spiele "
            "bestraft und den Effekt zur Regel statt zur Ausnahme "
            "gemacht. Ueber der Referenz gibt es bewusst KEINEN Bonus: "
            "eine laengere Pause bedeutet auch Rhythmusverlust, der "
            "Effekt waere also nicht mehr eindeutig gerichtet."
        ),
    },
    "REST_EFFECT_PER_24H": {
        "wert": 0.0025,
        "zweck": "Staerkeaenderung je 24 Stunden Pause unter der Referenz.",
        "bereich": (0.0, 0.01),
        "begruendung": (
            "Ebenfalls aus der gemessenen Verteilung abgeleitet. "
            "Perzentile der Pause: 25 % bei 96 h, 10 % bei 72 h, 1 % bei "
            "64 h. Mit diesem Satz ergibt eine typische englische Woche "
            "(72 h) rund 1,0 % und der gemessene Extremfall (64 h) rund "
            "1,1 % - spuerbar, aber deutlich unter der Einzelgrenze. "
            "Der zunaechst angesetzte Wert von 0,01 je Tag war um das "
            "Vierfache zu gross: er trieb schon eine voellig normale "
            "Mittwochspartie in die Obergrenze. Dann bestimmt nicht mehr "
            "das Modell den Effekt, sondern das Clamping - und ein "
            "Grenzwert, der im Regelbetrieb staendig greift, ist keine "
            "Sicherung mehr, sondern eine versteckte Konstante."
        ),
    },
    "CONGESTION_EFFECT": {
        "wert": {"low": 0.003, "normal": 0.0, "elevated": -0.008, "high": -0.018},
        "zweck": "Staerkeaenderung je Verdichtungsstufe.",
        "bereich": (-0.03, 0.03),
        "begruendung": (
            "Gemessene Haeufigkeit ueber dieselben 12.220 Teamspiele: "
            "low 29,9 %, normal 55,4 %, elevated 9,6 %, high 1,4 %. "
            "'high' ist damit tatsaechlich der Ausnahmefall und traegt "
            "deshalb den groessten Betrag. 'low' bekommt einen kleinen "
            "positiven Wert statt null - eine ruhige Woche ist ein "
            "realer Vorteil, aber ein kleinerer als der Nachteil einer "
            "Belastungsspitze: Erholung wirkt schwaecher als Ermuedung. "
            "Bei knapp 30 % Anteil muss dieser Bonus zudem klein "
            "bleiben, sonst verschoebe er fast ein Drittel aller "
            "Begegnungen."
        ),
    },
    "CONSECUTIVE_AWAY_EFFECT": {
        "wert": 0.003,
        "zweck": "Abzug je Auswaertsspiel in ununterbrochener Serie.",
        "bereich": (0.0, 0.01),
        "begruendung": (
            "Greift erst ab dem zweiten Spiel der Serie - das erste "
            "Auswaertsspiel ist der Normalfall und steckt bereits im "
            "Heimvorteil des Modells. Bewusst der kleinste Effekt der "
            "Tabelle: Reisebelastung ist der am schwaechsten belegte der "
            "Einfluesse, und die Zeitleiste kennt keine Entfernungen, "
            "sondern nur die Abfolge."
        ),
    },
    "SCHEDULE_STRENGTH_EFFECT": {
        "wert": 0.008,
        "zweck": "Skalierung der Gegnerstaerke der letzten 30 Tage.",
        "bereich": (0.0, 0.02),
        "begruendung": (
            "Wer zuletzt gegen starke Gegner spielen musste, war hoeher "
            "belastet, als die reine Spielzahl zeigt. Der Wert wird mit "
            "der auf [-1, 1] begrenzten relativen Abweichung vom "
            "Ligadurchschnitt multipliziert; der Betrag bleibt damit "
            "unter einem Prozent. Bewusst kleiner als der "
            "Verdichtungseffekt, weil die Gegnerstaerke bereits "
            "mittelbar in der Modellstaerke des Gegners steckt und "
            "sonst doppelt zaehlen wuerde."
        ),
    },
    "MAX_SINGLE_EFFECT": {
        "wert": 0.030,
        "zweck": "Obergrenze fuer den Betrag EINES Einzeleffekts.",
        "bereich": (0.0, 0.05),
        "begruendung": (
            "Drei Prozent Staerkeaenderung entsprechen grob einem "
            "Zehntel Tor Erwartungswert. Das ist sichtbar, kippt aber "
            "keine Begegnung, deren Ausgang die Staerke schon klar "
            "vorzeichnet. Nach der Neukalibrierung wird die Grenze im "
            "Regelbetrieb nicht mehr erreicht - sie ist eine Sicherung "
            "gegen fehlerhafte Eingangsdaten, kein Betriebspunkt."
        ),
    },
    "MAX_TOTAL_EFFECT": {
        "wert": 0.050,
        "zweck": "Obergrenze fuer die Summe ALLER Effekte eines Teams.",
        "bereich": (0.0, 0.08),
        "begruendung": (
            "Kleiner als die Summe der Einzelgrenzen. Die Einfluesse "
            "sind korreliert - ein Team mit kurzer Pause hat meist auch "
            "hohe Verdichtung und oft starke Gegner. Sie voll zu "
            "addieren wuerde dieselbe Ursache mehrfach zaehlen."
        ),
    },
    "MIN_APPLY_THRESHOLD": {
        "wert": 0.001,
        "zweck": "Unterhalb dieses Betrags wird gar nicht erst angewendet.",
        "bereich": (0.0, 0.005),
        "begruendung": (
            "Verhindert, dass ein Effekt von einem Zehntelpromille die "
            "Simulation numerisch verunruhigt und Diagnoseausgaben mit "
            "Rauschen fuellt, ohne irgendetwas zu erklaeren."
        ),
    },
}


def _c(name):
    """Wert einer Konstante. Zentral, damit es keine zweite Quelle gibt."""
    return CONSTANTS[name]["wert"]


def constants_report():
    """
    Die Konstantentabelle in ausgabefaehiger Form.

    Bewusst ohne Pfade und ohne Umgebungswerte - sie darf in einer
    oeffentlichen Diagnose stehen.
    """
    zeilen = []
    for name, eintrag in CONSTANTS.items():
        zeilen.append({
            "name": name,
            "value": eintrag["wert"],
            "purpose": eintrag["zweck"],
            "range": list(eintrag["bereich"]),
            "justification": eintrag["begruendung"],
        })
    return zeilen


# ---------------------------------------------------------------------------
# Einzeleffekte
# ---------------------------------------------------------------------------

def _clamp(wert, grenze):
    """Auf [-grenze, +grenze] beschneiden. Rueckgabe: (wert, beschnitten)."""
    if wert > grenze:
        return grenze, True
    if wert < -grenze:
        return -grenze, True
    return wert, False


def _rest_effect(features):
    """
    Effekt der Pause. Negativ bei zu kurzer Pause, sonst null.

    Ueber der Referenz gibt es bewusst KEINEN Bonus - siehe Begruendung
    zu REFERENCE_REST_HOURS.
    """
    stunden = features.get("rest_hours")
    if stunden is None:
        return 0.0
    fehlend = _c("REFERENCE_REST_HOURS") - stunden
    if fehlend <= 0:
        return 0.0
    return -(fehlend / 24.0) * _c("REST_EFFECT_PER_24H")


def _congestion_effect(features):
    """Effekt der Terminverdichtung."""
    stufe = features.get("congestion_level")
    if not stufe:
        return 0.0
    return _c("CONGESTION_EFFECT").get(stufe, 0.0)


def _away_effect(features):
    """Effekt einer Auswaertsserie - erst ab dem zweiten Spiel."""
    serie = features.get("consecutive_away_matches") or 0
    if serie < 2:
        return 0.0
    return -(serie - 1) * _c("CONSECUTIVE_AWAY_EFFECT")


def _schedule_effect(schedule, league_average):
    """
    Effekt der zuletzt bespielten Gegnerstaerke.

    Ohne Ligadurchschnitt gibt es keinen Bezugspunkt und damit keinen
    Effekt - eine absolute Staerkezahl allein sagt nichts darueber, ob
    sie hoch oder niedrig ist.
    """
    wert = schedule.get("recent_opponent_strength")
    if wert is None or not league_average:
        return 0.0

    abweichung = (wert - league_average) / league_average
    # Auf [-1, 1] begrenzen, damit ein Ausreisser den Effekt nicht
    # ueber die Einzelgrenze hinaustraegt.
    abweichung = max(-1.0, min(1.0, abweichung))
    return -abweichung * _c("SCHEDULE_STRENGTH_EFFECT")


def compute_modifier(features, schedule=None, league_average=None):
    """
    Gesamtkorrektur fuer EIN Team vor EINEM Spiel.

    Rueckgabe:
        {
          "modifier":        float   Faktor-Abweichung, z. B. -0.021
          "components":      {name: wert}   nach Clamping und Gewichtung
          "components_raw":  {name: wert}   davor
          "clamp_applied":   bool
          "clamped_parts":   [name, ...]
          "data_quality":    str
          "quality_weight":  float
        }

    Der Rueckgabewert ist eine ABWEICHUNG, kein Faktor: 0.0 bedeutet
    "keine Aenderung". Das macht die Neutralitaet bei fehlenden Daten
    pruefbar - ein Faktor 1.0 waere leichter mit einem Fehler zu
    verwechseln.
    """
    schedule = schedule or {}

    zaehl_qualitaet = features.get("data_quality") or "unavailable"
    pausen_qualitaet = features.get("rest_data_quality") or "unavailable"
    plan_qualitaet = schedule.get("schedule_strength_quality") or "unavailable"

    # Jeder Anteil wird mit SEINER eigenen Qualitaet gewichtet. Eine
    # exakte Spielzaehlung darf nicht darunter leiden, dass die
    # Stundenangabe ungenau ist - und umgekehrt.
    roh = {
        "rest": _rest_effect(features),
        "congestion": _congestion_effect(features),
        "consecutive_away": _away_effect(features),
        "schedule_strength": _schedule_effect(schedule, league_average),
    }
    gewichte = {
        "rest": quality_weight(pausen_qualitaet),
        "congestion": quality_weight(zaehl_qualitaet),
        "consecutive_away": quality_weight(zaehl_qualitaet),
        "schedule_strength": quality_weight(plan_qualitaet),
    }

    grenze = _c("MAX_SINGLE_EFFECT")
    teile = {}
    beschnitten = []
    for name, wert in roh.items():
        gewichtet, wurde_beschnitten = _clamp(wert * gewichte[name], grenze)
        if wurde_beschnitten:
            beschnitten.append(name)
        teile[name] = gewichtet

    summe = sum(teile.values())
    summe, summe_beschnitten = _clamp(summe, _c("MAX_TOTAL_EFFECT"))
    if summe_beschnitten:
        beschnitten.append("total")

    if abs(summe) < _c("MIN_APPLY_THRESHOLD"):
        summe = 0.0

    gesamt_qualitaet = zaehl_qualitaet
    if all(g == 0.0 for g in gewichte.values()):
        gesamt_qualitaet = "unavailable"

    return {
        "modifier": round(summe, 6),
        "components": {k: round(v, 6) for k, v in teile.items()},
        "components_raw": {k: round(v, 6) for k, v in roh.items()},
        "clamp_applied": bool(beschnitten),
        "clamped_parts": beschnitten,
        "data_quality": gesamt_qualitaet,
        "quality_weight": round(max(gewichte.values()) if gewichte else 0.0, 4),
    }


def apply_modifier(profile, modifier):
    """
    Wendet eine Korrektur auf ein Staerkeprofil an.

    Ein muedes Team trifft seltener UND haelt schlechter hinten. Der
    Angriffswert sinkt deshalb, der Abwehrwert steigt (groessere
    defence-Werte sind im Projekt schlechter).

    Das Original wird NICHT veraendert - der Aufrufer braucht beide
    Staende fuer den Shadow-Vergleich.
    """
    if not profile:
        return profile
    if not modifier:
        return dict(profile)

    korrigiert = dict(profile)
    for schluessel in ("attack_home", "attack_away"):
        if korrigiert.get(schluessel) is not None:
            korrigiert[schluessel] = korrigiert[schluessel] * (1.0 + modifier)
    for schluessel in ("defence_home", "defence_away"):
        if korrigiert.get(schluessel) is not None:
            korrigiert[schluessel] = korrigiert[schluessel] * (1.0 - modifier)
    return korrigiert
