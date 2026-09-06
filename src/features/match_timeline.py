"""
Wettbewerbsuebergreifende Chronologie tatsaechlich ausgetragener Spiele.

WOFUER
------
Belastung entsteht nicht in einem Wettbewerb, sondern aus ihrer Summe.
Ein Team, das mittwochs im Pokal und samstags in der Liga spielt, ist
anders belastet als eines, das nur samstags spielt. Ohne eine gemeinsame
Zeitleiste laesst sich das nicht messen.

QUELLEN
-------
    Ligen (BL1, PL, PD, SA, FL1)   football-data.org, lokale Historie
    Champions League               football-data.org, lokale Historie
    Nationale Pokale               API-Sports, lokale Historie (GO 2)

Die ersten beiden teilen einen ID-Raum, die Pokale einen anderen. Die
Pokalspiele werden deshalb ueber src/features/team_crosswalk.py auf
football-data-IDs uebersetzt. Ein Pokalspiel ohne sichere Zuordnung
wird NICHT aufgenommen - lieber eine Luecke als ein falsch
zugeschriebenes Spiel.

WAS ZAEHLT
----------
Nur tatsaechlich ausgetragene Partien. Angesetzte, verschobene und
abgesagte Spiele erzeugen keine Ermuedung und stehen deshalb nicht in
der Zeitleiste. Die Zeitsemantik (was war wann bekannt) kommt
unveraendert aus src/features/point_in_time.py - hier wird sie benutzt,
nicht nachgebaut.
"""

from src.features.point_in_time import match_date, match_time


#: Wettbewerbe, die Pflichtspielbelastung erzeugen.
LEAGUE_COMPETITIONS = ("BL1", "PL", "PD", "SA", "FL1")
CUP_COMPETITIONS = ("CL",)
DOMESTIC_CUP_KEYS = ("dfb", "fac", "cdr", "cit", "cdf")

#: Nationale Ligen der CL-Teilnehmer ausserhalb der Top 5 (V2-C2B).
#:
#: Sie kommen von API-Sports und tragen deshalb dessen Team-IDs. Die
#: Uebersetzung auf die interne (football-data-) Identitaet macht
#: _national_league_entries ueber CL_PARTICIPANT_CROSSWALK.
NATIONAL_LEAGUE_KEYS = tuple(sorted({
    "pt1", "nl1", "be1", "at1", "tr1", "sco1", "dk1", "cz1", "ch1",
    "rs1", "ua1", "no1", "gr1", "az1", "hr1", "cy1", "sk1", "kz1",
}))

#: football-data-ID -> API-Sports-ID fuer die CL-Teilnehmer, deren
#: nationale Liga zusaetzlich geladen wurde.
#:
#: WIE DIESE TABELLE ENTSTAND - UND WARUM SIE EXPLIZIT IST
#: Zugeordnet wurde am 2026-09-06 INNERHALB DERSELBEN WETTBEWERBSSAISON:
#: die CL-Teilnehmerliste aus data/historical/CL_<saison>.json gegen
#: /fixtures?league=2&season=<saison> bei API-Sports. Beide Seiten
#: beschreiben dieselben Partien, also dieselben Vereine - das ist der
#: engste Vergleichsraum, den es hier gibt.
#:
#: 20 der 27 Vereine loesten sich ueber die normalisierte Schreibweise
#: oder die Teilmengenregel eindeutig auf. Die uebrigen sieben tragen
#: bei den beiden Anbietern verschiedene Namen und stehen deshalb
#: einzeln und nachvollziehbar hier. Ein unscharfer Vergleich war
#: ausdruecklich nicht die Alternative: "Union St. Gilloise" und
#: "Union Berlin" stehen beide in der CL-Teilnehmerliste, und ein
#: Treffer auf "Union" haette den falschen Verein belastet.
#:
#: Gegengeprueft: Jede API-Sports-ID taucht tatsaechlich in der
#: Teamliste der zugehoerigen Ligadatei auf (27 von 27).
CL_PARTICIPANT_CROSSWALK = {
    # eindeutig ueber die Schreibweise
    851: 569,    # Club Brugge KV
    732: 247,    # Celtic FC
    1871: 565,   # BSC Young Boys
    7283: 598,   # FK Crvena Zvezda
    1877: 571,   # FC Red Bull Salzburg
    503: 212,    # FC Porto
    907: 628,    # AC Sparta Praha
    # eindeutig ueber die Teilmengenregel
    1903: 211,   # Sport Lisboa e Benfica   -> "Benfica"
    674: 197,    # PSV                      -> "PSV Eindhoven"
    675: 209,    # Feyenoord Rotterdam      -> "Feyenoord"
    610: 645,    # Galatasaray SK           -> "Galatasaray"
    1887: 550,   # FK Shakhtar Donetsk      -> "Shakhtar Donetsk"
    611: 556,    # Qarabag Agdam FK         -> "Qarabag"
    755: 620,    # GNK Dinamo Zagreb        -> "Dinamo Zagreb"
    7509: 656,   # SK Slovan Bratislava     -> "Slovan Bratislava"
    2021: 637,   # SK Sturm Graz            -> "Sturm Graz"
    930: 560,    # SK Slavia Praha          -> "Slavia Praha"
    678: 194,    # AFC Ajax                 -> "Ajax"
    1864: 740,   # Royal Antwerp FC         -> "Antwerp"
    5613: 217,   # Sporting Clube de Braga  -> "SC Braga"
    # verschiedene Anbieternamen - einzeln belegt
    498: 228,    # Sporting Clube de Portugal  -> "Sporting CP"
    1876: 400,   # FC Kobenhavn                -> "FC Copenhagen"
    5721: 327,   # FK Bodo/Glimt               -> "Bodo/Glimt"
    654: 553,    # PAE Olympiakos SFP          -> "Olympiakos Piraeus"
    3929: 1393,  # Royale Union Saint-Gilloise -> "Union St. Gilloise"
    11034: 3403, # Paphos FC                   -> "Pafos"
    10601: 664,  # FK Kairat                   -> "Kairat Almaty"
}

