"""
Spielbezogene Aktualisierung statt taeglichem Vollrefresh.

DAS PROBLEM
-----------
FootSim holte Spielerprofile mit einer festen Lebensdauer von 24 Stunden.
Das hat zwei gegenlaeufige Folgen, und beide traten am 24.08.2026 auf:

    Zu langsam   Nach einem Spiel dauert es bis zu einen Tag, bis die
                 neuen Minuten ankommen.
    Zu teuer     Wer nicht warten will, laedt eine ganze Liga neu -
                 rund 450 Abrufe fuer eine Handvoll veraenderter Werte.

Ein taeglicher Vollrefresh aller fuenf Ligen kostet rund 2.250 Abrufe.
Das Tageslimit liegt bei 7.500. Es geht, aber es ist Verschwendung: An
einem normalen Spieltag aendern sich die Werte von vielleicht zwanzig
Mannschaften, nicht von hundert.

DER ANSATZ
----------
Erst fragen, wer ueberhaupt gespielt hat - dann nur diese Spieler holen.

    1 Abruf   /fixtures?date=YYYY-MM-DD liefert ALLE Spiele des Tages,
              nicht eines je Liga. Danach wird lokal auf die fuenf
              Ligen gefiltert.
    N Abrufe  ein Profil je Spieler der beteiligten Mannschaften.

Ein Spieltag mit zehn Partien betrifft zwanzig Mannschaften, also rund
500 Spieler. Ein Tag ohne Spiele kostet genau einen Abruf.

WAS HIER NICHT ENTSCHIEDEN WIRD
-------------------------------
Ob eine Minutenzahl stimmt. Der Fixture-Status sagt, ob ein Spiel vorbei
ist - nicht, ob der Anbieter es fertig verbucht hat. Bei Real Madrid war
die Partie seit 27 Stunden beendet, und der Anbieter lieferte weiterhin
38 Minuten. Dagegen hilft kein Zeitplan; dagegen hilft nur, den Stand
ehrlich als moeglicherweise vorlaeufig zu kennzeichnen.

Und: Diese Datei installiert nichts. Sie stellt eine idempotente,
wiederholbare Funktion bereit. Ein Timer auf dem Server wird in
ops/players-refresh.md beschrieben, nicht hier eingerichtet.
"""

from datetime import datetime, timedelta, timezone

from src.api.live_api import (
    ACTIVE_PHASES,
    PHASE_CANCELLED,
    PHASE_FINISHED,
    classify_status,
)
from src.data.competition_taxonomy import DOMESTIC_LEAGUE_IDS

#: Waehrend ein Spiel laeuft, ist jeder abgerufene Stand ein Zwischenstand.
#: Eine Viertelstunde ist kurz genug, um nicht lange falsch zu liegen, und
#: lang genug, um bei einem 90-Minuten-Spiel nicht sechsmal zu fragen.
TTL_DURING_MATCH = 15 * 60

#: Kurz nach Schlusspfiff verbucht der Anbieter nach. Zwei Stunden geben
#: ihm Zeit, ohne den Wert einen ganzen Tag festzuhalten.
TTL_AFTER_MATCH = 2 * 60 * 60

#: Wie lange "kurz nach Schlusspfiff" dauert.
NACHLAUF = timedelta(hours=6)

#: Ausserhalb jedes Spielfensters aendert sich nichts mehr. Das ist die
#: bisherige Lebensdauer und bleibt es.
TTL_IDLE = 24 * 60 * 60

#: Eine abgeschlossene Saison aendert sich nicht mehr nennenswert.
TTL_FINISHED_SEASON = 365 * 24 * 60 * 60

#: Phasen, in denen ein Spiel regulaer zu Ende ist. Andere Endzustaende
#: (abgebrochen, verschoben, abgesagt) zaehlen ausdruecklich NICHT dazu -
#: sie erzeugen keine verlaesslichen Endstaende.
FINAL_PHASES = frozenset({PHASE_FINISHED})

#: Phasen, in denen gerade gespielt wird oder das Spiel im Gange ist.
#: Uebernommen aus live_api, damit es keine zweite Liste gibt.
RUNNING_PHASES = frozenset(ACTIVE_PHASES)


def _utc_now():
    return datetime.now(timezone.utc)


def fixture_phase(fixture):
    """
    Die Phase eines Spiels, ueber die zentrale Statustabelle.

    Bewusst KEINE eigene Statusliste: live_api.STATUS_MAP kennt bereits
    alle Codes des Anbieters, samt der Unterscheidung zwischen "vorbei"
    und "findet nicht statt". Eine zweite Liste waere eine zweite Wahrheit
    und wuerde beim naechsten neuen Statuscode auseinanderlaufen.
    """
    status = ((fixture or {}).get("fixture") or {}).get("status") or {}
    phase, _ = classify_status(status.get("short"))
    return phase


