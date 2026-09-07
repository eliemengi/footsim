"""
Kader- und Verfuegbarkeitsmomentaufnahmen (V2-C6).

WOZU
----
Ergebnisse lassen sich nachtraeglich holen. Kaderstaende und
Verletzungen nicht: Wer heute fragt, wer dem FC Bayern am 12. November
2025 fehlte, bekommt vom Anbieter den HEUTIGEN Stand. Diese Historie
entsteht nur, indem man sie ab jetzt sammelt.

Dieses Modul definiert, WAS gesammelt wird und in welcher Form. Das WIE
- Planung, Netz, Wiederholungen, Sperre, Bericht - steht in
snapshot_collector.py; die Ablage in snapshot_archive.py. Drei Ebenen,
damit die fachliche Form ohne Netz und ohne Dateisystem testbar bleibt.

DIE ZWEI QUELLEN UND IHRE SEHR VERSCHIEDENE ZEITSEMANTIK
--------------------------------------------------------
Nachgemessen am 06.09.2026 mit vier Requests:

    /players/squads?team=X
        Liefert den Kader OHNE jede Zeit- oder Saisonangabe. Geprueft:
        Die Antwort enthaelt kein einziges Feld mit "date" oder
        "season" im Namen. Ein Kadersnapshot hat deshalb KEINEN
        effective_at - er belegt ausschliesslich: "spaetestens bei
        diesem Abruf sah der Kader so aus".

    /injuries?league=X&season=Y
        Liefert 2832 Eintraege fuer die Bundesliga 2025 auf EINER
        Seite, jeder mit fixture.date. Das ist keine Momentaufnahme,
        sondern eine partiebezogene Liste: "Spieler P fehlte bei Partie
        F am Datum D". Diese Eintraege HABEN einen echten
        Gueltigkeitszeitpunkt.

Der Unterschied ist der Kern des Point-in-Time-Vertrags dieses Moduls
und wird nirgends verwischt: fetched_at ist der Abruf, effective_at der
von der Quelle behauptete Zeitpunkt. Fehlt der zweite, bleibt er None -
er wird NIEMALS aus dem ersten erfunden.

WAS "AVAILABILITY" HIER HEISST - UND WAS NICHT
----------------------------------------------
Der Endpunkt heisst "injuries", liefert aber mehr als Verletzungen. Aus
derselben Probe, Bundesliga 2025:

    player.type    "Missing Fixture" 2694, "Questionable" 138
    player.reason  Knee Injury 631, Muscle Injury 419, ...,
                   Yellow Cards 87, Red Card 78, Illness 88

Sperren sind also enthalten - aber als FREITEXT im selben Feld wie
Verletzungen, nicht als eigener typisierter Wert. Dieses Modul
normalisiert sie in Kategorien und behaelt den Rohwert daneben. Was es
NICHT tut: den Bestand als vollstaendige Verfuegbarkeitslage ausgeben.
Rotationsentscheidungen, nicht gemeldete Blessuren und alles, was der
Anbieter nicht kennt, fehlen darin - und ein Modell, das die Liste fuer
vollstaendig haelt, wuerde eine Abwesenheit von Eintraegen als
"alle fit" lesen.
"""

import re

#: Fassung des Snapshot-Schemas.
#:
#: 1  V2-C6: Erstfassung. Kader und Verfuegbarkeit, getrennte
#:    Zeitsemantik, normalisierte Abwesenheitsgruende.
SNAPSHOT_SCHEMA_VERSION = 1

#: Fassung des sammelnden Codes. Sie steht in jedem Snapshot, damit
#: spaeter unterscheidbar bleibt, ob ein Unterschied aus den Daten oder
#: aus einer geaenderten Normalisierung stammt.
COLLECTOR_VERSION = "c6.1"

#: Die beiden Snapshotarten. Sie landen in getrennten Archivzweigen.
KIND_SQUAD = "squad"
KIND_AVAILABILITY = "availability"
SNAPSHOT_KINDS = (KIND_SQUAD, KIND_AVAILABILITY)

#: Woher die Daten stammen.
SOURCE_APISPORTS = "api-football.com"

#: Endpunkte, so wie sie beim Anbieter heissen.
ENDPOINT_SQUAD = "players/squads"
ENDPOINT_INJURIES = "injuries"


