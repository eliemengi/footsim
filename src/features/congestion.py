"""
Belastungs- und Erholungsmerkmale aus einer wettbewerbsuebergreifenden
Spielhistorie.

Die Idee
--------
Ein Team, das Mittwoch in der Champions League gespielt hat und Samstag
in der Liga antritt, hat drei Tage Pause. Ein Gegner ohne Europapokal hat
sieben. Dieser Unterschied ist eine der wenigen objektiv messbaren
Groessen, die vor Anpfiff feststehen - und er taucht im aktuellen Modell
ueberhaupt nicht auf, weil Teamstaerken je Wettbewerb getrennt gerechnet
werden.

Datenlage (Stand dieser Implementierung)
----------------------------------------
Die Zeitleiste kann nur so vollstaendig sein wie die zugrunde liegenden
Daten. Verfuegbar und persistiert sind:

    die fuenf nationalen Ligen   data/historical/{BL1,PL,PD,SA,FL1}_*.json
    die Champions League         data/historical/CL_*.json

NICHT verfuegbar sind die nationalen Pokale (DFB-Pokal, FA Cup, Copa del
Rey, Coppa Italia, Coupe de France). Der football-data.org-Tarif dieses
Projekts liefert sie nicht: Ein direkter Abruf beantwortet DFB, FAC, CDR
und CDF jeweils mit HTTP 403. Auch Europa League und Conference League
fehlen.

Folge fuer die Auswertung: In Pokalwochen unterschaetzt jede Kennzahl
hier die tatsaechliche Belastung. Das ist eine bekannte, benannte Luecke -
sie wird NICHT durch Schaetzungen gefuellt. Wer diese Merkmale spaeter
benutzt, sollte coverage() mit auswerten und die Luecke im Modell
beruecksichtigen, statt sie zu ignorieren.

Point-in-Time
-------------
Alle Funktionen hier schneiden ueber src/features/point_in_time.py. Ein
Merkmal fuer ein Spiel am 1. Oktober sieht ausschliesslich Partien, die
davor stattgefunden haben. Der Schnitt ist bei gleichem Datum ohne
Uhrzeit bewusst streng - siehe dort.

Bewusst NICHT verdrahtet
------------------------
Diese Merkmale fliessen NICHT in expected_goals() ein. Ihre Wirkung soll
erst gemessen werden, bevor sie das Modell veraendern. Alles andere waere
genau die Art von unbelegter Modellaenderung, die diese Phase vermeiden
soll.
"""

from src.features.point_in_time import (
    match_date,
    match_time,
    matches_known_at,
    sort_chronologically,
)


# Zeitfenster, ueber die Belastung ueblicherweise betrachtet wird.
DEFAULT_WINDOWS = (7, 14, 30)


def _to_ordinal(date_text):
    """Wandelt 'YYYY-MM-DD' in eine Tageszahl fuer Differenzrechnungen."""
    from datetime import date

    try:
        year, month, day = (int(part) for part in date_text.split("-"))
        return date(year, month, day).toordinal()
    except (AttributeError, ValueError):
        return None


def build_team_timeline(competition_matches, team_id):
    """
    Fuehrt die Spiele eines Teams aus mehreren Wettbewerben zusammen.

    competition_matches: { wettbewerb: [matches] }, z. B.
                         {"BL1": [...], "CL": [...]}

    Rueckgabe: chronologisch sortierte Liste. Jeder Eintrag traegt
    zusaetzlich competition und is_home, damit spaeter erkennbar bleibt,
    woher die Belastung kam.

    Ein Spiel ohne verwertbares Datum wird uebersprungen: Es liesse sich
    weder einsortieren noch fuer Abstaende verwenden.
    """
    timeline = []

    for competition, matches in (competition_matches or {}).items():
        for match in matches or []:
            home = match.get("home_id")
            away = match.get("away_id")
            if team_id not in (home, away):
                continue
            if match_date(match) is None:
                continue

            entry = dict(match)
            entry["competition"] = competition
            entry["is_home"] = (home == team_id)
            entry["opponent_id"] = away if home == team_id else home
            timeline.append(entry)

    return sort_chronologically(timeline)


def days_since_last_match(timeline, cutoff, inclusive=False):
    """
    Tage zwischen dem letzten bekannten Spiel und dem Stichtag.

    None, wenn kein frueheres Spiel vorliegt - etwa zu Saisonbeginn. Das
    ist ehrlicher als eine grosse Zahl, die "lange ausgeruht" suggeriert,
    obwohl schlicht nichts bekannt ist.
    """
    known = matches_known_at(timeline, cutoff, inclusive=inclusive)
    if not known:
        return None

    last = sort_chronologically(known)[-1]
    last_ordinal = _to_ordinal(match_date(last))

    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)
    cutoff_ordinal = _to_ordinal(cutoff_text[:10])

    if last_ordinal is None or cutoff_ordinal is None:
        return None

    return cutoff_ordinal - last_ordinal


def matches_in_last_days(timeline, cutoff, days, inclusive=False):
    """
    Anzahl der Spiele in den letzten n Tagen vor dem Stichtag.

    Das Fenster ist halboffen: [cutoff - days, cutoff). Ein Spiel genau
    am Stichtag zaehlt nur bei inclusive=True mit.
    """
    known = matches_known_at(timeline, cutoff, inclusive=inclusive)
    if not known:
        return 0

    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)
    cutoff_ordinal = _to_ordinal(cutoff_text[:10])
    if cutoff_ordinal is None:
        return 0

    lower_bound = cutoff_ordinal - days
    count = 0

    for match in known:
        played = _to_ordinal(match_date(match))
        if played is not None and played >= lower_bound:
            count += 1

    return count


