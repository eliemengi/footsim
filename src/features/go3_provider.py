"""
Beschaffung der GO-3-Merkmale - einmal je Spiel, nie je Simulationsdurchlauf.

DAS PROBLEM, DAS DIESES MODUL LOEST
-----------------------------------
Eine Monte-Carlo-Simulation wuerfelt zehntausende Male. Wuerde sie die
Belastungsmerkmale in der Schleife holen, waere jeder Durchlauf mit
Dateizugriffen und Zeitleistenaufbau belastet - und die Laufzeit stiege
um Groessenordnungen, ohne dass sich ein einziger Wert aendert. Die
Merkmale haengen am Spiel, nicht am Wuerfelwurf.

Deshalb: EIN Snapshot vor der Schleife, danach nur noch Lesen.

WAS GECACHT WIRD
----------------
    Zeitleiste     je Saisonmenge, im Prozess
    Merkmale       je (Saison, Team, Wettbewerb, Datenstand, Cutoff)

Der Datenstand geht bewusst in den Schluessel ein: kommen neue Spiele
hinzu, aendert sich der Stand und der alte Eintrag wird nicht mehr
getroffen. Ohne das wuerde ein Snapshot aus dem August im Mai noch
immer ausgeliefert.

KEINE ABFRAGE BEIM ANBIETER
---------------------------
Dieses Modul liest ausschliesslich lokale Historiedateien. Es gibt hier
keinen Netzzugriff, weder direkt noch mittelbar - auch nicht beim ersten
Aufruf. Ein Test haelt das fest.
"""

import threading

from src.features.go3 import compute_modifier, apply_modifier, current_mode
from src.features.match_timeline import build_timeline, team_timeline, coverage
from src.features.workload import workload_features, schedule_strength


#: Prozessweiter Zwischenspeicher. Ein Lock, weil Gunicorn mit mehreren
#: Threads je Worker laufen kann und ein halb gefuellter Eintrag sonst
#: sichtbar wuerde.
_TIMELINE_CACHE = {}
_FEATURE_CACHE = {}
_LOCK = threading.Lock()

#: Obergrenze, damit ein lang laufender Prozess nicht unbegrenzt waechst.
#: Bei Ueberschreitung wird der Merkmalscache geleert statt einzeln
#: verdraengt - die Merkmale sind billig nachzubauen, sobald die
#: Zeitleiste steht.
MAX_FEATURE_ENTRIES = 20000


def _timeline_for(seasons):
    """Zeitleiste einer Saisonmenge, im Prozess gehalten."""
    schluessel = tuple(sorted(seasons))
    with _LOCK:
        vorhanden = _TIMELINE_CACHE.get(schluessel)
    if vorhanden is not None:
        return vorhanden

    eintraege, diagnose = build_timeline(schluessel)
    paket = {
        "entries": eintraege,
        "diagnostics": diagnose,
        "coverage": coverage(eintraege),
        # Datenstand: aendert sich, sobald Spiele hinzukommen. Geht in
        # jeden Merkmalsschluessel ein.
        "data_state": f"{len(eintraege)}:{schluessel}",
        "by_team": {},
    }
    with _LOCK:
        _TIMELINE_CACHE[schluessel] = paket
    return paket


def _team_entries(paket, team_id):
    """Die Spiele eines Teams - je Team einmal aufgebaut."""
    with _LOCK:
        vorhanden = paket["by_team"].get(team_id)
    if vorhanden is not None:
        return vorhanden

    eintraege = team_timeline(paket["entries"], team_id)
    with _LOCK:
        paket["by_team"][team_id] = eintraege
    return eintraege


def clear_cache():
    """
    Zwischenspeicher leeren.

    Fuer Tests und fuer den Fall, dass die Historiedateien im laufenden
    Betrieb erneuert wurden. Loescht KEINE Daten auf der Platte.
    """
    with _LOCK:
        _TIMELINE_CACHE.clear()
        _FEATURE_CACHE.clear()


def cache_stats():
    """Fuellstand des Zwischenspeichers - fuer Diagnose."""
    with _LOCK:
        return {
            "timelines": len(_TIMELINE_CACHE),
            "features": len(_FEATURE_CACHE),
            "max_features": MAX_FEATURE_ENTRIES,
        }


def team_features(team_id, cutoff, seasons, competition=None,
                  strength_lookup=None, league_average=None):
    """
    Vollstaendiger Merkmalssatz eines Teams vor einem Spiel.

    cutoff: datetime des Anpfiffs. Nur Spiele STRIKT davor gehen ein.

    Rueckgabe enthaelt Belastung, Spielplanhaerte und die daraus
    berechnete Korrektur - aber wendet sie NICHT an. Das Anwenden ist
    Sache von adjusted_profiles(), damit der Vergleich vorher/nachher
    immer moeglich bleibt.
    """
    paket = _timeline_for(seasons)

    schluessel = (
        tuple(sorted(seasons)), team_id, competition,
        paket["data_state"], cutoff.isoformat() if cutoff else None,
    )
    with _LOCK:
        vorhanden = _FEATURE_CACHE.get(schluessel)
    if vorhanden is not None:
        return vorhanden

    eintraege = _team_entries(paket, team_id)
    belastung = workload_features(eintraege, cutoff)
    plan = schedule_strength(eintraege, cutoff, strength_lookup or {})
    korrektur = compute_modifier(belastung, plan, league_average)

    ergebnis = {
        "team_id": team_id,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "competition": competition,
        "workload": belastung,
        "schedule": plan,
        "modifier": korrektur,
    }

    with _LOCK:
        if len(_FEATURE_CACHE) >= MAX_FEATURE_ENTRIES:
            _FEATURE_CACHE.clear()
        _FEATURE_CACHE[schluessel] = ergebnis
    return ergebnis


