"""
Zentrale Beschaffung der Teamstaerken.

Dieses Modul beantwortet genau eine Frage:
"Wie stark ist Team X in Liga Y zum jetzigen Zeitpunkt - und woher weiss
ich das?"

Es fuehrt zusammen, was die anderen Module liefern:

    historical_loader  -> Rohdaten abgeschlossener Saisons
    team_profile       -> Attack/Defence-Ratings daraus
    dynamic_weights    -> Mischung Historie / laufende Saison

Fallback-Kaskade
----------------
Fuer jedes Team wird der erste Treffer dieser Reihenfolge genommen. Die
erreichte Stufe wird als fallback_level mitgefuehrt, damit im Debug
sichtbar ist, wie belastbar der Wert ist:

    Stufe 0  Team-ID in der Historie gefunden          (bester Fall)
    Stufe 1  ueber normalisierten Namen / Alias gefunden
    Stufe 2  keine Historie, aber Spiele der laufenden Saison
    Stufe 3  Aufsteiger: empirisches Aufsteigerprofil der Liga
    Stufe 4  Liga-Neutralwert                          (letzter Ausweg)

Empirisches Aufsteigerprofil
----------------------------
Aufsteiger bekommen NICHT einfach den Ligadurchschnitt. Aus zwei
aufeinanderfolgenden Saisons laesst sich messen, wie Aufsteiger
tatsaechlich abschneiden: Wer in Saison N in der Liga spielte, aber in
Saison N-1 nicht, war ein Aufsteiger. Der Mittelwert genau dieser Teams
ist der Erwartungswert fuer kuenftige Aufsteiger.

Damit ist der Aufsteigerwert aus echten Daten abgeleitet und nicht
geraten. Fehlen die Daten fuer diese Rechnung, wird auf einen
konservativen Abschlag zurueckgegriffen, der als solcher markiert wird.
"""

import unicodedata
from collections import defaultdict

from src.data.historical_loader import (
    LEAGUE_CODES,
    AVAILABLE_HISTORICAL_SEASONS,
    load_available_seasons,
)
from src.api.league_api import get_all_matches, ApiUnavailable
from src.features.team_profile import (
    build_season_profiles,
    blend_profiles,
    league_averages,
    neutral_profile,
    collect_team_stats,
    NEUTRAL_RATING,
)
from src.features.dynamic_weights import blend_profile, confidence_level
from src.utils.team_aliases import TEAM_ALIASES
from src.features.model_constants import (
    domestic_league_avg_fallback,
    cl_league_avg_fallback,
)


# Wenn kein empirisches Aufsteigerprofil berechnet werden kann, gilt
# dieser Abschlag. Aufsteiger sind im Mittel schwaecher als der Rest der
# Liga - der Wert ist bewusst massvoll, damit sie nicht vorverurteilt
# werden. Wird nur bei fehlender Datengrundlage benutzt.
# Ab wie vielen Spielen der Ligaschnitt der LAUFENDEN Saison den
# historischen ersetzt. Technische Stichprobenschwelle, keine
# fussballerische Annahme.
CURRENT_LEAGUE_AVG_MIN_MATCHES = 20

FALLBACK_PROMOTED_ATTACK = 0.88
FALLBACK_PROMOTED_DEFENCE = 1.14

# Ab dieser Anzahl beobachteter Aufsteiger gilt der empirische Mittelwert
# als voll belastbar. Darunter wird er anteilig Richtung Schaetzwert
# gezogen (siehe compute_promoted_profile). Drei entspricht der ueblichen
# Zahl von Aufsteigern pro Saison in den Top-Ligen.
PROMOTED_SAMPLE_TARGET = 3


def normalize_name(name):
    """
    Vereinheitlicht einen Teamnamen fuer den Vergleich.

    'FC Bayern München' -> 'bayern munchen'
    'Bayern'            -> 'bayern'

    Entfernt Akzente, Rechtsformen und Satzzeichen. Dient nur als
    Notbehelf, wenn keine Team-ID vorliegt. Die ID ist immer besser.
    """
    if not name:
        return ""

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()

    for token in (" fc", "fc ", " cf", "cf ", " sc", "sc ", " ac", "ac ",
                  " bv", " sv", "sv ", " vfb", " vfl", " tsg", " rb ",
                  " 1. ", " calcio", " ssc", " as ", " ss ", " ogc",
                  " afc", " ufc", " club", " cd ", " rcd", " ca "):
        text = text.replace(token, " ")

    for ch in ".,-_'`&()/":
        text = text.replace(ch, " ")

    return " ".join(text.split())