def competitions_in_last_days(timeline, cutoff, days, inclusive=False):
    """
    Aus welchen Wettbewerben die Belastung der letzten n Tage stammt.

    Rueckgabe: { wettbewerb: anzahl }. Macht sichtbar, ob ein Team
    zusaetzlich international gefordert war.
    """
    known = matches_known_at(timeline, cutoff, inclusive=inclusive)

    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)
    cutoff_ordinal = _to_ordinal(cutoff_text[:10])
    if cutoff_ordinal is None:
        return {}

    lower_bound = cutoff_ordinal - days
    counts = {}

    for match in known:
        played = _to_ordinal(match_date(match))
        if played is None or played < lower_bound:
            continue
        competition = match.get("competition") or "unknown"
        counts[competition] = counts.get(competition, 0) + 1

    return counts


def travel_load_in_last_days(timeline, cutoff, days, inclusive=False):
    """
    Wie viele der juengsten Spiele Auswaertsspiele waren.

    Kein Ersatz fuer echte Reisedistanzen - die liefert keiner unserer
    Anbieter. Aber die Heim/Auswaerts-Verteilung ist zuverlaessig
    vorhanden und immerhin ein grober Anhaltspunkt.
    """
    known = matches_known_at(timeline, cutoff, inclusive=inclusive)

    cutoff_text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)
    cutoff_ordinal = _to_ordinal(cutoff_text[:10])
    if cutoff_ordinal is None:
        return {"matches": 0, "away_matches": 0}

    lower_bound = cutoff_ordinal - days
    total = away = 0

    for match in known:
        played = _to_ordinal(match_date(match))
        if played is None or played < lower_bound:
            continue
        total += 1
        if not match.get("is_home", False):
            away += 1

    return {"matches": total, "away_matches": away}


def congestion_features(competition_matches, team_id, cutoff,
                        windows=DEFAULT_WINDOWS, inclusive=False):
    """
    Alle Belastungsmerkmale eines Teams zu einem Zeitpunkt.

    Das ist die vorgesehene Schnittstelle fuer spaetere Trainingsdaten.
    Rueckgabe bewusst flach und JSON-tauglich, damit sie sich unveraendert
    in einen Datensatz schreiben laesst.

    coverage sagt, welche Wettbewerbe ueberhaupt in die Rechnung
    eingegangen sind. Das ist keine Nebensache: Fehlen die nationalen
    Pokale (siehe Modulbeschreibung), sind alle Zahlen hier
    systematisch zu niedrig, und zwar genau in den Wochen, in denen
    Belastung am ehesten eine Rolle spielt.
    """
    timeline = build_team_timeline(competition_matches, team_id)
    known = matches_known_at(timeline, cutoff, inclusive=inclusive)

    features = {
        "team_id": team_id,
        "cutoff": str(cutoff),
        "days_since_last_match": days_since_last_match(
            timeline, cutoff, inclusive=inclusive),
        "matches_known": len(known),
    }

    for window in windows:
        features[f"matches_last_{window}_days"] = matches_in_last_days(
            timeline, cutoff, window, inclusive=inclusive)

    shortest = min(windows) if windows else 7
    features["competitions_last_%d_days" % shortest] = competitions_in_last_days(
        timeline, cutoff, shortest, inclusive=inclusive)
    features["travel_last_%d_days" % shortest] = travel_load_in_last_days(
        timeline, cutoff, shortest, inclusive=inclusive)

    features["coverage"] = coverage(competition_matches)

    return features


def coverage(competition_matches):
    """
    Woraus die Zeitleiste besteht - und was ihr fehlt.

    Ohne diese Angabe waere aus einem Merkmalssatz nicht erkennbar, ob
    "zwei Spiele in sieben Tagen" die volle Wahrheit ist oder nur der
    Teil, den unsere Datenlage hergibt.
    """
    present = sorted((competition_matches or {}).keys())

    # Wettbewerbe, die Belastung erzeugen, aber im aktuellen Tarif nicht
    # abrufbar sind. Bewusst hier benannt statt stillschweigend
    # weggelassen.
    known_gaps = ["national cups (DFB, FAC, CDR, CDF: HTTP 403)",
                  "UEFA Europa League", "UEFA Conference League"]

    return {
        "competitions": present,
        "competition_count": len(present),
        "known_gaps": known_gaps,
        "complete": False,
    }


def build_timeline_from_history(seasons, team_id, competitions=None):
    """
    Baut eine Zeitleiste direkt aus den gespeicherten Historiedateien.

    seasons:      Liste von Saisonjahren, z. B. [2024, 2025]
    competitions: API-Codes; Standard sind die fuenf Ligen plus CL

    Bequemlichkeitsfunktion fuer Backtests: Sie nimmt dem Aufrufer ab,
    die Dateien einzeln zu laden und zusammenzufuehren. Fehlende Dateien
    werden uebersprungen, nicht ergaenzt.
    """
    from src.data.historical_loader import LEAGUE_CODES, CUP_CODES, load_season

    if competitions is None:
        competitions = list(LEAGUE_CODES.values()) + list(CUP_CODES.values())

    by_competition = {}

    for api_code in competitions:
        collected = []
        for season in seasons:
            payload = load_season(api_code, season)
            if not payload:
                continue
            collected.extend(payload.get("matches") or [])
        if collected:
            by_competition[api_code] = collected

    return build_team_timeline(by_competition, team_id), by_competition
