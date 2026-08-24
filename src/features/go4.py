"""
GO 4: Kaderverfuegbarkeit als vorsichtige Korrektur der Teamstaerke.

WAS DIESES MODUL IST
--------------------
Die einzige Stelle, an der aus Importance, Quality und Verfuegbarkeit
(squad_availability.py) eine Veraenderung der Simulationsstaerke wird.
Wer wissen will, wie stark GO 4 wirken kann, liest die Konstantentabelle
unten - und sonst nichts.

VERHAELTNIS ZU GO 3 UND GO 5
----------------------------
Drei getrennte Modi, drei getrennte Konstantentabellen, drei getrennte
Clamps. GO 4 aktiv zu schalten aktiviert weder GO 3 noch GO 5. GO 5 darf
die Daten aus GO 4 benutzen, ohne dass GO 4 wirken muss - Importance und
Quality sind Daten, keine Wirkung.

DIE SKALA
---------
Bevor irgendein Prozentwert festgelegt wurde, wurde die tatsaechliche
Skala der Staerkewerte gemessen (288 Teamsaisons, 2023-2025):

    attack_home    Median 0.949   Standardabweichung 0.269
    attack_away    Median 0.962   Standardabweichung 0.260
    defence_home   Median 0.982   Standardabweichung 0.225
    defence_away   Median 0.986   Standardabweichung 0.197

Ein Prozent Veraenderung entspricht damit rund 3,5 Prozent EINER
Standardabweichung. Die Spannweite vom 5. zum 95. Perzentil betraegt
0,83 - also etwa drei Standardabweichungen. Daraus folgt unmittelbar:
Ein Effekt von drei Prozent verschiebt ein Team um rund ein Zehntel
Standardabweichung. Das ist sichtbar und kippt keine Hierarchie. Genau
dort liegen die Obergrenzen unten.

DER MODUS
---------
    off      GO 4 rechnet nicht. Simulation exakt wie vorher.
    shadow   GO 4 rechnet vollstaendig, aendert aber NICHTS.
    active   GO 4 wirkt.

Voreinstellung ist shadow.
"""

import os


MODES = ("off", "shadow", "active")

#: Sichere Voreinstellung.
DEFAULT_MODE = "shadow"

MODE_ENV_VAR = "FOOTSIM_GO4_MODE"


def current_mode():
    """
    Aktiver GO-4-Modus.

    Ein unbekannter Wert faellt auf die sichere Voreinstellung zurueck,
    statt zu werfen: eine vertippte Umgebungsvariable darf die Anwendung
    weder lahmlegen noch heimlich aktivieren.
    """
    gesetzt = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    return gesetzt if gesetzt in MODES else DEFAULT_MODE


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