# ---------------------------------------------------------------------------
# Zeitvertrag
# ---------------------------------------------------------------------------

#: Warum ein effective_at fehlt. Sichtbar statt stillschweigend None.
EFFECTIVE_FROM_SOURCE = "source_fixture_date"
EFFECTIVE_UNKNOWN_SQUAD = "unknown_source_has_no_timestamp"
EFFECTIVE_UNKNOWN_MISSING = "unknown_field_absent_in_entry"

#: Was fetched_at belegt - und was nicht. Der Satz steht in jedem
#: Snapshot, damit ein spaeterer Leser ihn nicht rekonstruieren muss.
FETCHED_AT_MEANING = (
    "Zeitpunkt des Abrufs. Belegt ausschliesslich: spaetestens jetzt war "
    "dieser Zustand sichtbar. KEIN Beginn einer Verletzung, Sperre oder "
    "Kaderaenderung - dafuer steht effective_at, und wo dieses fehlt, "
    "bleibt der Beginn unbekannt."
)


# ---------------------------------------------------------------------------
# Normalisierung der Abwesenheitsgruende
# ---------------------------------------------------------------------------

#: Die normalisierten Kategorien.
ABSENCE_INJURY = "injury"
ABSENCE_SUSPENSION = "suspension"
ABSENCE_ILLNESS = "illness"
ABSENCE_PERSONAL = "personal"
ABSENCE_COACH = "coach_decision"
#: Kein gemeldeter Schaden, aber auch nicht einsatzbereit: "Lacking
#: Match Fitness", "Fitness", "Inactive". Eine eigene Kategorie, weil
#: beide Alternativen falsch waeren - als Verletzung gefuehrt behauptet
#: sie einen Schaden, unter "other" verschwindet ein klar benannter und
#: haeufiger Zustand (157 Eintraege allein in der Bundesliga 2025).
ABSENCE_FITNESS = "fitness"
ABSENCE_OTHER = "other"
ABSENCE_UNKNOWN = "unknown"

ABSENCE_CATEGORIES = (ABSENCE_INJURY, ABSENCE_SUSPENSION, ABSENCE_ILLNESS,
                      ABSENCE_PERSONAL, ABSENCE_COACH, ABSENCE_FITNESS,
                      ABSENCE_OTHER, ABSENCE_UNKNOWN)

