"""
Positionsgenaue Kaderverfuegbarkeit: wer fehlt, und was fehlt dadurch?

WAS SICH GEGENUEBER squad_impact.py AENDERT
-------------------------------------------
Das Vorgaengermodul bewertete ausschliesslich Torschuetzen und veraenderte
nur den Angriffswert. Sein eigener Modulkopf sagt das offen:

    "Erfasst werden nur Spieler, die in der Torschuetzenliste
     auftauchen, also im Wesentlichen die Offensive. Ausfaelle von
     Verteidigern oder Torhuetern bleiben unberuecksichtigt."

Damit war der Ausfall eines Stammtorwarts wirkungslos und der eines
Innenverteidigers ebenfalls. Dieses Modul ersetzt die Torschuetzenliste
durch Importance und Quality je Positionsgruppe und wirkt getrennt auf
Angriff und Abwehr.

squad_impact.py bleibt unveraendert bestehen. Es wird nicht ueberschrieben
und nicht abgeschaltet - GO 4 laeuft daneben und in der Voreinstellung im
Schattenmodus.

DIE POSITIONSGRUPPEN
--------------------
Mehr als vier gibt es nicht, weil der Anbieter nicht mehr liefert. Eine
Unterscheidung zwischen Innen- und Aussenverteidiger oder zwischen
Sechser und Zehner waere erfunden. Wo nur "Midfielder" steht, wird
"Midfielder" gerechnet.

DIE SOLLBESETZUNG
-----------------
Ohne aktuelle Aufstellung ist die tatsaechliche Formation unbekannt.
Statt eine zu raten, wird eine konservative Sollbesetzung angesetzt
(EXPECTED_STARTERS): 1 Torwart, 4 Verteidiger, 4 Mittelfeldspieler,
2 Angreifer. Das ist die haeufigste Grundordnung im europaeischen
Spitzenfussball und dient hier nur als NENNER - nicht als Behauptung,
dass ein Team so spielt.

PUNKT-IN-ZEIT: DIE HARTE GRENZE
-------------------------------
Beide Anbieter liefern Verletzungen ausschliesslich als Momentaufnahme.
Die Frage "wer fehlte am 12. November 2024?" ist rueckwirkend nicht
beantwortbar. Ein heutiger Abruf wuerde HEUTIGE Ausfaelle in ein
vergangenes Spiel setzen - das ist die Sorte Leck, die ein Modell
spaeter wertlos macht.

Deshalb gilt hier ohne Ausnahme: Ohne archivierten Stand am oder vor dem
Stichtag gibt es keine Verfuegbarkeitsaussage, sondern "unavailable".
Es wird nichts rekonstruiert und nichts angenommen.
"""

from src.features.player_quality import replacement_quality


#: Positionsgruppen in fester Reihenfolge.
POSITION_GROUPS = ("Goalkeeper", "Defender", "Midfielder", "Attacker")

#: Konservative Sollbesetzung je Position. Siehe Modulkopf.
EXPECTED_STARTERS = {
    "Goalkeeper": 1,
    "Defender": 4,
    "Midfielder": 4,
    "Attacker": 2,
}

#: Normalisierte Verfuegbarkeitszustaende.
#:
#:   out           sicher nicht dabei (Verletzung)
#:   suspended     gesperrt - ebenfalls sicher nicht dabei
#:   questionable  fraglich; der Anbieter fuehrt ihn, aber ohne Gewissheit
#:   available     spielt
#:   unknown       keine Angabe - NICHT dasselbe wie "available"
STATUSES = ("out", "suspended", "questionable", "available", "unknown")

#: Zustaende, die als sicherer Ausfall gelten.
DEFINITELY_OUT = frozenset({"out", "suspended"})

#: Wie stark ein fraglicher Spieler zaehlt.
#:
#: Nicht 1.0 und nicht 0.0: Die Mehrheit der als fraglich gemeldeten
#: Spieler laeuft am Ende auf, ein Teil aber nicht. Ein Drittel ist eine
#: bewusst vorsichtige Annahme - sie unterschaetzt den Ausfall lieber,
#: als eine Mannschaft wegen einer Meldung zu schwaechen, die sich als
#: folgenlos erweist. Der Wert ist ein Kalibrierungsparameter und steht
#: im Backtest zur Ueberpruefung.
QUESTIONABLE_WEIGHT = 1.0 / 3.0

