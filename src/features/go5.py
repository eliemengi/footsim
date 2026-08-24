"""
GO 5: Transferwirkung mit abnehmendem Gewicht im Saisonverlauf.

DIE FRAGE
---------
Ein Verein hat im Sommer seinen besten Innenverteidiger abgegeben und
einen Stuermer geholt. Am ersten Spieltag weiss das Modell davon nichts:
Seine Teamstaerke stammt aus der Vorsaison, in der beide Spieler noch
anders verteilt waren. GO 5 traegt diese Information nach.

DAS DOPPELZAEHLUNGSPROBLEM - UND WARUM ES λ GIBT
------------------------------------------------
Nach zehn Spieltagen ist die Lage umgekehrt. Der neue Stuermer hat Tore
erzielt, der fehlende Verteidiger hat Gegentore gekostet, und beides
steht laengst in den Ergebnissen dieser Saison - aus denen das Modell
seine Staerke bereits bildet (dynamic_weights.blend_profile).

Wuerde GO 5 seinen Transferaufschlag daneben unveraendert weiterrechnen,
zaehlte dieselbe Veraenderung zweimal. Deshalb sinkt das Gewicht:

    lambda_transfer(n) = k_transfer / (n + k_transfer)

n ist die Zahl der bereits absolvierten LIGASPIELE des Teams vor dem
Zielspiel.

WARUM NUR LIGASPIELE
--------------------
Weil genau gegen die Ligaspiele abgesichert wird. Der bestehende
In-Season-Blend (dynamic_weights.DEFAULT_K = 8) zaehlt Ligaspiele; die
Teamprofile entstehen aus Ligapartien. λ muss deshalb dieselbe Groesse
zaehlen, sonst schuetzt es vor der falschen Doppelung.

Pokalspiele blind mitzuzaehlen waere aus zwei Gruenden falsch: Sie gehen
nicht in die Staerkeberechnung ein, und sie werden haeufig mit stark
veraenderter Aufstellung bestritten - ein Pokalspiel gegen einen
Viertligisten sagt ueber die Wirkung eines Sommertransfers wenig.

WARUM k_transfer KLEINER IST ALS 8
----------------------------------
DEFAULT_K = 8 beschreibt, wie schnell die laufende Saison die Historie
ueberholt. Der Transferaufschlag muss SCHNELLER verschwinden als das,
sonst ueberlappen sich beide - er soll ja gerade die Luecke fuellen,
bevor die laufende Saison sie schliesst. k_transfer = 4 halbiert die
Halbwertszeit: Nach vier Ligaspielen ist der Transfereffekt halbiert,
waehrend die laufende Saison erst bei acht Spielen gleichzieht.

WAS GO 5 NICHT TUT
------------------
Keine Ablosesummen, keine Marktwerte, keine Bekanntheit, kein
Trainerwechselbonus, kein pauschales "viele Transfers sind schlecht"
und kein pauschales "Leihe ist schlecht". Ein Transfer wirkt genau
insoweit, wie Importance und Quality des Spielers belegt sind.
"""

import os

from src.features.go4 import _clamp, quality_weight


MODES = ("off", "shadow", "active")

#: Sichere Voreinstellung. Unabhaengig von GO 3 und GO 4.
DEFAULT_MODE = "shadow"

MODE_ENV_VAR = "FOOTSIM_GO5_MODE"


def current_mode():
    """
    Aktiver GO-5-Modus.

    Ausdruecklich getrennt von GO 4: GO 5 auf active zu setzen aktiviert
    GO 4 nicht. GO 5 benutzt lediglich Importance und Quality aus GO 4 -
    das sind Daten, keine Wirkung.
    """
    gesetzt = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    return gesetzt if gesetzt in MODES else DEFAULT_MODE


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