CONSTANTS = {
    "ATTACK_SENSITIVITY": {
        "wert": 0.08,
        "zweck": "Angriffsaenderung je Einheit Angriffs-Verfuegbarkeitsverlust.",
        "bereich": (0.0, 0.20),
        "begruendung": (
            "Der Verlust einer Positionsgruppe ist auf 0.35 begrenzt "
            "(squad_availability.MAX_POSITION_LOSS). Mit diesem Faktor "
            "ergibt der denkbar schwerste Angriffsausfall rund 2,8 "
            "Prozent - knapp unter der Einzelgrenze und damit etwa ein "
            "Zehntel Standardabweichung. Ein Team, dem der beste "
            "Stuermer fehlt, wird schwaecher, aber es wird nicht zu "
            "einem anderen Team."
        ),
    },
    "DEFENCE_SENSITIVITY": {
        "wert": 0.07,
        "zweck": "Abwehraenderung je Einheit Abwehr-Verfuegbarkeitsverlust.",
        "bereich": (0.0, 0.20),
        "begruendung": (
            "Etwas kleiner als der Angriffsfaktor, aus zwei Gruenden. "
            "Erstens ist die Streuung der Abwehrwerte geringer (0.225 "
            "gegen 0.269), dieselbe Prozentzahl bewegt dort also mehr. "
            "Zweitens ist Abwehrleistung staerker eine Mannschafts- als "
            "eine Einzelleistung: Faellt ein Innenverteidiger aus, "
            "steht die Grundordnung weiter."
        ),
    },
    "GOALKEEPER_SENSITIVITY": {
        "wert": 0.06,
        "zweck": "Abwehraenderung je Einheit Torwart-Verfuegbarkeitsverlust.",
        "bereich": (0.0, 0.20),
        "begruendung": (
            "Getrennt gefuehrt, weil der Torwart die einzige Position "
            "ohne Vertretung im laufenden Spiel ist - eine "
            "Sollbesetzung von genau eins. Der Faktor ist trotzdem der "
            "kleinste der drei: Der Abstand zwischen Stamm- und "
            "Ersatztorwart ist in Spitzenmannschaften geringer als der "
            "zwischen Stammstuermer und Ersatz, und die Datenlage ist "
            "duenner - nur 32 von 73 Torhuetern der Bundesliga 2025/26 "
            "erhalten ueberhaupt eine belastbare Quality."
        ),
    },
    "MIDFIELD_SENSITIVITY": {
        "wert": 0.05,
        "zweck": "Aenderung je Einheit Mittelfeld-Verfuegbarkeitsverlust.",
        "bereich": (0.0, 0.15),
        "begruendung": (
            "Der kleinste Faktor, und er wirkt geteilt auf Angriff und "
            "Abwehr (MIDFIELD_SPLIT). Grund: Der Anbieter fuehrt nur "
            "'Midfielder' ohne Unterteilung. Ob ein Ausfall die "
            "Offensive oder die Defensive trifft, ist damit nicht "
            "bestimmbar. Eine genauere Rollenzuordnung waere erfunden - "
            "also wirkt der Ausfall vorsichtig auf beides."
        ),
    },
    "MIDFIELD_SPLIT": {
        "wert": 0.5,
        "zweck": "Anteil des Mittelfeldeffekts, der auf den Angriff entfaellt.",
        "bereich": (0.0, 1.0),
        "begruendung": (
            "Genau die Haelfte, weil nichts in den Daten eine andere "
            "Aufteilung stuetzt. Jede Abweichung von 0.5 waere eine "
            "Behauptung ueber Spielsysteme, die dieses Projekt nicht "
            "belegen kann."
        ),
    },
    "MAX_SINGLE_EFFECT": {
        "wert": 0.030,
        "zweck": "Obergrenze fuer den Betrag eines einzelnen Bereichseffekts.",
        "bereich": (0.0, 0.06),
        "begruendung": (
            "Drei Prozent entsprechen rund einem Zehntel "
            "Standardabweichung der gemessenen Staerkeverteilung. Damit "
            "kann kein einzelner Spielerausfall eine Begegnung kippen, "
            "deren Ausgang die Teamstaerke bereits klar vorzeichnet."
        ),
    },
    "MAX_TOTAL_EFFECT": {
        "wert": 0.050,
        "zweck": "Obergrenze fuer Angriff bzw. Abwehr eines Teams aus GO 4.",
        "bereich": (0.0, 0.09),
        "begruendung": (
            "Kleiner als die Summe der Einzelgrenzen. Ausfaelle haeufen "
            "sich nicht unabhaengig: Eine Mannschaft in einer "
            "Verletzungskrise verliert Spieler ueber mehrere Positionen "
            "zugleich, und die Ursachen ueberschneiden sich. Sie voll "
            "zu addieren wuerde dieselbe Lage mehrfach zaehlen."
        ),
    },
    "MAX_COMBINED_GO4_GO5": {
        "wert": 0.070,
        "zweck": "Obergrenze fuer GO 4 und GO 5 zusammen, je Wert.",
        "bereich": (0.0, 0.12),
        "begruendung": (
            "Sieben Prozent sind rund ein Viertel Standardabweichung - "
            "weniger als der Abstand zwischen zwei benachbarten "
            "Mittelfeldteams. Die Grenze steht hier und nicht in GO 5, "
            "damit es genau EINE Stelle gibt, an der die gemeinsame "
            "Wirkung begrenzt wird."
        ),
    },
    "MIN_APPLY_THRESHOLD": {
        "wert": 0.001,
        "zweck": "Unterhalb dieses Betrags wird nicht angewendet.",
        "bereich": (0.0, 0.005),
        "begruendung": (
            "Verhindert, dass ein Effekt von einem Zehntelpromille die "
            "Simulation numerisch verunruhigt und die Diagnose mit "
            "Rauschen fuellt, ohne etwas zu erklaeren."
        ),
    },
}