def _build_name_index(profiles):
    """Baut einen Suchindex normalisierter Namen auf Team-Profile."""
    index = {}
    for team_id, profile in profiles.items():
        for candidate in (profile.get("team_name"), profile.get("short_name")):
            key = normalize_name(candidate)
            if key and key not in index:
                index[key] = team_id
    return index


def _alias_candidates(team_name):
    """Alle Schreibweisen, unter denen ein Team bekannt sein koennte."""
    candidates = {team_name}

    mapped = TEAM_ALIASES.get(team_name)
    if mapped:
        candidates.add(mapped)

    # Auch die Rueckrichtung: steht der Name als Wert im Alias-Dict,
    # sind alle zugehoerigen Schluessel ebenfalls gueltige Schreibweisen.
    for key, value in TEAM_ALIASES.items():
        if value == team_name:
            candidates.add(key)

    return {c for c in candidates if c}


def compute_promoted_profile(season_profile_list):
    """
    Misst empirisch, wie Aufsteiger in dieser Liga abschneiden.

    season_profile_list: Saisonprofile, NEUESTE ZUERST.
    Benoetigt mindestens zwei Saisons: Teams, die in der neueren Saison
    vorkommen, in der aelteren aber nicht, waren Aufsteiger. Ihr
    Durchschnitt ist der Erwartungswert.

    Rueckgabe: (profil_dict, quelle) - quelle ist 'empirisch' oder
    'geschaetzt', damit der Ursprung nachvollziehbar bleibt.
    """
    if len(season_profile_list) < 2:
        return _estimated_promoted_profile(), "geschaetzt"

    newer = season_profile_list[0]["profiles"]
    older = season_profile_list[1]["profiles"]

    promoted_ids = [tid for tid in newer if tid not in older]

    if not promoted_ids:
        return _estimated_promoted_profile(), "geschaetzt"

    keys = ("attack_home", "attack_away", "defence_home", "defence_away",
            "points_per_game", "goals_for_per_game", "goals_against_per_game",
            "win_rate")

    profile = {
        "team_id": None,
        "team_name": "Aufsteiger (Ligamittel)",
        "short_name": None,
        "crest": None,
        "seasons_used": [season_profile_list[0].get("season")],
        "seasons_count": 1,
        "matches_used": sum(newer[tid]["matches_used"] for tid in promoted_ids),
        "sample_teams": len(promoted_ids),
    }

    for key in keys:
        profile[key] = sum(newer[tid][key] for tid in promoted_ids) / len(promoted_ids)

    # Kleine Stichprobe absichern.
    # Typisch steigen 2-3 Teams pro Saison auf. Liegt nur ein einzelnes
    # Team vor, ist dessen Saison zu einem grossen Teil Zufall - ein
    # ueberraschend starker Aufsteiger wuerde sonst zum Massstab fuer alle
    # kuenftigen. Deshalb dieselbe Shrinkage wie bei den Team-Ratings:
    # Richtung konservativer Schaetzung ziehen, gewichtet nach Stichprobe.
    sample = len(promoted_ids)
    if sample < PROMOTED_SAMPLE_TARGET:
        estimated = _estimated_promoted_profile()
        w_empirical = sample / PROMOTED_SAMPLE_TARGET
        for key in keys:
            profile[key] = (
                w_empirical * profile[key]
                + (1.0 - w_empirical) * estimated[key]
            )
        profile["shrunk_to_estimate"] = round(1.0 - w_empirical, 2)

    return profile, "empirisch"


def _estimated_promoted_profile():
    """Konservative Schaetzung, wenn keine empirische Basis vorliegt."""
    profile = neutral_profile(None, "Aufsteiger (geschaetzt)")
    profile["attack_home"] = FALLBACK_PROMOTED_ATTACK
    profile["attack_away"] = FALLBACK_PROMOTED_ATTACK
    profile["defence_home"] = FALLBACK_PROMOTED_DEFENCE
    profile["defence_away"] = FALLBACK_PROMOTED_DEFENCE
    profile["points_per_game"] = 1.10
    profile["win_rate"] = 0.26
    profile["sample_teams"] = 0
    return profile