#: Muster je Kategorie, in FESTER Reihenfolge geprueft.
#:
#: Die Reihenfolge entscheidet, und sie ist nicht beliebig: "Red Card"
#: muss vor jedem Verletzungsmuster stehen, sonst faenge ein
#: allgemeines "injur" spaeter einen Eintrag wie "Injury after red
#: card" falsch ein. Sperren zuerst, dann die klar benannten Faelle,
#: dann Verletzungen als breitester Topf.
#:
#: Die Muster stammen aus dem TATSAECHLICHEN Wortschatz des Anbieters,
#: nicht aus Vermutung. Ausgezaehlt an einem echten Snapshot
#: (Bundesliga 2025, 2404 Eintraege): Knee Injury 631, Muscle Injury,
#: Ankle Injury, Injury, Thigh Injury, Groin Injury, Illness, Yellow
#: Cards 68, Calf Injury, Red Card 67, Achilles Tendon Injury, Foot
#: Injury - und in der zweiten Reihe Lacking Match Fitness 34, Inactive
#: 28, Muscle bruise 21, Jumpers knee 19, Sprained ankle 11, Thigh
#: problems 8, Wound 5, Cruciate ligament stretch 4, Appendicitis 3,
#: Groin operation 2, Back trouble 1, Stomach complaints 1.
#:
#: Die zweite Reihe war beim ersten Lauf durchgefallen. Sie als "other"
#: stehen zu lassen waere bequem gewesen und falsch: "Sprained ankle"
#: ist eine Verletzung, "Appendicitis" eine Krankheit, und "Lacking
#: Match Fitness" ist beides nicht.
ABSENCE_PATTERNS = (
    # Sperren ZUERST. Sonst faenge ein allgemeines Verletzungsmuster
    # einen Eintrag wie "Red card Suspended" nicht mehr richtig ein.
    (ABSENCE_SUSPENSION, (r"\bred card", r"\byellow card", r"\bsuspend",
                          r"\bsuspension\b", r"\bban\b", r"\bbanned\b",
                          r"\bsent off\b")),
    (ABSENCE_ILLNESS, (r"\billness\b", r"\bill\b", r"\bsick\b",
                       r"\bvirus\b", r"\bcovid", r"\bfever\b", r"\bflu\b",
                       r"\bappendicitis\b", r"\bstomach\b",
                       r"\bdisorder\b", r"\bcomplaints?\b")),
    (ABSENCE_PERSONAL, (r"\bpersonal\b", r"\bfamily\b", r"\bbereave",
                        r"\bnational team\b", r"\binternational duty\b")),
    (ABSENCE_COACH, (r"\bcoach\b", r"\brotation\b", r"\bnot in squad\b")),
    # Zustand ohne gemeldeten Schaden - vor den Verletzungsmustern,
    # damit "Lacking Match Fitness" nicht spaeter irgendwo haengen
    # bleibt.
    (ABSENCE_FITNESS, (r"\bfitness\b", r"\binactive\b", r"\bcondition\b",
                       r"\bmatch practice\b", r"\brest\b")),
    # Verletzungen zuletzt und am breitesten: Hier landet alles, was
    # einen koerperlichen Schaden benennt.
    (ABSENCE_INJURY, (r"\binjur", r"\bfracture\b", r"\bstrain\b",
                      r"\btear\b", r"\brupture\b", r"\bsurgery\b",
                      r"\boperation\b", r"\bknock\b", r"\bhamstring\b",
                      r"\bacl\b", r"\bconcussion\b", r"\bbroken\b",
                      r"\bbruise\b", r"\bsprain", r"\bligament\b",
                      r"\btendon\b", r"\bwound\b", r"\bproblems?\b",
                      r"\btrouble\b", r"\bcrack\b", r"\bpain\b",
                      r"\bmeniscus\b", r"\bfemoral\b", r"\bmuscular\b",
                      r"\bknee\b", r"\bankle\b", r"\bthigh\b",
                      r"\bcalf\b", r"\bgroin\b", r"\bshoulder\b",
                      r"\bfoot\b", r"\bback\b", r"\bhip\b")),
)

#: Der Anbietertyp: "Missing Fixture" heisst sicher raus, "Questionable"
#: heisst fraglich. Beides bleibt getrennt - sie in einen Wert zu legen
#: waere ein Informationsverlust, der spaeter nicht mehr aufzuholen ist.
STATUS_OUT = "out"
STATUS_DOUBTFUL = "doubtful"
STATUS_UNKNOWN = "unknown"

RAW_TYPE_TO_STATUS = {
    "missing fixture": STATUS_OUT,
    "questionable": STATUS_DOUBTFUL,
}


def normalise_absence_reason(raw_reason):
    """
    Der Rohgrund in eine Kategorie - der Rohwert geht dabei nicht verloren.

    Rueckgabe: eine der ABSENCE_CATEGORIES.

    Bewusst musterbasiert und nicht ueber eine Wertetabelle: Der
    Anbieter liefert Freitext, und eine Tabelle waere am Tag nach dem
    ersten unbekannten Wert unvollstaendig, ohne dass es auffiele. Ein
    nicht erkannter Text wird ABSENCE_OTHER - sichtbar, und der Rohwert
    steht daneben.
    """
    if raw_reason is None:
        return ABSENCE_UNKNOWN
    text = str(raw_reason).strip().lower()
    if not text:
        return ABSENCE_UNKNOWN

    for kategorie, muster in ABSENCE_PATTERNS:
        for einzelmuster in muster:
            if re.search(einzelmuster, text):
                return kategorie
    return ABSENCE_OTHER


def normalise_availability_status(raw_type):
    """Der Anbietertyp als normalisierter Status."""
    if raw_type is None:
        return STATUS_UNKNOWN
    return RAW_TYPE_TO_STATUS.get(str(raw_type).strip().lower(),
                                  STATUS_UNKNOWN)


# ---------------------------------------------------------------------------
# Kadersnapshot
# ---------------------------------------------------------------------------