def league_average_strength(strength_lookup):
    """
    Bezugspunkt fuer die Spielplanhaerte.

    Ohne ihn sagt eine absolute Gegnerstaerke nichts aus. Der
    Durchschnitt stammt aus DEMSELBEN Lookup, das auch die Gegner
    bewertet - eine andere Quelle waere nicht vergleichbar.
    """
    if not strength_lookup:
        return None
    werte = [float(w) for w in strength_lookup.values() if w is not None]
    if not werte:
        return None
    return sum(werte) / len(werte)


def fixture_snapshot(home_id, away_id, cutoff, seasons, competition=None,
                     strength_lookup=None, home_profile=None, away_profile=None):
    """
    Der vollstaendige GO-3-Stand fuer EINE Begegnung.

    Das ist der Snapshot aus Phase 8: einmal vor der Simulation gebaut,
    danach unveraendert weitergereicht. Er enthaelt beide Staende -
    Ausgangswerte und korrigierte - damit der Shadow-Modus vergleichen
    kann und der aktive Modus nichts nachrechnen muss.

    Rueckgabe:
        {
          "mode":        "off" | "shadow" | "active",
          "applied":     bool     ob die Korrektur die Simulation aendert
          "home": {...}, "away": {...},
          "baseline_profiles": {...}, "adjusted_profiles": {...},
          "coverage": {...},
        }
    """
    modus = current_mode()
    paket = _timeline_for(seasons)
    durchschnitt = league_average_strength(strength_lookup)

    heim = team_features(home_id, cutoff, seasons, competition,
                         strength_lookup, durchschnitt)
    gast = team_features(away_id, cutoff, seasons, competition,
                         strength_lookup, durchschnitt)

    # In off und shadow bleibt die Simulation unberuehrt. Gerechnet wird
    # in shadow trotzdem vollstaendig - sonst liesse sich die Wirkung
    # nie beurteilen, bevor man sie einschaltet.
    anwenden = (modus == "active")

    basis = {"home": home_profile, "away": away_profile}
    korrigiert = {
        "home": apply_modifier(home_profile, heim["modifier"]["modifier"])
        if anwenden else (dict(home_profile) if home_profile else home_profile),
        "away": apply_modifier(away_profile, gast["modifier"]["modifier"])
        if anwenden else (dict(away_profile) if away_profile else away_profile),
    }

    return {
        "mode": modus,
        "applied": anwenden,
        "home": heim,
        "away": gast,
        "baseline_profiles": basis,
        "adjusted_profiles": korrigiert,
        "coverage": paket["coverage"],
    }


# ---------------------------------------------------------------------------
# Shadow-Modus (Phase 9)
# ---------------------------------------------------------------------------

def shadow_report(snapshot, baseline_probabilities=None,
                  adjusted_probabilities=None):
    """
    Was GO 3 getan HAETTE - ohne dass es etwas getan hat.

    Nimmt einen Snapshot und optional beide Wahrscheinlichkeitssaetze und
    stellt sie gegenueber. Genau diese Ausgabe entscheidet, ob der Modus
    auf active gehen darf.

    Enthaelt bewusst keine Pfade, keine Schluessel und keine
    Anbieterantworten - sie ist fuer die oeffentliche Diagnose geeignet.
    """
    heim = snapshot["home"]["modifier"]
    gast = snapshot["away"]["modifier"]

    bericht = {
        "mode": snapshot["mode"],
        "applied_to_simulation": snapshot["applied"],
        "home": {
            "team_id": snapshot["home"]["team_id"],
            "modifier": heim["modifier"],
            "components": heim["components"],
            "clamp_applied": heim["clamp_applied"],
            "clamped_parts": heim["clamped_parts"],
            "data_quality": heim["data_quality"],
            "congestion_level": snapshot["home"]["workload"]["congestion_level"],
            "rest_hours": snapshot["home"]["workload"]["rest_hours"],
        },
        "away": {
            "team_id": snapshot["away"]["team_id"],
            "modifier": gast["modifier"],
            "components": gast["components"],
            "clamp_applied": gast["clamp_applied"],
            "clamped_parts": gast["clamped_parts"],
            "data_quality": gast["data_quality"],
            "congestion_level": snapshot["away"]["workload"]["congestion_level"],
            "rest_hours": snapshot["away"]["workload"]["rest_hours"],
        },
        # Die relative Verschiebung zwischen den Teams ist die Groesse,
        # die den Ausgang beeinflusst - nicht der Einzelwert. Zwei
        # gleich muede Teams spielen ein normales Spiel.
        "relative_shift": round(heim["modifier"] - gast["modifier"], 6),
    }

    if baseline_probabilities and adjusted_probabilities:
        diffs = {}
        for schluessel in ("home_win", "draw", "away_win"):
            vorher = baseline_probabilities.get(schluessel)
            nachher = adjusted_probabilities.get(schluessel)
            if vorher is not None and nachher is not None:
                diffs[schluessel] = round(nachher - vorher, 6)
        bericht["baseline_probabilities"] = baseline_probabilities
        bericht["adjusted_probabilities"] = adjusted_probabilities
        bericht["probability_diffs"] = diffs
        if diffs:
            bericht["max_probability_change"] = round(
                max(abs(w) for w in diffs.values()), 6)

    return bericht