def fixture_kickoff(fixture):
    """Anstosszeit eines Spiels als aware datetime, oder None."""
    roh = ((fixture or {}).get("fixture") or {}).get("date")
    if not roh:
        return None
    try:
        wert = datetime.fromisoformat(str(roh).replace("Z", "+00:00"))
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)


def fixture_team_ids(fixture):
    """Die beiden Mannschaften eines Spiels."""
    teams = (fixture or {}).get("teams") or {}
    ids = []
    for seite in ("home", "away"):
        tid = (teams.get(seite) or {}).get("id")
        if tid is not None:
            ids.append(int(tid))
    return ids


def relevant_fixtures(fixtures, league_ids=None):
    """
    Nur die Spiele der fuenf Vergleichsligen.

    /fixtures?date= liefert die Spiele der ganzen Welt. Die Filterung
    geschieht hier lokal und kostet keinen weiteren Abruf.
    """
    erlaubt = set(league_ids or DOMESTIC_LEAGUE_IDS.keys())
    treffer = []
    for spiel in fixtures or []:
        liga = (spiel or {}).get("league") or {}
        if liga.get("id") in erlaubt:
            treffer.append(spiel)
    return treffer


def profile_ttl(phase, season_finished=False, minutes_since_final=None):
    """
    Wie lange darf ein Spielerprofil als frisch gelten?

    Gestaffelt statt pauschal:

        Saison vorbei          ein Jahr    - aendert sich nicht mehr
        Spiel laeuft gerade    15 Minuten  - jeder Stand ist vorlaeufig
        kurz nach Schluss      2 Stunden   - der Anbieter verbucht nach
        sonst                  24 Stunden  - wie bisher

    Die kurze Lebensdauer waehrend eines Spiels ist der eigentliche
    Fortschritt: Ein Zwischenstand blieb frueher bis zu einen vollen Tag
    stehen, ohne dass irgendetwas ihn abgeloest haette.
    """
    if season_finished:
        return TTL_FINISHED_SEASON
    if phase in RUNNING_PHASES:
        return TTL_DURING_MATCH
    if phase in FINAL_PHASES and minutes_since_final is not None:
        if minutes_since_final <= NACHLAUF.total_seconds() / 60:
            return TTL_AFTER_MATCH
    return TTL_IDLE


def is_provisional(phase):
    """
    Ist ein waehrend dieser Phase geholter Stand als vorlaeufig zu fuehren?

    Waehrend eines laufenden Spiels: ja, immer. Ein abgebrochenes oder
    verschobenes Spiel ebenfalls - dort ist voellig offen, was der
    Anbieter spaeter verbucht.
    """
    return phase in RUNNING_PHASES or phase == PHASE_CANCELLED


def teams_to_refresh(fixtures, league_ids=None, now=None):
    """
    Welche Mannschaften brauchen nach diesen Spielen neue Spielerdaten?

    Rueckgabe: dict team_id -> Grund. Nur regulaer beendete Spiele
    zaehlen. Ein abgebrochenes Spiel erzeugt keinen verlaesslichen
    Endstand, ein verschobenes gar keinen - beide werden ausdruecklich
    nicht als "fertig" behandelt.
    """
    now = now or _utc_now()
    betroffen = {}

    for spiel in relevant_fixtures(fixtures, league_ids):
        phase = fixture_phase(spiel)
        if phase not in FINAL_PHASES:
            continue
        anstoss = fixture_kickoff(spiel)
        if anstoss and anstoss > now:
            # Ein als beendet gemeldetes Spiel in der Zukunft ist ein
            # Datenfehler des Anbieters, kein Anlass fuer 25 Abrufe.
            continue
        for tid in fixture_team_ids(spiel):
            betroffen.setdefault(tid, "Spiel regulaer beendet")

    return betroffen


def running_teams(fixtures, league_ids=None):
    """
    Mannschaften, deren Spiel gerade laeuft.

    Fuer sie gilt die kurze Lebensdauer, und ihre Werte werden als
    vorlaeufig gefuehrt. Sie werden NICHT aktiv nachgeladen - waehrend
    eines Spiels ist jeder Abruf sofort wieder veraltet.
    """
    laufend = {}
    for spiel in relevant_fixtures(fixtures, league_ids):
        if fixture_phase(spiel) in RUNNING_PHASES:
            for tid in fixture_team_ids(spiel):
                laufend[tid] = fixture_phase(spiel)
    return laufend