#: Providerbegriffe, die einen sicheren Ausfall bezeichnen.
OUT_TOKENS = ("out", "injur", "missing fixture", "broken", "torn", "surgery",
              "rupture", "fracture")

#: Providerbegriffe fuer eine Sperre.
SUSPENDED_TOKENS = ("suspend", "red card", "ban")

#: Providerbegriffe fuer einen fraglichen Einsatz.
QUESTIONABLE_TOKENS = ("questionable", "doubt", "doubtful")

#: Wie stark ein Ausfall vom Ersatz aufgefangen wird, wenn KEIN
#: bewerteter Ersatz gefunden wird.
#:
#: Auch ohne Kenntnis des Ersatzmanns bleibt ein Teil der Leistung
#: erhalten - es tritt jemand an, und die Mannschaft besteht aus elf
#: Spielern. Der Vorgaengerwert (REPLACEMENT_FACTOR = 0.5 in
#: squad_impact.py) wird uebernommen, damit beide Modelle denselben
#: Grundgedanken teilen.
DEFAULT_REPLACEMENT_FACTOR = 0.5

#: Mindestminuten, damit ein Spieler als Ersatz zaehlt.
#:
#: Ohne diese Schwelle wuerde ein Ersatztorwart mit 90 Minuten und
#: zufaellig guter Paradenquote als gleichwertiger Ersatz gelten. Die
#: Frueh-Saison-Stabilisierung daempft solche Werte, hebt sie aber nicht
#: auf.
MIN_REPLACEMENT_MINUTES = 270

#: Obergrenze fuer den Verfuegbarkeitsverlust EINER Position.
#:
#: Auch wenn rechnerisch mehr herauskaeme: Eine Mannschaft, der die halbe
#: Abwehr fehlt, spielt nicht mit halber Abwehrstaerke. Es ruecken
#: Spieler nach, die Grundordnung bleibt bestehen.
MAX_POSITION_LOSS = 0.35


def normalize_status(raw_type=None, raw_reason=None):
    """
    Providerangabe auf einen der fuenf Zustaende abbilden.

    Zentral, damit nicht an drei Stellen unterschiedlich entschieden
    wird, was "Knock" bedeutet.

    Reihenfolge ist Absicht: Eine Sperre wird vor einer Verletzung
    geprueft, weil "suspended" haeufig zusaetzlich einen Grund traegt,
    der wie eine Verletzung klingt. Und "questionable" wird VOR den
    Ausfallbegriffen geprueft, weil "doubtful - injury" sonst als
    sicherer Ausfall gelesen wuerde.
    """
    text = " ".join(str(t).strip().lower()
                    for t in (raw_type, raw_reason) if t).strip()
    if not text:
        return "unknown"

    if any(token in text for token in SUSPENDED_TOKENS):
        return "suspended"
    if any(token in text for token in QUESTIONABLE_TOKENS):
        return "questionable"
    if any(token in text for token in OUT_TOKENS):
        return "out"
    return "unknown"


def status_weight(status):
    """
    Wie stark ein Zustand als Ausfall zaehlt.

    "unknown" ist ausdruecklich 0.0: Eine fehlende Angabe ist kein
    Ausfall. Wer sie als halben Ausfall behandelt, bestraft Teams
    dafuer, dass der Anbieter etwas nicht meldet.
    """
    if status in DEFINITELY_OUT:
        return 1.0
    if status == "questionable":
        return QUESTIONABLE_WEIGHT
    return 0.0


def normalize_absences(injury_entries, as_of=None):
    """
    Verletzungsmeldungen in einheitliche Ausfalleintraege.

    Rueckgabe: {player_id: {"status", "weight", "team_id", "reason",
                            "player_name", "as_of"}}

    Mehrfachmeldungen zu einem Spieler werden zum SCHWERSTEN Zustand
    zusammengefasst - wer sowohl als fraglich als auch als gesperrt
    gemeldet ist, fehlt sicher.
    """
    ergebnis = {}
    for eintrag in injury_entries or []:
        pid = eintrag.get("player_id")
        if pid is None:
            continue
        status = normalize_status(eintrag.get("type"), eintrag.get("reason"))
        gewicht = status_weight(status)
        if gewicht <= 0:
            continue

        pid = int(pid)
        vorhanden = ergebnis.get(pid)
        if vorhanden and vorhanden["weight"] >= gewicht:
            continue

        ergebnis[pid] = {
            "player_id": pid,
            "player_name": eintrag.get("player_name"),
            "team_id": eintrag.get("team_id"),
            "status": status,
            "weight": gewicht,
            "reason": eintrag.get("reason") or eintrag.get("type"),
            "as_of": as_of,
        }
    return ergebnis