#: API-Sports-ID -> football-data-ID. Aus der Tabelle oben abgeleitet,
#: damit es nur EINE gepflegte Richtung gibt.
_APISPORTS_TO_INTERNAL = {v: k for k, v in CL_PARTICIPANT_CROSSWALK.items()}

assert len(_APISPORTS_TO_INTERNAL) == len(CL_PARTICIPANT_CROSSWALK), (
    "zwei Vereine zeigen auf dieselbe API-Sports-ID - eine Belastung "
    "wuerde dem falschen Verein zugerechnet")

#: Fehlt eine Anstosszeit, wird konservativ Mittag angenommen.
#:
#: Warum Mittag und nicht 00:00: Eine Nullzeit wuerde ein Spiel um einen
#: halben Tag zu frueh einsortieren und die Erholungszeit zum naechsten
#: Spiel systematisch ueberschaetzen. Mittag ist der Zeitpunkt mit dem
#: kleinsten moeglichen Fehler in beide Richtungen - hoechstens zwoelf
#: Stunden statt bis zu vierundzwanzig.
FALLBACK_KICKOFF_HOUR = 12


def _to_datetime(match):
    """
    Zeitpunkt eines Spiels als datetime, normalisiert auf UTC und naiv.

    Rueckgabe: (datetime_oder_None, genauigkeit)
    genauigkeit ist "datetime" bei echter Anstosszeit, "date" beim
    Rueckfall auf FALLBACK_KICKOFF_HOUR.

    WARUM HIER UND NICHT IN point_in_time
    -------------------------------------
    Die Pokaldateien fuehren die Anstosszeit im Feld "kickoff"
    ("2025-08-15T18:30:00+00:00"), die Ligadateien fuehren ueberhaupt
    keine Uhrzeit. point_in_time._TIMESTAMP_FIELDS kennt nur "utc_date"
    und "utcDate" - match_time() gibt fuer ein Pokalspiel deshalb None
    zurueck, obwohl die Zeit dasteht.

    Dieses Feld dort zu ergaenzen waere der falsche Ort: davon haengt
    is_known_at() ab, also die projektweite Cutoff-Semantik. Ein
    zusaetzliches Zeitfeld wuerde bestehende Schnitte praezisieren und
    damit stillschweigend das Verhalten aller Aufrufer aendern. Die
    Zeitleiste liest "kickoff" deshalb selbst und laesst die geteilte
    Semantik unberuehrt.
    """
    from datetime import datetime, timezone

    roh = match.get("kickoff")
    if isinstance(roh, str) and len(roh) >= 19 and "T" in roh:
        try:
            zeitpunkt = datetime.fromisoformat(roh.replace("Z", "+00:00"))
        except ValueError:
            zeitpunkt = None
        if zeitpunkt is not None:
            if zeitpunkt.tzinfo is not None:
                # Auf UTC umrechnen und die Zone abstreifen. Alles in
                # der Zeitleiste ist danach in derselben Skala - sonst
                # waere jede Stundendifferenz zwischen zwei Quellen um
                # den Zonenversatz falsch.
                zeitpunkt = zeitpunkt.astimezone(timezone.utc).replace(tzinfo=None)
            return zeitpunkt, "datetime"

    tag = match_date(match)
    if not tag:
        return None, None

    try:
        jahr, monat, tagnr = (int(t) for t in str(tag).split("-")[:3])
    except (ValueError, AttributeError):
        return None, None

    uhrzeit = match_time(match)
    if uhrzeit:
        try:
            teile = str(uhrzeit).split(":")
            return datetime(jahr, monat, tagnr, int(teile[0]),
                            int(teile[1]) if len(teile) > 1 else 0), "datetime"
        except (ValueError, IndexError):
            pass

    return datetime(jahr, monat, tagnr, FALLBACK_KICKOFF_HOUR), "date"