def plan_post_match_refresh(fixtures, season, league_ids=None, now=None,
                            squad_lookup=None):
    """
    Was waere zu tun - ohne irgendetwas zu tun.

    Der Plan trennt sauber, was gerechnet wurde, von dem, was ausgefuehrt
    wird. Er ist die Grundlage der Kostenanzeige: Wer 500 Abrufe ausloesen
    wuerde, soll das vorher sehen und nicht hinterher im Kontostand
    entdecken.

    squad_lookup(team_id, season) -> (ids, name). Ohne Angabe wird der
    gecachte Kaderindex gelesen; gebaut wird er NIE, das kostete rund
    hundert Abrufe.

    Rueckgabe: dict mit teams, player_ids, running_teams, requests_fixtures,
    requests_players, requests_total.
    """
    from src.data.player_refetch import team_player_ids

    squad_lookup = squad_lookup or team_player_ids

    betroffen = teams_to_refresh(fixtures, league_ids, now=now)
    laufend = running_teams(fixtures, league_ids)

    spieler = []
    ohne_kader = []
    for team_id in sorted(betroffen):
        ids, name = squad_lookup(team_id, season)
        if not ids:
            ohne_kader.append(team_id)
            continue
        for pid in ids:
            if pid not in spieler:
                spieler.append(pid)

    return {
        "season": season,
        "teams": sorted(betroffen),
        "team_reasons": betroffen,
        "teams_without_squad": ohne_kader,
        "running_teams": sorted(laufend),
        "player_ids": spieler,
        # Ein einziger Fixture-Abruf deckt alle Ligen eines Tages ab.
        "requests_fixtures": 1,
        "requests_players": len(spieler),
        "requests_total": 1 + len(spieler),
    }


def run_post_match_refresh(season, fixtures=None, fetch_fixtures=None,
                           date_str=None, league_ids=None, now=None,
                           dry_run=False, refetch=None, squad_lookup=None,
                           max_players=None):
    """
    Den Plan ausfuehren: betroffene Spieler gezielt erneuern.

    Idempotent und wiederholbar - genau das, was ein spaeterer Timer
    braucht. Zweimal hintereinander ausgefuehrt passiert beim zweiten Mal
    nichts Zusaetzliches, weil die frisch geholten Profile dann innerhalb
    ihrer Lebensdauer liegen.

    max_players begrenzt einen einzelnen Lauf. Eine Obergrenze ist kein
    Misstrauen gegen die Rechnung, sondern gegen den Sonderfall: Liefert
    der Anbieter versehentlich hundert beendete Spiele, soll der Lauf
    nicht das Tageslimit aufbrauchen.

    Rueckgabe: (plan, ergebnisse, zusammenfassung).
    """
    from src.data.player_refetch import refetch_many

    refetch = refetch or refetch_many

    if fixtures is None:
        if fetch_fixtures is None:
            from src.api.apisports_api import get_fixtures_by_date
            fetch_fixtures = get_fixtures_by_date
        tag = date_str or (now or _utc_now()).strftime("%Y-%m-%d")
        fixtures = fetch_fixtures(tag)

    plan = plan_post_match_refresh(fixtures, season, league_ids=league_ids,
                                   now=now, squad_lookup=squad_lookup)

    ids = plan["player_ids"]
    if max_players is not None and len(ids) > max_players:
        plan["gekuerzt_auf"] = max_players
        ids = ids[:max_players]

    if not ids:
        return plan, [], {"angefragt": 0, "bearbeitet": 0, "erfolgreich": 0,
                          "fehlgeschlagen": 0, "pool_aktualisiert": 0,
                          "veraendert": 0, "requests": 0,
                          "abgebrochen": False, "dry_run": bool(dry_run)}

    ergebnisse, zusammenfassung = refetch(ids, season, dry_run=dry_run)
    return plan, ergebnisse, zusammenfassung


def estimate_daily_cost(spieltage_je_woche=2, mannschaften_je_spieltag=20,
                        spieler_je_mannschaft=25):
    """
    Grobe Kostenrechnung fuer den Dauerbetrieb.

    Fuer den Bericht und die Entscheidung, ob ein Timer taeglich laufen
    darf. Die Zahlen sind Groessenordnungen, keine Zusicherungen.
    """
    je_spieltag = 1 + mannschaften_je_spieltag * spieler_je_mannschaft
    je_woche = spieltage_je_woche * je_spieltag + (7 - spieltage_je_woche)
    return {
        "requests_je_spieltag": je_spieltag,
        "requests_je_ruhetag": 1,
        "requests_je_woche": je_woche,
        "requests_je_tag_im_mittel": round(je_woche / 7),
        "vollrefresh_taeglich": 5 * 450,
        "tageslimit": 7500,
    }