def build_current_season_profiles(finished_matches, teams_lookup=None):
    """
    Baut Profile aus den bereits gespielten Partien der LAUFENDEN Saison.

    finished_matches: Liste im Format des historical_loader
                      (home_id, away_id, home_goals, away_goals)
    Gibt None zurueck, wenn noch nichts gespielt wurde - dann traegt
    ausschliesslich die Historie.
    """
    if not finished_matches:
        return None

    payload = {
        "meta": {"season": "current", "api_code": None},
        "teams": teams_lookup or {},
        "matches": finished_matches,
    }
    return build_season_profiles(payload)


def _build_provenance(competition, season, matches, source, sample_size=None,
                      extra=None):
    """
    Nachvollziehbarkeitsangaben zu einer Staerkeberechnung.

    computed_at         wann gerechnet wurde
    matches_through_date  juengstes tatsaechlich beruecksichtigtes Spiel
    season/competition  fachlicher Kontext
    source              woher die Rohdaten stammen
    sample_size         wie viele Spiele eingeflossen sind

    matches_through_date ist der wichtigste Eintrag: Er zeigt, worauf die
    Berechnung TATSAECHLICH beruhte. Liegt er weit vor dem Rechenzeitpunkt,
    ist das ein Hinweis auf eine Datenluecke - und beim spaeteren Training
    der Beleg dafuer, dass kein zukuenftiges Spiel eingeflossen ist.
    """
    from datetime import datetime, timezone
    from src.features.point_in_time import match_date

    through = None
    if matches:
        dates = [match_date(m) for m in matches]
        dates = [d for d in dates if d]
        through = max(dates) if dates else None

    info = {
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matches_through_date": through,
        "season": season,
        "competition": competition,
        "source": source,
        "sample_size": sample_size,
    }
    if extra:
        info.update(extra)

    return info