def _entry(match, competition, competition_name, season, source, quality,
           home_id, away_id):
    """Ein normalisierter Zeitleisteneintrag."""
    zeitpunkt, genauigkeit = _to_datetime(match)
    if zeitpunkt is None:
        return None

    match_id = match.get("match_id") or match.get("id")
    if match_id is None:
        # Deterministische Ersatz-ID, damit Deduplizierung trotzdem greift.
        match_id = f"{competition}:{season}:{zeitpunkt.date()}:{home_id}:{away_id}"

    return {
        "match_id": match_id,
        "season": season,
        "competition": competition,
        "competition_name": competition_name,
        "kickoff": zeitpunkt,
        "time_precision": genauigkeit,
        "date": zeitpunkt.date().isoformat(),
        # Die Runde. Sie steht in den CL- und Pokaldateien und wird seit
        # V2-C3 mitgefuehrt, weil sich nur mit ihr entscheiden laesst, ob
        # eine Partie ueberhaupt in die Verlaengerung gehen KONNTE:
        # Rundenspiele koennen es nicht, K.-o.-Partien schon. Ohne die
        # Runde bliebe jede CL-Partie als "Verlaengerung unbekannt"
        # stehen - und ein Merkmal, das ueberall unbekannt ist, ist
        # keines.
        "stage": match.get("stage"),
        "home_id": home_id,
        "away_id": away_id,
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "status": match.get("status"),
        "played": True,
        "home_goals": match.get("home_goals"),
        "away_goals": match.get("away_goals"),
        "source": source,
        "data_quality": quality,
    }


def _league_entries(season):
    """Liga- und CL-Spiele aus der lokalen Historie."""
    from src.data.historical_loader import load_season

    eintraege = []
    for api_code in list(LEAGUE_COMPETITIONS) + list(CUP_COMPETITIONS):
        payload = load_season(api_code, season)
        if not payload:
            continue

        # Die Spieleintraege der Ligadateien fuehren nur Team-IDs. Die
        # Namen stehen im teams-Block derselben Datei - fuer Diagnose
        # und API-Ausgabe sind sie noetig, damit dort nicht nackte
        # Zahlen erscheinen.
        namen = {}
        for tid, info in (payload.get("teams") or {}).items():
            bezeichnung = (info or {}).get("name") or (info or {}).get("short_name")
            if bezeichnung:
                try:
                    namen[int(tid)] = bezeichnung
                except (TypeError, ValueError):
                    continue

        for match in (payload.get("matches") or []):
            # Domestic-Historie enthaelt ausschliesslich FINISHED-Spiele
            # (der Loader filtert providerseitig). Die CL-Dateien fuehren
            # den Status mit - dort wird er geprueft.
            status = match.get("status")
            if status is not None and str(status).upper() != "FINISHED":
                continue
            if match.get("home_goals") is None or match.get("away_goals") is None:
                continue

            eintrag = _entry(
                match, api_code, api_code, season,
                source="football-data.org", quality="complete",
                home_id=match.get("home_id"), away_id=match.get("away_id"),
            )
            if eintrag:
                eintrag["home_team"] = eintrag["home_team"] or namen.get(eintrag["home_id"])
                eintrag["away_team"] = eintrag["away_team"] or namen.get(eintrag["away_id"])
                eintraege.append(eintrag)

    return eintraege