CONSTANTS = {
    "K_TRANSFER": {
        "wert": 4.0,
        "zweck": "Regularisierungskonstante des Transfer-Decays.",
        "bereich": (1.0, 8.0),
        "begruendung": (
            "Bei n = k ist das Gewicht genau die Haelfte. Vier "
            "Ligaspiele sind bewusst weniger als die acht des "
            "bestehenden In-Season-Blends (dynamic_weights.DEFAULT_K): "
            "Der Transferaufschlag muss verschwunden sein, BEVOR die "
            "laufende Saison dieselbe Veraenderung selbst abbildet, "
            "sonst zaehlt sie doppelt. Der Wert wird im Backtest gegen "
            "2, 3, 6 und 8 geprueft."
        ),
    },
    "TRANSFER_SENSITIVITY": {
        "wert": 0.025,
        "zweck": "Staerkeaenderung je Einheit Netto-Bedeutungsgewinn.",
        "bereich": (0.0, 0.06),
        "begruendung": (
            "Die Netto-Bedeutung ist eine Summe aus Importance mal "
            "Quality und liegt praktisch zwischen -1 und +1. Mit diesem "
            "Faktor ergibt ein sehr grosser Kaderumbruch bei n = 0 rund "
            "2,5 Prozent - knapp unter der Einzelgrenze und rund ein "
            "Zehntel Standardabweichung der gemessenen Staerkeskala."
        ),
    },
    "MIDFIELD_SPLIT": {
        "wert": 0.5,
        "zweck": "Anteil des Mittelfeldtransfers, der auf den Angriff wirkt.",
        "bereich": (0.0, 1.0),
        "begruendung": (
            "Wie in GO 4: Der Anbieter fuehrt nur 'Midfielder'. Jede "
            "andere Aufteilung waere eine unbelegte Behauptung ueber "
            "Spielsysteme."
        ),
    },
    "QUALITY_NEUTRAL": {
        "wert": 0.5,
        "zweck": "Quality-Wert, ab dem ein Spieler ueberdurchschnittlich ist.",
        "bereich": (0.0, 1.0),
        "begruendung": (
            "Quality ist ein Perzentil - 0.5 ist per Definition der "
            "Median der Positionsgruppe. Der Bezugspunkt muss dort "
            "liegen, sonst waere jeder Zugang automatisch eine "
            "Verbesserung und jeder Abgang ein Verlust."
        ),
    },
    "MAX_SINGLE_EFFECT": {
        "wert": 0.030,
        "zweck": "Obergrenze fuer Angriff bzw. Abwehr aus GO 5 allein.",
        "bereich": (0.0, 0.06),
        "begruendung": (
            "Dieselbe Groessenordnung wie in GO 4 und aus derselben "
            "Messung abgeleitet: drei Prozent sind rund ein Zehntel "
            "Standardabweichung. Kein Transfersommer darf eine "
            "Tabellenhierarchie umkehren."
        ),
    },
    "MIN_APPLY_THRESHOLD": {
        "wert": 0.001,
        "zweck": "Unterhalb dieses Betrags wird nicht angewendet.",
        "bereich": (0.0, 0.005),
        "begruendung": (
            "Wie in GO 3 und GO 4: verhindert Rauschen in Simulation "
            "und Diagnose ohne Erklaerwert."
        ),
    },
    "TRANSFER_WINDOW_DAYS": {
        "wert": 365,
        "zweck": "Wie weit zurueck ein Transfer beruecksichtigt wird.",
        "bereich": (90, 730),
        "begruendung": (
            "Ein Jahr deckt beide Transferfenster vor dem Zielspiel ab. "
            "Ohne Fenster gingen alle 84.943 lokal vorhandenen "
            "Ereignisse aus zwei Jahrzehnten in jede Rechnung ein - ein "
            "Wechsel von 2011 sagt ueber die Aufstellung von heute "
            "nichts."
        ),
    },
}

#: Wie Positionsgruppen auf Angriff und Abwehr wirken.
#:
#: Torhueter zaehlen zur Abwehr - eine eigene Torwartachse fuer
#: Transfers waere ueberzogen, weil Torwartwechsel selten sind und die
#: Datenlage dort am duennsten ist (nur 32 von 73 Bundesligatorhuetern
#: erhalten eine belastbare Quality).
POSITION_ROUTING = {
    "Attacker": {"attack": 1.0, "defence": 0.0},
    "Midfielder": {"attack": 0.5, "defence": 0.5},
    "Defender": {"attack": 0.0, "defence": 1.0},
    "Goalkeeper": {"attack": 0.0, "defence": 1.0},
}


def _c(name):
    return CONSTANTS[name]["wert"]


def constants_report():
    """Die Konstantentabelle in ausgabefaehiger Form, ohne Pfade."""
    return [
        {"name": name, "value": e["wert"], "purpose": e["zweck"],
         "range": list(e["bereich"]), "justification": e["begruendung"]}
        for name, e in CONSTANTS.items()
    ]


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def lambda_transfer(season_matches_played, k=None):
    """
    Gewicht des Transfereffekts nach n Ligaspielen.

        lambda(n) = k / (n + k)

    Eigenschaften, die getestet werden:
      lambda(0) = 1.0            maximal, aber weiterhin geclamped
      monoton fallend in n
      immer in (0, 1], nie negativ, nie steigend
      keine Division durch null, weil k > 0 erzwungen wird

    Ein fehlendes oder unsinniges n faellt auf 0 zurueck - also auf das
    MAXIMALE Gewicht. Das ist bewusst: Unbekannter Saisonfortschritt
    heisst "wir wissen nicht, wie viel schon sichtbar ist", und der
    Clamp begrenzt den Effekt ohnehin. Der Alternativweg - bei
    Unkenntnis auf null zu setzen - wuerde den Transfer stillschweigend
    verschwinden lassen.
    """
    if k is None:
        k = _c("K_TRANSFER")
    try:
        k = float(k)
    except (TypeError, ValueError):
        k = _c("K_TRANSFER")
    if k <= 0:
        # Eine Konstante von null oder darunter waere keine Glaettung,
        # sondern eine Division durch null. Sicherer Rueckfall.
        k = _c("K_TRANSFER")

    try:
        n = max(0.0, float(season_matches_played or 0))
    except (TypeError, ValueError):
        n = 0.0

    return k / (n + k)