def get_league_strengths(
    league_key,
    standings_table,
    current_matches=None,
    seasons=None,
    use_squad_data=True,
    current_season=None,
    cutoff=None,
):
    """
    Liefert fuer jedes Team der Tabelle ein einsatzbereites Profil.

    league_key:      'bl1', 'pl', ...
    standings_table: aktuelle Tabelle (mit team_id, team_name, played)
    current_matches: bereits gespielte Partien der laufenden Saison
                     (optional; ohne sie zaehlt nur die Historie)
    current_season:  Jahr der laufenden Saison (z. B. 2026). Wird fuer
                     die Aufsteiger-Erkennung gebraucht: Aufsteiger ist,
                     wer JETZT in der Liga spielt, aber in der
                     unmittelbaren Vorsaison (current_season - 1) nicht.
                     Wird ausserdem an die Kaderwirkung weitergereicht,
                     damit dort dieselbe Saison gilt wie hier.
    cutoff:          Stichtag fuer historische Berechnungen. Ohne Angabe
                     (Standard) rechnet der normale Live-Pfad wie bisher.
                     Mit Stichtag filtert die Historie sich selbst und
                     die Kaderwirkung kommt ausschliesslich aus dem
                     Snapshot-Archiv - siehe unten.

    Rueckgabe:
    {
      "profiles":   { team_id: profil },
      "league_avg": {...},
      "coverage":   [ {team_name, fallback_level, data_source, ...} ],
      "summary":    {...}
    }
    """
    api_code = LEAGUE_CODES.get(league_key, league_key.upper())
    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS

    # Auch die laufende Saison am Stichtag abschneiden. Sonst zeigte die
    # Provenienz ein matches_through_date NACH dem Stichtag - und die
    # Formkomponente rechnete mit Spielen, die damals nicht bekannt waren.
    if cutoff is not None and current_matches:
        from src.features.point_in_time import matches_known_at
        current_matches = matches_known_at(current_matches, cutoff)

    # 1. Historie laden und zu einem Gesamtprofil verschmelzen.
    loaded = load_available_seasons(api_code, seasons)
    season_profiles = [build_season_profiles(payload, cutoff=cutoff)
                       for _, payload in loaded]
    historical = blend_profiles(season_profiles) if season_profiles else {}

    # Aufsteiger-Erkennung: NUR ueber die Teilnehmerliste der unmittelbaren
    # Vorsaison. "Keine Historie gefunden" ist ausdruecklich KEIN Beleg
    # fuer einen Aufstieg - das kann genauso ein Datenluecken- oder
    # Mapping-Problem sein. Liegt die Vorsaison lokal nicht vor, bleibt
    # der Status unbekannt (None) statt geraten.
    previous_season_team_ids = None
    previous_season_year = None
    if current_season is not None:
        previous_season_year = current_season - 1
        for loaded_season, payload in loaded:
            if loaded_season == previous_season_year:
                previous_season_team_ids = {
                    int(tid) for tid in (payload.get("teams") or {})
                }
                break

    # Ligadurchschnitt: bevorzugt aus der neuesten Historie-Saison.
    if season_profiles:
        league_avg = dict(season_profiles[0]["league_avg"])
    else:
        league_avg = domestic_league_avg_fallback()

    name_index = _build_name_index(historical)
    promoted_profile, promoted_source = compute_promoted_profile(season_profiles)

    # 2. Profile der laufenden Saison, falls schon gespielt wurde.
    current_data = build_current_season_profiles(current_matches)
    current_profiles = current_data["profiles"] if current_data else {}

    # Ligadurchschnitt der laufenden Saison nutzen, sobald er belastbar ist.
    if (current_data and current_data["league_avg"]["matches"]
            >= CURRENT_LEAGUE_AVG_MIN_MATCHES):
        league_avg = dict(current_data["league_avg"])

    profiles = {}
    coverage = []

    for row in standings_table:
        team_id = row.get("team_id")
        team_name = row.get("team_name") or ""
        played = row.get("played") or 0

        hist_profile = None
        fallback_level = 0
        data_source = "history_id"
        alias_used = None

        # --- Stufe 0: Treffer ueber Team-ID ---
        if team_id is not None and team_id in historical:
            hist_profile = historical[team_id]

        # --- Stufe 1: Treffer ueber normalisierten Namen / Alias ---
        if hist_profile is None:
            for candidate in _alias_candidates(team_name):
                key = normalize_name(candidate)
                match_id = name_index.get(key)
                if match_id is not None:
                    hist_profile = historical[match_id]
                    fallback_level = 1
                    data_source = "history_name"
                    alias_used = candidate
                    break

        has_historical_data = hist_profile is not None

        # Aufsteiger-Status: STRIKT getrennt von der Datenverfuegbarkeit.
        #   True   Team fehlt in der Teilnehmerliste der Vorsaison
        #   False  Team war in der Vorsaison dabei
        #   None   Vorsaison-Daten liegen nicht vor -> Status unbekannt
        # Ein Team KANN Aufsteiger sein und trotzdem aeltere
        # Erstliga-Historie besitzen (Wiederaufsteiger) - beides gilt.
        if previous_season_team_ids is not None and team_id is not None:
            is_promoted = team_id not in previous_season_team_ids
        else:
            is_promoted = None

        # --- Stufe 2: keine Historie, aber laufende Saison ---
        if hist_profile is None and team_id in current_profiles:
            fallback_level = 2
            data_source = "current_season_only"

        # --- Stufe 3: bestaetigter Aufsteiger ohne eigene Historie ---
        # Das empirische Aufsteigerprofil greift nur, wenn der Aufstieg
        # ueber die Vorsaison-Teilnehmerliste BELEGT ist. "Historie fehlt"
        # allein reicht nicht - dann waere jedes Datenloch ein Aufsteiger.
        if (hist_profile is None and team_id not in current_profiles
                and is_promoted is True):
            hist_profile = dict(promoted_profile)
            hist_profile["team_id"] = team_id
            hist_profile["team_name"] = team_name
            fallback_level = 3
            data_source = (
                "promoted_empirical" if promoted_source == "empirisch"
                else "promoted_estimated"
            )

        # --- Stufe 4: keine Daten, Aufstieg nicht belegbar -> Neutralwert ---
        if hist_profile is None and team_id not in current_profiles:
            hist_profile = neutral_profile(team_id, team_name)
            fallback_level = 4
            data_source = "league_neutral"

        # 3. Historie und laufende Saison nach Spielzahl mischen.
        curr_profile = current_profiles.get(team_id)
        merged = blend_profile(hist_profile, curr_profile, played)

        # Garantie der Fallback-Kette: Der letzte Schritt ist niemals None.
        if merged is None:
            merged = neutral_profile(team_id, team_name)
            fallback_level = 4
            data_source = "league_neutral"

        # Stammdaten aus der Tabelle haben Vorrang: sie sind aktuell.
        merged["team_id"] = team_id
        merged["team_name"] = team_name
        if row.get("crest"):
            merged["crest"] = row["crest"]

        confidence = confidence_level(
            matches_played=played,
            has_history=has_historical_data,
            fallback_level=fallback_level,
        )

        merged["data_source"] = data_source
        merged["fallback_level"] = fallback_level
        merged["alias_used"] = alias_used
        merged["confidence"] = confidence["score"]
        merged["confidence_level"] = confidence["level"]
        merged["season_data_available"] = bool(curr_profile)
        merged["is_promoted"] = is_promoted
        merged["has_historical_data"] = has_historical_data

        profiles[team_id] = merged

        coverage.append({
            "team_id": team_id,
            "team_name": team_name,
            "data_source": data_source,
            "fallback_level": fallback_level,
            "alias_used": alias_used,
            "matched_by_alias": alias_used is not None,
            "is_promoted": is_promoted,
            "has_historical_data": has_historical_data,
            "season_data_available": bool(curr_profile),
            "historical_seasons": merged.get("seasons_count", 0),
            "matches_used": merged.get("matches_used", 0),
            "current_matches_played": played,
            "confidence": confidence["score"],
            "confidence_level": confidence["level"],
        })

    # 4. Kaderwirkung aus API-Sports, falls verfuegbar.
    # Bewusst als letzter Schritt und streng optional: Faellt die Quelle
    # aus, bleibt alles andere unveraendert nutzbar.
    squad_applied = False
    if use_squad_data:
        # Der Import steht BEWUSST ausserhalb des try. Ein Import- oder
        # Namensfehler ist ein Programmierfehler, kein fehlendes Datum:
        # Genau so blieb dieses Feature unbemerkt wirkungslos, weil ein
        # ImportError (fehlende TTL-Konstante) hier als "keine Kaderdaten"
        # durchging. Datenfehler werden weiter unten weiterhin toleriert.
        from src.features.squad_impact import get_squad_impact, apply_impact

        try:
            # Saison AUSDRUECKLICH weitergeben. Frueher stand hier
            # get_squad_impact(league_key) - ohne Saison. Die Funktion
            # griff dann auf einen festen Modulwert zurueck, sodass eine
            # Simulation fuer 2026/27 die Ausfaelle und Torschuetzen der
            # Saison 2025/26 verwendete. Beide Anbieter zaehlen die
            # Saison nach dem Startjahr, der Wert passt also unveraendert.
            #
            # cutoff wird als as_of durchgereicht: bei einer historischen
            # Berechnung darf nur ein archivierter Kaderstand von damals
            # einfliessen, niemals ein Live-Abruf von heute.
            impact = get_squad_impact(
                league_key,
                season=current_season,
                as_of=cutoff,
            )
            if impact:
                apply_impact(profiles, impact)
                squad_applied = True

                # Coverage nachtragen, damit der Einfluss sichtbar ist.
                for entry in coverage:
                    team_impact = impact.get(entry["team_id"])
                    entry["squad_modifier"] = (
                        team_impact.get("attack_modifier", 1.0) if team_impact else 1.0
                    )
                    entry["missing_players"] = (
                        team_impact.get("missing_players", []) if team_impact else []
                    )
        except Exception:
            # Kaderdaten sind eine Zugabe, kein Muss.
            squad_applied = False

    summary = _coverage_summary(coverage, len(loaded), promoted_source)
    summary["squad_data_applied"] = squad_applied
    summary["previous_season_available"] = previous_season_team_ids is not None
    summary["previous_season_year"] = previous_season_year
    summary["historical_season_years"] = [s for s, _ in loaded]

    # Nachvollziehbarkeit: Woraus ist dieses Ergebnis entstanden? Ohne
    # diese Angaben laesst sich spaeter nicht pruefen, ob ein Feature nur
    # Daten benutzt hat, die zu seinem Zeitpunkt bekannt waren.
    # Rechenlogik bleibt unberuehrt - das sind reine Zusatzangaben.
    summary["provenance"] = _build_provenance(
        competition=api_code,
        season=current_season,
        matches=current_matches,
        source="football-data.org+historical",
        sample_size=len(current_matches or []),
        extra={
            "historical_seasons_used": [s for s, _ in loaded],
            "squad_data_applied": squad_applied,
            "league_avg_matches": league_avg.get("matches", 0),
            # Ohne Stichtag None - dann ist es eine normale Live-Rechnung.
            "cutoff": cutoff.isoformat() if hasattr(cutoff, "isoformat") else cutoff,
            "squad_source": "snapshot" if cutoff is not None else "live",
        },
    )

    return {
        "profiles": profiles,
        "league_avg": league_avg,
        "coverage": coverage,
        "summary": summary,
    }