def _cup_entries(season, crosswalks=None):
    """
    Nationale Pokalspiele, uebersetzt auf football-data-Team-IDs.

    Ein Spiel wird nur aufgenommen, wenn MINDESTENS ein Team sicher
    zugeordnet ist. Der unterklassige Gegner bleibt dann ohne interne ID
    stehen (None) - er erzeugt keine eigene Belastung, verfaelscht aber
    auch nichts.
    """
    from src.data.domestic_cup_loader import (
        DOMESTIC_CUPS, load_cup_season, is_finished)
    from src.features.team_crosswalk import build_crosswalk

    eintraege = []
    diagnose = []

    for cup_key in DOMESTIC_CUP_KEYS:
        cfg = DOMESTIC_CUPS.get(cup_key)
        if not cfg:
            continue

        payload = load_cup_season(cup_key, season)
        if not payload:
            continue

        as_teams = {int(k): (v or {}).get("name")
                    for k, v in (payload.get("teams") or {}).items()}

        if crosswalks is not None and cup_key in crosswalks:
            cw = crosswalks[cup_key]
        else:
            cw = build_crosswalk(cfg["league_key"], season, as_teams)
        diagnose.append(cw)

        mapping = cw["mapping"]
        # Ohne jede Zuordnung waere die Datei nutzlos - dann lieber
        # sichtbar als fallback kennzeichnen.
        qualitaet = "complete" if cw["mapped_count"] else "fallback"

        for match in (payload.get("matches") or []):
            if not is_finished(match):
                continue

            heim = mapping.get(match.get("home_id"))
            gast = mapping.get(match.get("away_id"))
            if heim is None and gast is None:
                # Reines Unterklassenduell - fuer FootSim ohne Bedeutung.
                continue

            eintrag = _entry(
                match, cfg["code"], cfg["name"], season,
                source="api-football.com", quality=qualitaet,
                home_id=heim, away_id=gast,
            )
            if eintrag:
                eintraege.append(eintrag)

    return eintraege, diagnose


def _national_league_entries(season):
    """
    Nationale Ligaspiele der CL-Teilnehmer ausserhalb der Top 5.

    Uebersetzt die API-Sports-Team-IDs auf die interne Identitaet. Ein
    Spiel wird nur aufgenommen, wenn MINDESTENS ein Team zugeordnet ist -
    die uebrigen 15 bis 19 Vereine einer solchen Liga interessieren
    FootSim nicht und bekommen bewusst keine erfundene ID.

    Der Gegner eines zugeordneten Vereins bleibt dabei ohne interne ID
    (None) stehen. Er erzeugt keine eigene Belastung, verfaelscht aber
    auch nichts - dieselbe Regel wie beim FA Cup.
    """
    from src.data.national_league_loader import (
        NATIONAL_LEAGUES, REQUIRED_SEASONS, is_finished, load_league_season)

    eintraege = []
    diagnose = []

    for league_key in NATIONAL_LEAGUE_KEYS:
        if season not in REQUIRED_SEASONS.get(league_key, ()):
            continue
        cfg = NATIONAL_LEAGUES.get(league_key)
        if not cfg:
            continue

        payload = load_league_season(league_key, season)
        if not payload:
            diagnose.append({"competition": cfg["code"], "season": season,
                             "status": "missing_file"})
            continue

        zugeordnet = 0
        for match in (payload.get("matches") or []):
            if not is_finished(match):
                continue

            heim = _APISPORTS_TO_INTERNAL.get(match.get("home_id"))
            gast = _APISPORTS_TO_INTERNAL.get(match.get("away_id"))
            if heim is None and gast is None:
                continue

            eintrag = _entry(
                match, cfg["code"], cfg["name"], season,
                source="api-football.com", quality="complete",
                home_id=heim, away_id=gast,
            )
            if eintrag:
                eintraege.append(eintrag)
                zugeordnet += 1

        diagnose.append({"competition": cfg["code"], "season": season,
                         "status": "loaded",
                         "matches_in_file": len(payload.get("matches") or []),
                         "entries_with_internal_team": zugeordnet})

    return eintraege, diagnose