def count_league_matches_before(timeline, cutoff, season):
    """
    Ligaspiele EINES Teams in DIESER Saison vor dem Stichtag.

    Nutzt die GO-3-Zeitleiste. Pokal- und Europapokalspiele werden
    ausdruecklich nicht mitgezaehlt (Begruendung im Modulkopf), und
    Spiele einer anderen Saison ebenso wenig - ein Team, das im Mai 34
    Spiele hatte, startet im August wieder bei null.
    """
    from src.features.match_timeline import LEAGUE_COMPETITIONS, matches_before

    if cutoff is None:
        return None

    return sum(
        1 for eintrag in matches_before(timeline or [], cutoff)
        if eintrag.get("competition") in LEAGUE_COMPETITIONS
        and eintrag.get("season") == season
    )


# ---------------------------------------------------------------------------
# Wirkung
# ---------------------------------------------------------------------------

def _player_significance(player_id, importance, quality):
    """
    Die spielerische Bedeutung eines Spielers: Rolle mal Guete.

    Rueckgabe: (bedeutung, positionsgruppe, belegt)

    bedeutung liegt zwischen -importance und +importance. Ein Spieler
    mit grosser Rolle und ueberdurchschnittlicher Quality traegt
    positiv, einer mit grosser Rolle und unterdurchschnittlicher
    negativ. Das ist der Grund, warum ein Abgang nicht automatisch ein
    Verlust ist: Wer einen Stammspieler abgibt, der schlechter war als
    der Positionsdurchschnitt, verliert nichts.

    Ohne beide Groessen gibt es keine Bedeutung - nicht null, sondern
    "nicht belegt". Der Aufrufer laesst den Transfer dann neutral.
    """
    imp = (importance or {}).get(player_id) or {}
    qual = (quality or {}).get(player_id) or {}

    rolle = imp.get("player_importance")
    guete = qual.get("player_quality")
    gruppe = imp.get("position_group") or qual.get("position_group")

    if rolle is None or guete is None or gruppe not in POSITION_ROUTING:
        return None, gruppe, False

    neutral = _c("QUALITY_NEUTRAL")
    return rolle * (guete - neutral) * 2.0, gruppe, True