def _coverage_summary(coverage, historical_seasons_loaded, promoted_source):
    """Verdichtet die Coverage-Liste zu Kennzahlen fuer Frontend und Report."""
    total = len(coverage)
    if total == 0:
        return {
            "teams_total": 0, "teams_with_history": 0,
            "teams_without_history": 0, "teams_promoted": 0,
            "teams_promoted_unknown": 0,
            "teams_neutral": 0, "historical_seasons": historical_seasons_loaded,
            "avg_confidence": 0.0, "reliable": False,
            "promoted_source": promoted_source,
        }

    with_history = sum(1 for c in coverage if c.get("has_historical_data"))
    # Echte Aufsteiger: nur ueber die Vorsaison-Teilnehmerliste belegt.
    # Teams ohne Historie sind ein getrenntes Merkmal (Datenluecke),
    # sonst wuerden vier oder fuenf "Aufsteiger" angezeigt, wo real drei sind.
    promoted = sum(1 for c in coverage if c.get("is_promoted") is True)
    promoted_unknown = sum(1 for c in coverage if c.get("is_promoted") is None)
    without_history = total - with_history
    neutral = sum(1 for c in coverage if c["fallback_level"] >= 4)
    avg_conf = sum(c["confidence"] for c in coverage) / total

    return {
        "teams_total": total,
        "teams_with_history": with_history,
        "teams_without_history": without_history,
        "teams_promoted": promoted,
        "teams_promoted_unknown": promoted_unknown,
        "teams_neutral": neutral,
        "history_ratio": round(with_history / total, 2),
        "historical_seasons": historical_seasons_loaded,
        "avg_confidence": round(avg_conf, 2),
        # Belastbar, wenn kein Team im Notfall-Modus liegt und die
        # allermeisten Teams echte Historie haben.
        "reliable": (neutral == 0 and with_history / total >= 0.8),
        "promoted_source": promoted_source,
    }