# ---------------------------------------------------------------------------
# API- und Diagnosedaten (Phase 15)
# ---------------------------------------------------------------------------

def _team_block(seite):
    """Die oeffentlich zeigbaren Merkmale einer Mannschaft."""
    belastung = seite["workload"]
    plan = seite["schedule"]
    korrektur = seite["modifier"]
    return {
        "team_id": seite["team_id"],
        "rest_hours": belastung["rest_hours"],
        "rest_days": belastung["rest_days"],
        "short_rest": belastung["short_rest_flag"],
        "previous_match": belastung["previous_match_datetime"],
        "previous_match_competition": belastung["previous_match_competition"],
        "matches_last_7_days": belastung["matches_last_7_days"],
        "matches_last_14_days": belastung["matches_last_14_days"],
        "matches_last_21_days": belastung["matches_last_21_days"],
        "matches_last_30_days": belastung["matches_last_30_days"],
        "consecutive_away_matches": belastung["consecutive_away_matches"],
        "congestion_level": belastung["congestion_level"],
        "competitions_included": belastung["competitions_included"],
        "number_of_usable_matches": belastung["number_of_usable_matches"],
        "recent_opponent_strength": plan["recent_opponent_strength"],
        "number_of_usable_opponents": plan["number_of_usable_opponents"],
        "schedule_strength_quality": plan["schedule_strength_quality"],
        "data_quality": belastung["data_quality"],
        "rest_data_quality": belastung["rest_data_quality"],
        "modifier": korrektur["modifier"],
        "modifier_components": korrektur["components"],
        "clamp_applied": korrektur["clamp_applied"],
    }


def api_metadata(snapshot):
    """
    Der GO-3-Block fuer die API-Antwort.

    BEWUSST OHNE: Dateipfade, Umgebungsvariablen, Schluessel,
    Anbieterantworten, Stacktraces. Alles hier ist entweder eine Zahl
    aus der Zeitleiste oder ein Wort aus einer festen Menge.

    Diese Funktion wirft nicht. Ein normaler Zustand - keine Historie,
    Saisonbeginn, ein Team ohne Zuordnung - ist kein Fehler, sondern
    eine Datenlage, und muss als solche in der Antwort stehen. Ein
    HTTP 500 oder 503 dafuer waere schlicht falsch: der Dienst ist
    verfuegbar, er hat nur nichts zu berichten.
    """
    if not snapshot:
        return {
            "mode": current_mode(),
            "applied": False,
            "available": False,
            "reason": "no_snapshot",
        }

    try:
        return {
            "mode": snapshot["mode"],
            "applied": snapshot["applied"],
            "available": True,
            "home": _team_block(snapshot["home"]),
            "away": _team_block(snapshot["away"]),
            "relative_shift": round(
                snapshot["home"]["modifier"]["modifier"]
                - snapshot["away"]["modifier"]["modifier"], 6),
            "coverage": {
                "competitions": snapshot["coverage"]["competitions"],
                "total_matches": snapshot["coverage"]["total_matches"],
                "known_gaps": snapshot["coverage"]["known_gaps"],
                "time_precision": snapshot["coverage"].get("time_precision"),
            },
        }
    except (KeyError, TypeError):
        # Ein unerwartet geformter Snapshot darf die Antwort nicht
        # zerstoeren. Die Diagnose ist eine Beigabe, kein Kernergebnis.
        return {
            "mode": current_mode(),
            "applied": False,
            "available": False,
            "reason": "incomplete_snapshot",
        }


def safe_fixture_snapshot(*args, **kwargs):
    """
    fixture_snapshot, das im Fehlerfall None liefert statt zu werfen.

    Fuer den Produktivpfad: GO 3 ist eine Ergaenzung. Faellt sie aus,
    muss die Simulation trotzdem ein Ergebnis liefern - ohne Korrektur,
    aber vollstaendig. Die Alternative waere, eine funktionierende
    Vorhersage wegen einer fehlenden Nebenangabe zu verweigern.
    """
    try:
        return fixture_snapshot(*args, **kwargs)
    except Exception:
        return None