def transfer_impact(incoming, outgoing, importance, quality,
                    season_matches_played=None, k=None,
                    excluded_player_ids=()):
    """
    Netto-Transferwirkung eines Teams vor einem Spiel.

    incoming / outgoing: normalisierte Transfereintraege aus
        transfer_events.team_window_transfers().

    excluded_player_ids: Spieler, die bereits anderswo gewirkt haben -
        typischerweise die von GO 4 als ausgefallen gefuehrten. Ohne
        diese Sperre koennte derselbe Spieler zweimal zaehlen: einmal
        als Zugang und einmal als Ausfall.

    Rueckgabe: alle in Teil H geforderten Felder plus lambda und
    Diagnose. Fehlt die Belegbarkeit, ist das Ergebnis exakt neutral.
    """
    ausgeschlossen = {int(p) for p in excluded_player_ids if p is not None}

    summen = {
        "incoming_attack_impact": 0.0,
        "outgoing_attack_impact": 0.0,
        "incoming_defence_impact": 0.0,
        "outgoing_defence_impact": 0.0,
        "incoming_goalkeeper_impact": 0.0,
        "outgoing_goalkeeper_impact": 0.0,
    }
    nutzbar = 0
    unbelegt = 0
    doppelt = 0
    nach_typ = {}

    for richtung, eintraege in (("incoming", incoming), ("outgoing", outgoing)):
        for eintrag in eintraege or []:
            pid = eintrag.get("player_id")
            if pid is None:
                continue
            pid = int(pid)

            if pid in ausgeschlossen:
                doppelt += 1
                continue

            # Ein Transfer, dessen Vereinszuordnung unklar ist, wirkt
            # nicht. Er koennte in die falsche Richtung zeigen.
            if not (eintrag.get("mapped_to_team") or eintrag.get("mapped_from_team")):
                unbelegt += 1
                continue

            bedeutung, gruppe, belegt = _player_significance(pid, importance, quality)
            if not belegt:
                unbelegt += 1
                continue

            routing = POSITION_ROUTING[gruppe]
            nutzbar += 1
            art = eintrag.get("transfer_type") or "unknown"
            nach_typ[art] = nach_typ.get(art, 0) + 1

            summen[f"{richtung}_attack_impact"] += bedeutung * routing["attack"]
            summen[f"{richtung}_defence_impact"] += bedeutung * routing["defence"]
            if gruppe == "Goalkeeper":
                summen[f"{richtung}_goalkeeper_impact"] += bedeutung

    lam = lambda_transfer(season_matches_played, k)

    # Netto: Was kam, minus was ging. Ein Abgang mit positiver Bedeutung
    # schwaecht, ein Zugang mit positiver Bedeutung staerkt.
    netto_angriff = (summen["incoming_attack_impact"]
                     - summen["outgoing_attack_impact"])
    netto_abwehr = (summen["incoming_defence_impact"]
                    - summen["outgoing_defence_impact"])

    faktor = _c("TRANSFER_SENSITIVITY") * lam
    grenze = _c("MAX_SINGLE_EFFECT")

    angriff, a_clamp = _clamp(netto_angriff * faktor, grenze)
    abwehr, d_clamp = _clamp(netto_abwehr * faktor, grenze)

    schwelle = _c("MIN_APPLY_THRESHOLD")
    if abs(angriff) < schwelle:
        angriff = 0.0
    if abs(abwehr) < schwelle:
        abwehr = 0.0

    gesamt = len(incoming or []) + len(outgoing or [])
    if nutzbar == 0:
        qualitaet = "unavailable" if gesamt else "complete"
    elif unbelegt == 0:
        qualitaet = "complete"
    elif nutzbar >= unbelegt:
        qualitaet = "partial"
    else:
        qualitaet = "fallback"

    return {
        "attack_modifier": round(angriff, 6),
        "defence_modifier": round(abwehr, 6),
        "net_attack_transfer_impact": round(netto_angriff, 6),
        "net_defence_transfer_impact": round(netto_abwehr, 6),
        "incoming_attack_impact": round(summen["incoming_attack_impact"], 6),
        "outgoing_attack_impact": round(summen["outgoing_attack_impact"], 6),
        "incoming_defence_impact": round(summen["incoming_defence_impact"], 6),
        "outgoing_defence_impact": round(summen["outgoing_defence_impact"], 6),
        "incoming_goalkeeper_impact": round(summen["incoming_goalkeeper_impact"], 6),
        "outgoing_goalkeeper_impact": round(summen["outgoing_goalkeeper_impact"], 6),
        "lambda_transfer": round(lam, 6),
        "season_matches_played": season_matches_played,
        "k_transfer": k if k is not None else _c("K_TRANSFER"),
        "number_of_usable_transfers": nutzbar,
        "transfers_seen": gesamt,
        "transfers_without_evidence": unbelegt,
        "transfers_excluded_as_absent": doppelt,
        "by_transfer_type": nach_typ,
        "transfer_data_quality": qualitaet,
        "clamp_applied": bool(a_clamp or d_clamp),
        "clamped_parts": ([n for n, c in (("attack", a_clamp),
                                          ("defence", d_clamp)) if c]),
        "reason": None if nutzbar else "no_usable_transfers",
    }


def empty_impact(reason="no_data"):
    """Exakt neutrale Transferwirkung. Fuer fehlende Datenlagen."""
    return {
        "attack_modifier": 0.0,
        "defence_modifier": 0.0,
        "net_attack_transfer_impact": 0.0,
        "net_defence_transfer_impact": 0.0,
        "incoming_attack_impact": 0.0,
        "outgoing_attack_impact": 0.0,
        "incoming_defence_impact": 0.0,
        "outgoing_defence_impact": 0.0,
        "incoming_goalkeeper_impact": 0.0,
        "outgoing_goalkeeper_impact": 0.0,
        "lambda_transfer": None,
        "season_matches_played": None,
        "k_transfer": _c("K_TRANSFER"),
        "number_of_usable_transfers": 0,
        "transfers_seen": 0,
        "transfers_without_evidence": 0,
        "transfers_excluded_as_absent": 0,
        "by_transfer_type": {},
        "transfer_data_quality": "unavailable",
        "clamp_applied": False,
        "clamped_parts": [],
        "reason": reason,
    }


def apply_modifier(profile, attack_modifier, defence_modifier):
    """
    Wendet die GO-5-Korrektur an. Original bleibt unveraendert.

    Vorzeichenlogik wie in GO 4: negativ ist immer "schlechter", und die
    Abwehr bekommt das umgekehrte Vorzeichen, weil groessere
    defence-Werte im Projekt schlechter sind.
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