def _als_int(wert):
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def normalise_squad(raw_response, team_id=None):
    """
    Die Anbieterantwort von /players/squads in die Snapshotform.

    Rueckgabe: (payload, beanstandungen).

    IDENTITAET
    Primaerschluessel ist die Spieler-ID des Anbieters. Namen werden
    mitgefuehrt, aber niemals als Schluessel benutzt - im Projekt gibt
    es dafuer einen dokumentierten Vorfall ("Barcelona" loeste ueber
    Teilstring auf "RCD Espanyol de Barcelona" auf). Ein Eintrag ohne
    verwertbare ID wird gezaehlt und verworfen, nicht geraten.

    DOPPELTE EINTRAEGE
    Zwei Zeilen mit derselben Spieler-ID sind ein Datenfehler. Die
    erste gewinnt, die zweite wird gemeldet - stillschweigend beide zu
    behalten wuerde jede spaetere Zaehlung verfaelschen.

    Die Spielerliste wird nach ID SORTIERT abgelegt. Ohne feste
    Sortierung ergaebe eine andere Reihenfolge beim Anbieter einen
    anderen Fingerabdruck, und das Archiv wuerde eine Aenderung
    behaupten, die keine ist.
    """
    beanstandungen = []
    eintraege = raw_response if isinstance(raw_response, list) else []

    if not eintraege:
        return None, ["leere Antwort"]

    block = eintraege[0]
    if not isinstance(block, dict):
        return None, ["unerwartete Antwortform"]

    team = block.get("team") or {}
    aufgeloeste_id = _als_int(team.get("id")) or _als_int(team_id)
    if aufgeloeste_id is None:
        return None, ["Antwort ohne Team-Kennung"]

    if team_id is not None and _als_int(team_id) is not None \
            and aufgeloeste_id != _als_int(team_id):
        # Eine Antwort ueber eine ANDERE Mannschaft. Sie zu speichern
        # waere schlimmer als sie zu verwerfen: Der Snapshot traege den
        # angefragten Schluessel und fremde Spieler.
        return None, [f"Antwort betrifft Team {aufgeloeste_id}, "
                      f"angefragt war {_als_int(team_id)}"]

    spieler = []
    gesehen = set()
    for roh in (block.get("players") or []):
        if not isinstance(roh, dict):
            continue
        pid = _als_int(roh.get("id"))
        if pid is None:
            beanstandungen.append("Spieler ohne Kennung verworfen")
            continue
        if pid in gesehen:
            beanstandungen.append(f"doppelte Spieler-Kennung {pid}")
            continue
        gesehen.add(pid)
        spieler.append({
            "player_id": pid,
            "name": roh.get("name"),
            "number": _als_int(roh.get("number")),
            "position": roh.get("position"),
            "age": _als_int(roh.get("age")),
        })

    if not spieler:
        return None, (beanstandungen + ["Kader ohne verwertbare Spieler"])

    spieler.sort(key=lambda e: e["player_id"])

    return {
        "team_id": aufgeloeste_id,
        "team_name": team.get("name"),
        "player_count": len(spieler),
        "players": spieler,
        # Der Anbieter liefert zu diesem Endpunkt KEINE Zeitangabe -
        # nachgemessen. Der Vermerk steht in jedem Snapshot, damit ein
        # spaeterer Leser nicht danach suchen muss.
        "effective_at": None,
        "effective_at_status": EFFECTIVE_UNKNOWN_SQUAD,
    }, beanstandungen


# ---------------------------------------------------------------------------
# Verfuegbarkeitssnapshot
# ---------------------------------------------------------------------------