#: Wie stark ein Effekt je Datenqualitaet wirkt. Deckungsgleich mit
#: GO 3 (workload.QUALITY_WEIGHTS), damit im Projekt nicht zwei
#: verschiedene Vorstellungen von "halb belegt" existieren.
QUALITY_WEIGHTS = {
    "complete": 1.0,
    "partial": 0.6,
    "fallback": 0.3,
    "unavailable": 0.0,
}


def _c(name):
    """Wert einer Konstante. Zentral, damit es keine zweite Quelle gibt."""
    return CONSTANTS[name]["wert"]


def quality_weight(klasse):
    """Einflussfaktor einer Qualitaetsklasse. Unbekannt = neutral."""
    return QUALITY_WEIGHTS.get(klasse, 0.0)


def constants_report():
    """Die Konstantentabelle in ausgabefaehiger Form, ohne Pfade."""
    return [
        {"name": name, "value": e["wert"], "purpose": e["zweck"],
         "range": list(e["bereich"]), "justification": e["begruendung"]}
        for name, e in CONSTANTS.items()
    ]


def _clamp(wert, grenze):
    """Auf [-grenze, +grenze] beschneiden. Rueckgabe: (wert, beschnitten)."""
    if wert > grenze:
        return grenze, True
    if wert < -grenze:
        return -grenze, True
    return wert, False