def _position_players(team_player_ids, importance, quality, position):
    """Die Spieler eines Teams auf einer Position, mit ihren Kennzahlen."""
    spieler = []
    for pid in team_player_ids or []:
        pid = int(pid)
        imp = (importance or {}).get(pid) or {}
        qual = (quality or {}).get(pid) or {}
        gruppe = imp.get("position_group") or qual.get("position_group")
        if gruppe != position:
            continue
        spieler.append({
            "player_id": pid,
            "player_name": imp.get("player_name") or qual.get("player_name"),
            "importance": imp.get("player_importance"),
            "quality": qual.get("player_quality"),
            "minutes": imp.get("minutes") or qual.get("minutes") or 0,
        })
    return spieler


def position_availability(team_player_ids, importance, quality, absences,
                          position, replacement_factor=DEFAULT_REPLACEMENT_FACTOR):
    """
    Verfuegbarkeit einer Positionsgruppe.

    Rueckgabe enthaelt den Verlust (0 = vollstaendig verfuegbar) sowie
    alle Zwischengroessen, damit im Schattenmodus nachvollziehbar ist,
    woher er kommt.

    Der Verlust entsteht aus der Importance der Ausfaelle, gedaempft um
    die Qualitaet des besten verbleibenden Spielers derselben Position.
    Importance ist hier die richtige Groesse und nicht Quality: Es geht
    darum, wie viel Rolle wegfaellt, nicht wie gut der Fehlende war.
    """
    alle = _position_players(team_player_ids, importance, quality, position)
    if not alle:
        return {
            "position": position,
            "loss": 0.0,
            "available_count": 0,
            "out_count": 0,
            "out_players": [],
            "out_importance": 0.0,
            "out_quality": 0.0,
            "depth": None,
            "replacement_quality": None,
            "data_quality": "unavailable",
        }

    fehlend = []
    verfuegbar = []
    for spieler in alle:
        ausfall = (absences or {}).get(spieler["player_id"])
        if ausfall and ausfall["weight"] > 0:
            fehlend.append(dict(spieler, status=ausfall["status"],
                                weight=ausfall["weight"],
                                reason=ausfall.get("reason")))
        else:
            verfuegbar.append(spieler)

    # Ersatz: der beste verbleibende Spieler DERSELBEN Position, mit
    # genug Spielzeit, um bewertbar zu sein.
    ersatz = replacement_quality(
        quality, position,
        exclude_ids=[s["player_id"] for s in fehlend],
        min_minutes=MIN_REPLACEMENT_MINUTES)

    if ersatz is None:
        daempfung = replacement_factor
        ersatz_qualitaet = "unavailable"
    else:
        # Ein guter Ersatz faengt mehr auf. Der Faktor bleibt zwischen
        # dem Grundwert und 0.9 - "gleichwertig" gibt es nicht, sonst
        # waere der Ausfall folgenlos.
        daempfung = min(0.9, replacement_factor + ersatz * 0.5)
        ersatz_qualitaet = "complete"

    bekannte_importance = [s["importance"] for s in fehlend
                           if s["importance"] is not None]
    out_importance = sum(bekannte_importance)
    out_quality = sum(s["quality"] for s in fehlend if s["quality"] is not None)

    soll = EXPECTED_STARTERS.get(position, 1)
    gewichteter_ausfall = sum(
        (s["importance"] or 0.0) * s["weight"] for s in fehlend)

    # Bezug auf die Sollbesetzung: Faellt ein Angreifer von zwei
    # erwarteten aus, wiegt das schwerer als einer von vier
    # Mittelfeldspielern.
    roh_verlust = (gewichteter_ausfall / soll) * (1.0 - daempfung)
    verlust = max(0.0, min(MAX_POSITION_LOSS, roh_verlust))

    # Tiefe: bewertete verfuegbare Spieler gegen die Sollbesetzung.
    bewertet = [s for s in verfuegbar if s["quality"] is not None]
    tiefe = None
    if bewertet:
        beste = sorted((s["quality"] for s in bewertet), reverse=True)[:soll]
        tiefe = round(sum(beste) / soll, 4)

    if not fehlend:
        qualitaet = "complete"
    elif len(bekannte_importance) == len(fehlend):
        qualitaet = "complete" if ersatz is not None else "partial"
    elif bekannte_importance:
        qualitaet = "partial"
    else:
        # Ausfaelle bekannt, aber keiner davon bewertbar - dann ist der
        # Betrag des Verlusts nicht belegt.
        qualitaet = "fallback"

    return {
        "position": position,
        "loss": round(verlust, 6),
        "raw_loss": round(roh_verlust, 6),
        "clamped": roh_verlust > MAX_POSITION_LOSS,
        "available_count": len(verfuegbar),
        "out_count": len(fehlend),
        "out_players": [
            {"player_id": s["player_id"], "player_name": s["player_name"],
             "status": s["status"], "weight": round(s["weight"], 4),
             "importance": s["importance"], "quality": s["quality"]}
            for s in fehlend
        ],
        "out_importance": round(out_importance, 6),
        "out_quality": round(out_quality, 6),
        "expected_starters": soll,
        "depth": tiefe,
        "replacement_quality": ersatz,
        "replacement_damping": round(daempfung, 4),
        "data_quality": qualitaet,
    }