# =============================================================================
# CHAMPIONS LEAGUE: eigene Fallback-Kette (Block B1)
# =============================================================================
#
# Warum eine eigene Funktion statt get_league_strengths("cl", ...)?
# -------------------------------------------------------------------------
# get_league_strengths sucht Team-Historie INNERHALB einer einzigen Liga
# (LEAGUE_CODES[league_key] -> genau eine api_code -> genau eine Serie
# historischer Saisondateien) und kennt eine Aufsteiger-Stufe. Beides
# passt nicht zur Champions League:
#
#   - CL-Teilnehmer kommen aus bis zu 36 verschiedenen nationalen Ligen,
#     nicht nur aus den fuenf von FootSim simulierten. Ein Team wie
#     Bodoe/Glimt hat schlicht keine "CL-Liga-Historie" - es muss ueber
#     seine Team-ID in JEDER der fuenf Top-Ligen gesucht werden koennen
#     (findet nichts, faellt also weiter), UND es braucht einen Fallback,
#     der nicht "Ligadurchschnitt" heisst, sondern auf echten
#     CL-Ergebnissen basiert.
#   - Es gibt keine Auf-/Abstiegsbeziehung zwischen CL und den Top-5-Ligen.
#     Die Aufsteiger-Stufe (compute_promoted_profile) ergibt hier keinen
#     fachlichen Sinn und wird deshalb nicht verwendet.
#
# Fallback-Kette:
#   Stufe 0  Team-ID in der geblendeten Historie EINER der fuenf
#            Top-Ligen (deckt die meisten CL-Teilnehmer ab: Bayern,
#            PSG, Real Madrid, Arsenal, ...)
#   Stufe 1  keine Top-5-Liga-Historie, aber echte CL-Ergebnisse dieser
#            Saison vorhanden (Bodoe/Glimt, Galatasaray, Qarabag, ...) -
#            berechnet aus WIRKLICH GESPIELTEN CL-Partien, nicht geraten
#   Stufe 2  neutral_profile - letzter Ausweg, nur wenn ein Team in
#            keiner der beiden Quellen auftaucht (z. B. ganz zu
#            Saisonbeginn, bevor ein einziges CL-Spiel stattfand)
#
# Die eigentliche Auswahl zwischen diesen drei Stufen (pro Team, mit dem
# Wissen um home_id/away_id einer konkreten Partie) uebernimmt
# src.predict.cl_match_sim._resolve_cl_profile - analog dazu, wie
# league_match_sim._resolve_profile die Ausgabe von get_league_strengths
# konsumiert.