def compute_modifier(availability):
    """
    Angriffs- und Abwehrkorrektur aus der Kaderverfuegbarkeit.

    Rueckgabe:
        {
          "attack_modifier":     float,  Abweichung, 0.0 = neutral
          "defence_modifier":    float,
          "goalkeeper_modifier": float,  Anteil innerhalb der Abwehr
          "components": {...},
          "clamp_applied": bool, "clamped_parts": [...],
          "data_quality": str, "reason": str|None,
        }

    Beide Werte sind ABWEICHUNGEN, nicht Faktoren: 0.0 heisst "keine
    Aenderung". Das macht Neutralitaet bei fehlenden Daten pruefbar -
    ein Faktor 1.0 waere leichter mit einem Fehler zu verwechseln.

    VORZEICHEN: Ein Ausfall SENKT den Angriffswert und ERHOEHT den
    Abwehrwert, weil groessere defence-Werte im Projekt schlechter sind.
    Beide Modifikatoren werden hier trotzdem als "Verschlechterung
    negativ" gefuehrt; apply_modifier dreht das Vorzeichen fuer die
    Abwehr um. So bleibt die Diagnose lesbar: negativ ist immer
    schlechter.
    """
    leer = {
        "attack_modifier": 0.0,
        "defence_modifier": 0.0,
        "goalkeeper_modifier": 0.0,
        "components": {},
        "clamp_applied": False,
        "clamped_parts": [],
        "data_quality": "unavailable",
        "reason": None,
    }

    if not availability or not availability.get("available"):
        leer["reason"] = (availability or {}).get(
            "reason", "no_availability_data")
        return leer

    klasse = availability.get("data_quality") or "unavailable"
    gewicht = quality_weight(klasse)
    if gewicht <= 0.0:
        leer["reason"] = "quality_unavailable"
        leer["data_quality"] = klasse
        return leer

    positionen = availability.get("positions") or {}

    def verlust(pos):
        return (positionen.get(pos) or {}).get("loss") or 0.0

    angriff_verlust = verlust("Attacker")
    abwehr_verlust = verlust("Defender")
    torwart_verlust = verlust("Goalkeeper")
    mittelfeld_verlust = verlust("Midfielder")

    teilung = _c("MIDFIELD_SPLIT")
    mittelfeld = mittelfeld_verlust * _c("MIDFIELD_SENSITIVITY")

    roh = {
        "attack_from_attackers": -angriff_verlust * _c("ATTACK_SENSITIVITY"),
        "attack_from_midfield": -mittelfeld * teilung,
        "defence_from_defenders": -abwehr_verlust * _c("DEFENCE_SENSITIVITY"),
        "defence_from_goalkeeper": -torwart_verlust * _c("GOALKEEPER_SENSITIVITY"),
        "defence_from_midfield": -mittelfeld * (1.0 - teilung),
    }

    grenze = _c("MAX_SINGLE_EFFECT")
    teile = {}
    beschnitten = []
    for name, wert in roh.items():
        gewichtet, wurde = _clamp(wert * gewicht, grenze)
        if wurde:
            beschnitten.append(name)
        teile[name] = gewichtet

    angriff = teile["attack_from_attackers"] + teile["attack_from_midfield"]
    abwehr = (teile["defence_from_defenders"]
              + teile["defence_from_goalkeeper"]
              + teile["defence_from_midfield"])

    gesamt = _c("MAX_TOTAL_EFFECT")
    angriff, a_beschnitten = _clamp(angriff, gesamt)
    abwehr, d_beschnitten = _clamp(abwehr, gesamt)
    if a_beschnitten:
        beschnitten.append("attack_total")
    if d_beschnitten:
        beschnitten.append("defence_total")

    schwelle = _c("MIN_APPLY_THRESHOLD")
    if abs(angriff) < schwelle:
        angriff = 0.0
    if abs(abwehr) < schwelle:
        abwehr = 0.0

    return {
        "attack_modifier": round(angriff, 6),
        "defence_modifier": round(abwehr, 6),
        "goalkeeper_modifier": round(teile["defence_from_goalkeeper"], 6),
        "components": {k: round(v, 6) for k, v in teile.items()},
        "components_raw": {k: round(v, 6) for k, v in roh.items()},
        "clamp_applied": bool(beschnitten),
        "clamped_parts": beschnitten,
        "data_quality": klasse,
        "quality_weight": round(gewicht, 4),
        "reason": None,
    }


def apply_modifier(profile, attack_modifier, defence_modifier):
    """
    Wendet die GO-4-Korrektur auf ein Staerkeprofil an.

    Das Original wird NICHT veraendert - der Aufrufer braucht beide
    Staende fuer den Schattenvergleich.

    Die Abwehr bekommt das umgekehrte Vorzeichen: Ein negativer
    defence_modifier bedeutet "schlechtere Abwehr", und schlechtere
    Abwehr heisst im Projekt GROESSERE defence-Werte.
    """
    if not profile:
        return profile
    if not attack_modifier and not defence_modifier:
        return dict(profile)

    korrigiert = dict(profile)
    for schluessel in ("attack_home", "attack_away"):
        if korrigiert.get(schluessel) is not None:
            korrigiert[schluessel] = korrigiert[schluessel] * (1.0 + attack_modifier)
    for schluessel in ("defence_home", "defence_away"):
        if korrigiert.get(schluessel) is not None:
            korrigiert[schluessel] = korrigiert[schluessel] * (1.0 - defence_modifier)
    return korrigiert


def combined_clamp(go4_modifier, go5_modifier):
    """
    Gemeinsame Obergrenze fuer GO 4 und GO 5.

    Genau EINE Stelle im Projekt begrenzt die Summe beider Features.
    Ohne sie koennten zwei je fuer sich zulaessige Korrekturen zusammen
    eine Wirkung ergeben, die keiner der beiden Tabellen entspricht.

    Rueckgabe: (summe, beschnitten)
    """
    return _clamp((go4_modifier or 0.0) + (go5_modifier or 0.0),
                  _c("MAX_COMBINED_GO4_GO5"))