def team_availability(team_player_ids, importance, quality, absences,
                      as_of=None, snapshot_timestamp=None,
                      absences_known=True):
    """
    Verfuegbarkeit eines Teams ueber alle vier Positionsgruppen.

    absences_known: Ob fuer diesen Zeitpunkt ueberhaupt ein zulaessiger
        Ausfallstand vorliegt. Ist er False, gibt es KEINE Aussage -
        nicht "alle verfuegbar". Der Unterschied ist entscheidend: "wir
        wissen es nicht" darf nicht wie "niemand fehlt" wirken, sonst
        wuerde ein Team ohne Datenlage systematisch besser dastehen als
        eines mit gemeldeten Ausfaellen.

    Rueckgabe: alle geforderten Felder, inklusive availability_* je
    Bereich und overall_availability.
    """
    if not absences_known:
        return {
            "available": False,
            "reason": "no_absence_snapshot_for_cutoff",
            "as_of": as_of,
            "snapshot_timestamp": snapshot_timestamp,
            "availability_goalkeeper": None,
            "availability_defence": None,
            "availability_midfield": None,
            "availability_attack": None,
            "overall_availability": None,
            "positions": {},
            "data_quality": "unavailable",
        }

    je_position = {
        pos: position_availability(team_player_ids, importance, quality,
                                   absences, pos)
        for pos in POSITION_GROUPS
    }

    def verfuegbarkeit(pos):
        return round(1.0 - je_position[pos]["loss"], 6)

    klassen = [je_position[p]["data_quality"] for p in POSITION_GROUPS]
    rang = {"complete": 0, "partial": 1, "fallback": 2, "unavailable": 3}
    gesamt_qualitaet = max(klassen, key=lambda k: rang.get(k, 3))

    verluste = [je_position[p]["loss"] for p in POSITION_GROUPS]

    return {
        "available": True,
        "as_of": as_of,
        "snapshot_timestamp": snapshot_timestamp,
        "availability_goalkeeper": verfuegbarkeit("Goalkeeper"),
        "availability_defence": verfuegbarkeit("Defender"),
        "availability_midfield": verfuegbarkeit("Midfielder"),
        "availability_attack": verfuegbarkeit("Attacker"),
        # Gesamtwert als Mittel der vier Bereiche. Bewusst ungewichtet:
        # Eine Gewichtung waere eine Behauptung darueber, welcher
        # Mannschaftsteil wichtiger ist - und genau das soll der
        # Backtest zeigen, nicht eine Konstante vorwegnehmen.
        "overall_availability": round(1.0 - sum(verluste) / len(verluste), 6),
        "positions": je_position,
        "unavailable_players": [
            s for pos in POSITION_GROUPS
            for s in je_position[pos]["out_players"]
        ],
        "unavailable_importance": round(
            sum(je_position[p]["out_importance"] for p in POSITION_GROUPS), 6),
        "data_quality": gesamt_qualitaet,
        "clamp_applied": any(je_position[p]["clamped"] for p in POSITION_GROUPS),
    }