def build_timeline(seasons, crosswalks=None):
    """
    Vollstaendige Zeitleiste ueber alle Wettbewerbe und Saisons.

    Rueckgabe: (eintraege, diagnose)

    Dedupliziert ueber (competition, season, match_id). Dasselbe Spiel
    kann in mehreren Dateien stehen - etwa wenn eine Saison zweimal
    importiert wurde. Es darf trotzdem nur einmal Belastung erzeugen.
    """
    gesehen = set()
    alle = []
    diagnose_gesamt = []

    for season in seasons:
        for eintrag in _league_entries(season):
            schluessel = (eintrag["competition"], eintrag["season"], eintrag["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            alle.append(eintrag)

        cup_eintraege, diagnose = _cup_entries(season, crosswalks)
        diagnose_gesamt.extend(diagnose)
        for eintrag in cup_eintraege:
            schluessel = (eintrag["competition"], eintrag["season"], eintrag["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            alle.append(eintrag)

        # Nationale Ligen der uebrigen CL-Teilnehmer (V2-C2B). Dieselbe
        # Deduplizierung wie oben: Der Schluessel traegt den Wettbewerb,
        # deshalb koennen sich die Match-IDs zweier Anbieter nicht in
        # die Quere kommen.
        liga_eintraege, liga_diagnose = _national_league_entries(season)
        diagnose_gesamt.extend(liga_diagnose)
        for eintrag in liga_eintraege:
            schluessel = (eintrag["competition"], eintrag["season"], eintrag["match_id"])
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            alle.append(eintrag)

    alle.sort(key=lambda e: (e["kickoff"], str(e["match_id"])))
    return alle, diagnose_gesamt


#: Wettbewerbe, die den WOECHENTLICHEN Grundtakt einer Mannschaft
#: erzeugen. Nur wer hier auftaucht, hat eine rekonstruierbare
#: Belastungskurve.
#:
#: Der Unterschied ist wesentlich und nicht formal: Ein Verein spielt
#: zwischen zwei Europapokalabenden zwei bis drei Ligaspiele. Fehlt
#: seine Liga, sieht die Zeitleiste nur die Europapokalpartien im
#: Zweiwochentakt - und eine daraus gerechnete Ruhezeit waere
#: systematisch zu lang. Nachgemessen an den CL-Zeilen 2023-2025:
#: Median 3,0 Tage bei Mannschaften MIT Ligahistorie, 15,0 Tage ohne.
#: Die Wettbewerbscodes der zusaetzlichen Ligen - aus der Registrierung
#: abgeleitet, nicht ein zweites Mal getippt. Eine zweite Liste liefe
#: frueher oder spaeter auseinander.
def _national_league_codes():
    from src.data.national_league_loader import NATIONAL_LEAGUES

    return frozenset(NATIONAL_LEAGUES[k]["code"] for k in NATIONAL_LEAGUE_KEYS)


BASE_LOAD_COMPETITIONS = frozenset(LEAGUE_COMPETITIONS) | _national_league_codes()

#: Wie weit vor dem Stichtag eine Ligapartie liegen darf, damit die
#: Belastung als rekonstruierbar gilt.
#:
#: 45 Tage decken eine Winterpause nicht ab, aber jede normale
#: Spielphase mit Abstand. Kuerzer waere zu streng (Laenderspielpausen
#: erzeugen bis zu drei Wochen ohne Vereinsspiel), laenger wuerde eine
#: Mannschaft als abgedeckt fuehren, deren letzte sichtbare Ligapartie
#: fachlich nichts mehr aussagt.
BASE_LOAD_WINDOW_DAYS = 45

#: Warum eine Seite keine belastbare Belastungsangabe bekommt.
COVERAGE_OK = "covered"
COVERAGE_NO_BASE_COMPETITION = "no_base_competition_in_timeline"
COVERAGE_STALE = "base_competition_stale"


def base_load_coverage(entries, team_id, cutoff,
                       window_days=BASE_LOAD_WINDOW_DAYS):
    """
    Laesst sich die Belastung dieser Mannschaft ehrlich rekonstruieren?

    Rueckgabe: (bool, grund).

    DIE FRAGE IST NICHT "kennen wir irgendein Spiel", SONDERN
    "kennen wir ihren Grundtakt". Die Zeitleiste kennt jeden
    CL-Teilnehmer - aber von einem Teil nur dessen CL-Partien. Aus
    denen eine Ruhezeit zu rechnen ergaebe eine plausibel aussehende
    Zahl, die um den Faktor vier danebenliegt. Ein ehrliches Fehlen ist
    besser als ein falscher Wert, den niemand mehr hinterfragt.

    Geprueft wird ausschliesslich VOR dem Stichtag - diese Funktion
    darf den Point-in-Time-Vertrag nicht unterlaufen.
    """
    from datetime import timedelta

    if cutoff is None or team_id is None:
        return False, COVERAGE_NO_BASE_COMPETITION

    grenze = cutoff - timedelta(days=window_days)
    gesehen = False

    for eintrag in entries:
        if eintrag.get("competition") not in BASE_LOAD_COMPETITIONS:
            continue
        if team_id not in (eintrag.get("home_id"), eintrag.get("away_id")):
            continue
        zeitpunkt = eintrag.get("kickoff")
        if zeitpunkt is None or zeitpunkt >= cutoff:
            continue
        gesehen = True
        if zeitpunkt >= grenze:
            return True, COVERAGE_OK

    return False, (COVERAGE_STALE if gesehen else COVERAGE_NO_BASE_COMPETITION)


def team_timeline(entries, team_id):
    """
    Die Spiele EINES Teams, chronologisch.

    Jeder Eintrag bekommt zusaetzlich is_home und opponent_id, damit
    spaeter erkennbar bleibt, woher die Belastung kam.
    """
    # Ohne Kennung gibt es keine Zeitleiste (V2-C2). Ohne diese Zeile
    # traefe None == None: Ein Pokalspiel, dessen unterklassiger Verein
    # sich nicht zuordnen liess, wuerde jedem Aufrufer zugerechnet, der
    # versehentlich None uebergibt. Eine unsichere Zuordnung darf nicht
    # still zur sicheren werden.
    if team_id is None:
        return []

    ergebnis = []
    for eintrag in entries:
        if team_id == eintrag.get("home_id"):
            heim = True
        elif team_id == eintrag.get("away_id"):
            heim = False
        else:
            continue

        kopie = dict(eintrag)
        kopie["is_home"] = heim
        kopie["opponent_id"] = eintrag["away_id"] if heim else eintrag["home_id"]
        ergebnis.append(kopie)

    ergebnis.sort(key=lambda e: (e["kickoff"], str(e["match_id"])))
    return ergebnis


def matches_before(timeline, cutoff):
    """
    Spiele STRIKT vor dem Zeitpunkt.

    Der Kern des Leakage-Schutzes: Das Zielspiel selbst und alles
    danach bleibt draussen. Bewusst strikt kleiner - ein Spiel, das zur
    selben Minute angepfiffen wird, ist keine vorherige Belastung.
    """
    if cutoff is None:
        return []
    return [e for e in timeline if e["kickoff"] < cutoff]


def coverage(entries):
    """Woraus die Zeitleiste besteht - fuer Diagnose und Datenqualitaet."""
    nach_wettbewerb = {}
    for eintrag in entries:
        nach_wettbewerb[eintrag["competition"]] = \
            nach_wettbewerb.get(eintrag["competition"], 0) + 1

    ligen = [c for c in nach_wettbewerb if c in LEAGUE_COMPETITIONS]
    pokale = [c for c in nach_wettbewerb
              if c not in LEAGUE_COMPETITIONS and c not in CUP_COMPETITIONS]

    genauigkeit = {}
    for eintrag in entries:
        stufe = eintrag.get("time_precision") or "unknown"
        genauigkeit[stufe] = genauigkeit.get(stufe, 0) + 1

    return {
        "competitions": sorted(nach_wettbewerb),
        # Wie viele Spiele eine echte Anstosszeit haben. Praktisch nur
        # die Pokale: die football-data-Historie fuehrt ausschliesslich
        # Kalendertage. Stundengenaue Pausen sind deshalb fuer den
        # groessten Teil der Spiele eine Naeherung - das muss sichtbar
        # bleiben, statt Genauigkeit vorzutaeuschen.
        "time_precision": genauigkeit,
        "matches_by_competition": nach_wettbewerb,
        "total_matches": len(entries),
        "has_leagues": bool(ligen),
        "has_champions_league": "CL" in nach_wettbewerb,
        "has_domestic_cups": bool(pokale),
        # Bekannte, nicht abrufbare Wettbewerbe - ehrlich benannt statt
        # stillschweigend weggelassen.
        "known_gaps": ["UEFA Europa League", "UEFA Conference League"],
    }