def get_cl_team_strengths(season, cutoff, repository=None):
    """
    Baut die Datengrundlage fuer die Champions-League-Teamstaerke.

    Liefert KEINE fertigen Profile pro Team (anders als
    get_league_strengths), sondern die beiden Quellen, aus denen die
    Fallback-Kette pro Partie waehlt. Das genuegt fuer die
    Einzelspielsimulation und vermeidet, fuer jeden Request alle 36
    CL-Teilnehmer vorab aufzuloesen, wenn nur zwei davon gebraucht werden.

    cutoff ist PFLICHT (V2-C1). Bis dahin stand hier
    _blend_top5_league_history_by_id() - ohne Stichtag und ohne
    Saisonobergrenze. Ein Profil fuer die Saison 2024 war dadurch
    identisch mit dem fuer 2025: beide enthielten alle drei lokal
    vorliegenden Saisons. Das Modell wurde auf stichtagsgenauen Profilen
    trainiert und gemessen, bekam im Betrieb aber einen anderen
    Informationsstand.

    Seit V2-C1 kommt die Rechnung aus src/features/pit_profiles.py -
    derselben Fabrik, die auch den Trainingsdatensatz baut. Fuer ein
    aktuelles Spiel liefert runtime_cutoff() den Stichtag; er wird am
    RAND bestimmt und hereingereicht, nie hier drinnen geraten.

    Rueckgabe:
    {
      "domestic_by_id":  { team_id: profil },  # Stufe 0
      "cl_current_by_id": { team_id: profil },  # Stufe 1
      "league_avg": {...},  # aus echten CL-Partien bis zum Stichtag,
                             # sonst ein grober Schaetzwert
    }

    Der Schluessel cl_current_by_id behaelt seinen Namen: Er steht im
    API-Vertrag und wird im Browser gelesen (static/script.js, Vergleich
    auf die Herkunft "cl_current_season"). Sein INHALT ist seit V2-C1
    die gepoolte CL-Historie bis zum Stichtag statt nur der laufenden
    Saison - fachlich dasselbe, was der Datensatz unter cl_history_pit
    fuehrt. Die Umbenennung waere eine sichtbare Vertragsaenderung und
    gehoert nicht in diesen Block.
    """
    from src.features.pit_profiles import (
        PitProfileRepository, cl_profile_sources, require_cutoff)

    cutoff = require_cutoff(cutoff)
    repository = repository or PitProfileRepository()

    # QUELLENKASKADE FUER DIE CL-SPIELE
    #
    # 1. Lokale, validierte Historie (data/historical/CL_<saison>.json).
    #    Abgeschlossene Saisons aendern sich nie mehr; sie live zu holen
    #    kostete Anbieterrequests und machte die CL-Staerke von der
    #    Erreichbarkeit des Anbieters abhaengig.
    # 2. Live-Abruf, wenn lokal nichts liegt (laufende Saison, Luecke).
    # 3. Leer - dann greift Stufe 2 der Profilkaskade (neutral_profile).
    #
    # Eine leere Anbieterantwort ersetzt NIE eine vorhandene lokale
    # Historie: geladen wird nur, was auch etwas enthaelt.
    #
    # V2-C1: Gelesen wird die lokale Datei ueber die Fabrik. Vorher gab
    # es hier einen ZWEITEN load_cl_season-Aufruf neben dem der Fabrik -
    # zwei Leser derselben Datei, die auseinanderlaufen koennen.
    cl_matches = []
    cl_source = "none"
    cl_source_detail = None

    # Die Saison ist die OBERGRENZE der Fabrik (keine spaetere Saison),
    # der Stichtag die Grenze innerhalb davon. Beides wird gebraucht:
    # Die Saison allein liesse den Rest der laufenden Saison durch, der
    # Stichtag allein die kompletten Folgesaisons.
    aufgeloeste_saison = season
    try:
        import os as _os
        from src.data.historical_loader import season_file_path
        from src.api.league_api import get_current_season

        aufgeloest = season if season is not None else get_current_season("CL")
        aufgeloeste_saison = aufgeloest
        payload = repository.cl_payload(aufgeloest)
        lokal = (payload or {}).get("matches") or []

        if lokal:
            # Fuer die Herkunftsangabe unten. Als extra_cl_matches geht
            # sie NICHT hinein - die Fabrik liest dieselbe Datei selbst
            # und wuerde die Partien sonst doppelt zaehlen.
            cl_matches = lokal
            cl_source = "local_history"
            cl_source_detail = {
                "file": _os.path.basename(season_file_path("CL", aufgeloest)),
                "fetched_at": (payload.get("meta") or {}).get("fetched_at"),
                "stages": (payload.get("meta") or {}).get("stages"),
            }
    except Exception:
        # Eine unlesbare oder fehlende Datei ist kein Fehler, sondern
        # bedeutet schlicht: live nachladen.
        lokal = []

    if not lokal:
        try:
            cl_matches = get_all_matches("CL", season=season, only_finished=True)
            if cl_matches:
                cl_source = "live_api"
                cl_source_detail = {"provider": "football-data.org"}
        except ApiUnavailable:
            # Keine Daten erreichbar (z. B. Saison noch nicht begonnen oder
            # API kurzzeitig nicht verfuegbar) - Stufe 1 bleibt dann leer,
            # betroffene Teams fallen auf Stufe 2 (neutral_profile) zurueck.
            cl_matches = []

    # Die eine Filterstelle. Die lokale Historie liest die Fabrik selbst;
    # was hier oben live geholt wurde, geht als extra_cl_matches hinein
    # und durchlaeuft DENSELBEN Stichtagsfilter. Ohne das waere die
    # Live-Quelle der letzte Weg, auf dem Zukunftsdaten hereinkaemen.
    quellen = cl_profile_sources(
        season=aufgeloeste_saison,
        cutoff=cutoff,
        repository=repository,
        extra_cl_matches=cl_matches if cl_source == "live_api" else None)

    domestic_by_id = quellen["domestic_by_id"]
    cl_current_by_id = quellen["cl_history_by_id"]
    league_avg = quellen["league_avg"]

    if not league_avg:
        # Grober Schaetzwert, nur bis die ersten echten CL-Ergebnisse der
        # Saison vorliegen. Die Champions League hat historisch ein etwas
        # offeneres Torniveau als der Schnitt der Top-5-Ligen.
        league_avg = cl_league_avg_fallback()

    return {
        "domestic_by_id": domestic_by_id,
        "cl_current_by_id": cl_current_by_id,
        "league_avg": league_avg,
        "provenance": _build_provenance(
            competition="CL",
            season=season,
            # Was TATSAECHLICH benutzt wurde - nicht der Rohbestand der
            # Datei. Vorher meldete matches_through_date das Saisonende,
            # obwohl zum Stichtag nur ein Teil bekannt war.
            matches=quellen["cl_matches_used"],
            # Woher die Spiele wirklich kamen - lokale Historie oder Live.
            source=("local:data/historical" if cl_source == "local_history"
                    else "football-data.org"),
            sample_size=quellen["cl_matches_known"],
            extra={
                "cl_source": cl_source,
                "cl_source_detail": cl_source_detail,
                "domestic_profiles": len(domestic_by_id),
                "cl_profiles": len(cl_current_by_id),
                "league_avg_from_real_matches": bool(league_avg.get("matches")),
                # V2-C1: Womit wurde gerechnet? Ohne diese Angabe laesst
                # sich spaeter nicht mehr feststellen, welchen
                # Kenntnisstand ein Ergebnis hatte.
                "pit_cutoff": cutoff,
                "pit_season_ceiling": aufgeloeste_saison,
                "cl_matches_known_at_cutoff": quellen["cl_matches_known"],
                "cutoff_inclusive": False,
            },
        ),
    }