def group_pool_by_team(pool_players, as_of=None):
    """
    Spieler nach Vereinsnamen gruppieren - NUR fuer die aktuelle Saison.

    Der Spielerpool fuehrt den HEUTIGEN Verein (siehe
    player_identity-Modulkopf). Fuer die laufende Saison ist das genau
    richtig; rueckwirkend waere es ein Leck.

    Ist ein Stichtag gesetzt, wird deshalb nichts geliefert. Das ist
    keine Bequemlichkeit, sondern die Sperre selbst.
    """
    if as_of is not None:
        return {}

    nach_team = {}
    for spieler in pool_players or []:
        name = spieler.get("team_name")
        pid = spieler.get("player_id")
        if not name or pid is None:
            continue
        nach_team.setdefault(name, []).append(int(pid))
    return nach_team


def capture_availability_snapshot(competition_code, season=None, archive=True):
    """
    Haelt den AKTUELLEN Ausfallstand einer Liga zeitgestempelt fest.

    Es wird nichts rekonstruiert. Was heute nicht vorliegt, bleibt
    unbekannt - ab jetzt wird gesammelt. Genau derselbe Gedanke wie in
    squad_impact.capture_squad_snapshot(), nur mit den normalisierten
    Zustaenden dieses Moduls und mit Position statt Torschuetzenliste.

    Schreibt atomar ueber snapshot_archive und ueberschreibt keinen
    bestehenden Stand: Jeder Aufruf legt eine eigene Zeitmarke an.
    """
    from datetime import datetime, timezone

    from src.api.apisports_api import ApisportsUnavailable, get_injuries, resolve_season

    season = resolve_season(season)
    erfasst_am = datetime.now(timezone.utc)

    try:
        roh = get_injuries(competition_code, season=season)
    except ApisportsUnavailable as fehler:
        return {
            "competition": competition_code,
            "season": season,
            "captured_at": erfasst_am.isoformat(),
            "ok": False,
            "reason": str(fehler)[:200],
            "entries": 0,
            "archived_to": None,
        }

    ausfaelle = normalize_absences(roh, as_of=erfasst_am.isoformat())

    verteilung = {}
    for eintrag in ausfaelle.values():
        verteilung[eintrag["status"]] = verteilung.get(eintrag["status"], 0) + 1

    ergebnis = {
        "competition": competition_code,
        "season": season,
        "captured_at": erfasst_am.isoformat(),
        "ok": True,
        "entries": len(ausfaelle),
        "by_status": verteilung,
        "absences": {str(k): v for k, v in ausfaelle.items()},
        "schema_version": 1,
        "source": "api-football.com/injuries",
        "archived_to": None,
    }

    # Ein leerer Stand wird NICHT archiviert. Er waere von "keine
    # Ausfaelle" nicht zu unterscheiden und wuerde bei der spaeteren
    # Suche nach dem naechstgelegenen Stand einen guten verdraengen.
    if archive and ausfaelle:
        from src.data.snapshot_archive import archive_snapshot

        ergebnis["archived_to"] = archive_snapshot(
            kind="availability",
            key=f"{competition_code}_{season}",
            payload=ergebnis,
            source="api-football.com",
            captured_at=erfasst_am,
        )

    return ergebnis


def load_availability_snapshot(competition_code, season, as_of):
    """
    Der zuletzt vor dem Stichtag erfasste Ausfallstand.

    Rueckgabe: (absences, snapshot_timestamp) oder (None, None).

    Ein None ist die richtige Antwort und kein Fehler: Fuer die
    allermeisten historischen Zeitpunkte gibt es keinen Stand, weil vor
    GO 4 keiner gesammelt wurde. Der Aufrufer behandelt das als
    "unbekannt" und bleibt neutral.
    """
    from src.data.snapshot_archive import snapshot_as_of

    eintrag = snapshot_as_of("availability", as_of,
                             key=f"{competition_code}_{season}")
    if not eintrag:
        return None, None

    nutzlast = eintrag.get("payload") or {}
    roh = nutzlast.get("absences") or {}
    ausfaelle = {}
    for pid, wert in roh.items():
        try:
            ausfaelle[int(pid)] = wert
        except (TypeError, ValueError):
            continue

    return ausfaelle, nutzlast.get("captured_at")


def availability_coverage():
    """Welche Ausfallstaende liegen im Archiv? Fuer den Bericht."""
    from src.data.snapshot_archive import archive_coverage

    try:
        return archive_coverage("availability")
    except Exception:
        return {"kind": "availability", "snapshots": 0, "keys": []}