def normalise_availability(raw_response, league_id=None, season=None):
    """
    Die Anbieterantwort von /injuries in die Snapshotform.

    Rueckgabe: (payload, beanstandungen).

    ZEITSEMANTIK
    Jeder Eintrag bezieht sich auf EINE Partie und traegt deren Datum.
    Das ist ein echter Gueltigkeitszeitpunkt: "Spieler P fehlte bei
    Partie F am Datum D". effective_at wird deshalb aus fixture.date
    gefuellt - und nur daraus. Fehlt es, bleibt es None mit Vermerk.

    Die Eintraege werden nach (fixture_id, player_id) sortiert. Feste
    Ordnung, damit der Fingerabdruck nicht an der Anbieterreihenfolge
    haengt.
    """
    beanstandungen = []
    eintraege = raw_response if isinstance(raw_response, list) else []

    if not isinstance(raw_response, list):
        return None, ["unerwartete Antwortform"]

    ausfaelle = []
    gesehen = set()
    ohne_zeit = 0

    for roh in eintraege:
        if not isinstance(roh, dict):
            continue
        spieler = roh.get("player") or {}
        team = roh.get("team") or {}
        fixture = roh.get("fixture") or {}
        liga = roh.get("league") or {}

        pid = _als_int(spieler.get("id"))
        tid = _als_int(team.get("id"))
        fid = _als_int(fixture.get("id"))
        if pid is None or tid is None:
            beanstandungen.append("Eintrag ohne Spieler- oder Team-Kennung")
            continue

        schluessel = (fid, pid)
        if schluessel in gesehen:
            beanstandungen.append(
                f"doppelter Eintrag fuer Partie {fid}, Spieler {pid}")
            continue
        gesehen.add(schluessel)

        wirksam = fixture.get("date")
        if not wirksam:
            ohne_zeit += 1

        roher_grund = spieler.get("reason")
        ausfaelle.append({
            "player_id": pid,
            "player_name": spieler.get("name"),
            "team_id": tid,
            "team_name": team.get("name"),
            "fixture_id": fid,
            # Der von der QUELLE behauptete Gueltigkeitszeitpunkt.
            "effective_at": wirksam,
            "effective_at_status": (EFFECTIVE_FROM_SOURCE if wirksam
                                    else EFFECTIVE_UNKNOWN_MISSING),
            "status": normalise_availability_status(spieler.get("type")),
            "absence_category": normalise_absence_reason(roher_grund),
            # Rohwerte bleiben stehen: Jede Normalisierung ist eine
            # Interpretation, und wer sie spaeter anzweifelt, muss sie
            # nachrechnen koennen.
            "raw_type": spieler.get("type"),
            "raw_reason": roher_grund,
        })

    ausfaelle.sort(key=lambda e: (e["fixture_id"] or 0, e["player_id"]))

    from collections import Counter

    return {
        "league_id": _als_int(league_id),
        "season": _als_int(season),
        "entry_count": len(ausfaelle),
        "entries": ausfaelle,
        "teams_covered": sorted({e["team_id"] for e in ausfaelle}),
        "players_covered": len(({e["player_id"] for e in ausfaelle})),
        "by_status": dict(Counter(e["status"] for e in ausfaelle)),
        "by_absence_category": dict(Counter(e["absence_category"]
                                            for e in ausfaelle)),
        "entries_without_effective_at": ohne_zeit,
        "completeness_note": (
            "Der Anbieter meldet gemeldete Ausfaelle, nicht die "
            "vollstaendige Verfuegbarkeitslage. Ein Spieler ohne Eintrag "
            "ist NICHT belegt einsatzbereit - er ist nur nicht als "
            "Ausfall gemeldet. Rotationsentscheidungen und nicht "
            "gemeldete Blessuren fehlen."),
    }, beanstandungen


# ---------------------------------------------------------------------------
# Schluessel
# ---------------------------------------------------------------------------

def squad_key(team_id):
    """Archivschluessel eines Kadersnapshots."""
    return f"team_{int(team_id)}"


def availability_key(league_id, season):
    """Archivschluessel eines Verfuegbarkeitssnapshots."""
    return f"league_{int(league_id)}_season_{int(season)}"


def snapshot_meta(kind, endpoint, scope, quelle=SOURCE_APISPORTS):
    """
    Die Metadaten, die JEDER Snapshot traegt.

    scope beschreibt die Anfrage OHNE Geheimnisse - die Parameter, mit
    denen sie reproduzierbar ist, und nichts weiter. Ein Schluessel
    oder ein vollstaendiger Header haette hier nichts zu suchen und
    landete sonst dauerhaft im Archiv.
    """
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "endpoint": endpoint,
        "request_scope": dict(scope),
        "provider": quelle,
        "fetched_at_meaning": FETCHED_AT_MEANING,
    }
