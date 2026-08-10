"""
Point-in-Time-Schnitt fuer Features, Backtesting und spaeteres Training.

Das Problem
-----------
Ein Modell, das ein Spiel vom 1. Oktober vorhersagt, darf nichts wissen,
was erst am 2. Oktober passiert ist. Klingt selbstverstaendlich, passiert
aber beim Aufbau von Trainingsdaten fast zwangslaeufig: Man laedt "die
Saison" und rechnet Teamstaerken aus - inklusive der Spiele, die nach dem
Zielspiel lagen. Das Modell sieht im Training die Zukunft, wirkt dadurch
grossartig und faellt im Livebetrieb auseinander.

Dieses Modul stellt den Schnitt an genau einer Stelle bereit, statt ihn
in jedem Feature erneut (und irgendwann falsch) zu bauen.

Warum der Standard STRIKT ist
-----------------------------
Zwei Spiele am selben Tag: eins um 15:30, eins um 18:30. Fuer die
Vorhersage des Abendspiels ist das Nachmittagsergebnis bekannt. Nur:
Die historischen Dateien speichern lediglich das Datum, keine Uhrzeit
(data/historical/BL1_2024.json fuehrt "date": "2024-08-23"). Ob ein Spiel
desselben Tages vorher oder nachher stattfand, ist daraus NICHT
ableitbar.

Deshalb gilt: Bei gleichem Datum und fehlender Uhrzeit wird ein Spiel
ausgeschlossen. Lieber ein Feature, das etwas weniger weiss, als eines,
das heimlich zu viel weiss. Wo beide Seiten eine Uhrzeit tragen, wird sie
benutzt und der Schnitt entsprechend genauer.

Bewusst NICHT enthalten
-----------------------
Dieses Modul rechnet keine Features aus. Es beantwortet ausschliesslich
die Frage "welche Spiele waren zum Zeitpunkt T bekannt?". Was daraus
gebaut wird, gehoert woandershin - sonst waere der Schnitt wieder ueber
den Code verteilt.

Es ist ausserdem noch NICHT in den Live-Simulationspfad verdrahtet. Der
laeuft ohnehin gegen den aktuellen Stand, wo die Frage nicht auftritt.
Der Umbau dort waere Regressionsrisiko ohne heutigen Nutzen.
"""

from collections import defaultdict


# Feldnamen, unter denen die verschiedenen Quellen ihr Datum fuehren.
# Reihenfolge = Vorrang: das praezisere Feld zuerst.
_TIMESTAMP_FIELDS = ("utc_date", "utcDate")
_DATE_FIELDS = ("date",)


def match_date(match):
    """
    Das Kalenderdatum eines Spiels als 'YYYY-MM-DD', oder None.

    Versteht beide im Projekt vorkommenden Formate:
        historische Datei:  {"date": "2024-08-23"}
        Live-API:           {"utc_date": "2024-08-23T18:30:00Z"}
    """
    if not isinstance(match, dict):
        return None

    for field in _TIMESTAMP_FIELDS:
        value = match.get(field)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]

    for field in _DATE_FIELDS:
        value = match.get(field)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]

    return None


def match_time(match):
    """
    Die Uhrzeit eines Spiels als 'HH:MM:SS', oder None wenn die Quelle
    keine fuehrt (historische Dateien fuehren keine).
    """
    if not isinstance(match, dict):
        return None

    for field in _TIMESTAMP_FIELDS:
        value = match.get(field)
        if isinstance(value, str) and len(value) >= 19 and "T" in value:
            return value[11:19]

    return None


def _split_cutoff(cutoff):
    """
    Zerlegt eine Schnittangabe in (datum, uhrzeit_oder_None).

    Akzeptiert 'YYYY-MM-DD' und 'YYYY-MM-DDTHH:MM:SSZ'.
    """
    if cutoff is None:
        return None, None

    if hasattr(cutoff, "isoformat"):        # date oder datetime
        text = cutoff.isoformat()
    else:
        text = str(cutoff)

    if len(text) < 10:
        raise ValueError(f"Unbrauchbares Cutoff-Datum: {cutoff!r}")

    date_part = text[:10]
    time_part = text[11:19] if len(text) >= 19 and "T" in text else None

    return date_part, time_part


def is_known_at(match, cutoff, inclusive=False):
    """
    War dieses Spiel zum Zeitpunkt cutoff bereits gespielt?

    inclusive=False (Standard, leak-sicher):
        Nur Spiele VOR dem Stichtag. Ein Spiel am Stichtag selbst gilt
        als unbekannt, solange sich nicht ueber Uhrzeiten belegen laesst,
        dass es vorher angepfiffen wurde.

    inclusive=True:
        Spiele am Stichtag zaehlen mit. Sinnvoll fuer Aussagen wie
        "Stand nach dem 5. Spieltag", NICHT fuer Features eines Spiels,
        das an diesem Tag stattfindet.

    Spiele ohne verwertbares Datum gelten grundsaetzlich als unbekannt.
    Ein Datensatz, dessen Zeitpunkt sich nicht pruefen laesst, darf nicht
    stillschweigend in die Vergangenheit gerechnet werden.
    """
    cutoff_date, cutoff_time = _split_cutoff(cutoff)
    if cutoff_date is None:
        raise ValueError("cutoff ist erforderlich")

    played_date = match_date(match)
    if played_date is None:
        return False

    if played_date < cutoff_date:
        return True
    if played_date > cutoff_date:
        return False

    # Gleicher Tag: nur mit Uhrzeiten auf BEIDEN Seiten entscheidbar.
    played_time = match_time(match)
    if played_time is not None and cutoff_time is not None:
        return played_time < cutoff_time

    return bool(inclusive)


def matches_known_at(matches, cutoff, inclusive=False):
    """
    Filtert eine Spielliste auf das, was zum Stichtag bekannt war.

    Das ist die zentrale Funktion dieses Moduls. Jedes Feature, das
    spaeter fuer ein historisches Spiel berechnet wird, sollte seine
    Eingangsdaten hierdurch schicken.

    Die Reihenfolge der Eingabe bleibt erhalten.
    """
    if not matches:
        return []

    return [m for m in matches if is_known_at(m, cutoff, inclusive=inclusive)]


def matches_for_fixture(matches, fixture, exclude_fixture=True):
    """
    Die Spiele, die vor einer bestimmten Partie bekannt waren.

    Der uebliche Fall beim Aufbau von Trainingsdaten: fixture ist das
    Zielspiel, zurueck kommt alles, was davor lag.

    exclude_fixture entfernt das Zielspiel zusaetzlich anhand seiner ID,
    falls es in der Liste steckt. Ohne das koennte ein Spiel mit
    identischem Zeitstempel sich selbst als Feature sehen - der
    unmittelbarste denkbare Leak.
    """
    cutoff = None
    for field in _TIMESTAMP_FIELDS:
        value = fixture.get(field)
        if isinstance(value, str) and len(value) >= 10:
            cutoff = value
            break
    if cutoff is None:
        cutoff = match_date(fixture)

    if cutoff is None:
        raise ValueError("Zielspiel hat kein verwertbares Datum")

    known = matches_known_at(matches, cutoff, inclusive=False)

    if not exclude_fixture:
        return known

    fixture_id = fixture.get("match_id") or fixture.get("id")
    if fixture_id is None:
        return known

    return [
        m for m in known
        if (m.get("match_id") or m.get("id")) != fixture_id
    ]


def team_matches(matches, team_id):
    """Alle Spiele eines Teams, Heim wie Auswaerts, Reihenfolge erhalten."""
    return [
        m for m in matches
        if m.get("home_id") == team_id or m.get("away_id") == team_id
    ]


def sort_chronologically(matches):
    """
    Sortiert Spiele nach Zeitpunkt. Spiele ohne Datum wandern ans Ende,
    statt die Sortierung zu sprengen.
    """
    def key(match):
        date = match_date(match)
        time = match_time(match) or "00:00:00"
        return (date is None, date or "", time)

    return sorted(matches, key=key)


class PointInTime:
    """
    Ein benannter Datenschnitt: "Stand vom ... in Wettbewerb ...".

    Buendelt Stichtag und Kontext, damit beides zusammen durch den Code
    wandert und in der Provenienz eines Features landen kann. Ohne diese
    Klammer wird der Stichtag frueher oder spaeter irgendwo verloren -
    und dann faellt niemandem auf, dass ein Feature mehr wusste als
    erlaubt.
    """

    def __init__(self, cutoff, season=None, competition=None, matchday=None,
                 inclusive=False):
        self.cutoff_date, self.cutoff_time = _split_cutoff(cutoff)
        if self.cutoff_date is None:
            raise ValueError("cutoff ist erforderlich")

        self.cutoff = str(cutoff)
        self.season = season
        self.competition = competition
        self.matchday = matchday
        self.inclusive = inclusive

    @classmethod
    def for_fixture(cls, fixture, season=None, competition=None):
        """Schnitt unmittelbar vor einer konkreten Partie."""
        cutoff = None
        for field in _TIMESTAMP_FIELDS:
            value = fixture.get(field)
            if isinstance(value, str) and len(value) >= 10:
                cutoff = value
                break
        if cutoff is None:
            cutoff = match_date(fixture)
        if cutoff is None:
            raise ValueError("Zielspiel hat kein verwertbares Datum")

        return cls(
            cutoff,
            season=season,
            competition=competition,
            matchday=fixture.get("matchday"),
            inclusive=False,
        )

    def slice(self, matches):
        """Die zum Stichtag bekannten Spiele."""
        return matches_known_at(matches, self.cutoff, inclusive=self.inclusive)

    def matches_through_date(self, matches):
        """
        Das Datum des juengsten beruecksichtigten Spiels.

        Gehoert in die Provenienz eines Features: Es zeigt, worauf die
        Berechnung TATSAECHLICH beruhte, nicht nur, was erlaubt gewesen
        waere. Liegen zwischen letztem Spiel und Stichtag Wochen, ist das
        ein Hinweis auf eine Datenluecke.
        """
        known = self.slice(matches)
        dates = [match_date(m) for m in known]
        dates = [d for d in dates if d]
        return max(dates) if dates else None

    def provenance(self, matches=None):
        """
        Nachvollziehbarkeitsangaben zu diesem Schnitt.

        Bewusst ein schlichtes Dict: Es soll sich unveraendert in
        Feature-Ausgaben und spaeter in Trainingsdaten einbetten lassen.
        """
        info = {
            "cutoff": self.cutoff,
            "cutoff_date": self.cutoff_date,
            "inclusive": self.inclusive,
            "season": self.season,
            "competition": self.competition,
            "matchday": self.matchday,
        }

        if matches is not None:
            known = self.slice(matches)
            info["matches_used"] = len(known)
            info["matches_through_date"] = self.matches_through_date(matches)

        return info

    def __repr__(self):
        return (f"PointInTime(cutoff={self.cutoff!r}, season={self.season!r}, "
                f"competition={self.competition!r})")


def assert_no_future_data(matches, cutoff, inclusive=False):
    """
    Prueft, dass eine bereits geschnittene Liste keine Zukunft enthaelt.

    Gedacht als Zusicherung in Trainingspipelines: Nach jedem Schritt,
    der Daten zusammenfuehrt, laesst sich damit belegen, dass der Schnitt
    gehalten hat. Wirft ValueError mit den Fundstellen, statt still
    weiterzulaufen.
    """
    offenders = [
        m for m in (matches or [])
        if not is_known_at(m, cutoff, inclusive=inclusive)
    ]

    if offenders:
        preview = ", ".join(
            f"{match_date(m)}({m.get('home_id')}v{m.get('away_id')})"
            for m in offenders[:5]
        )
        raise ValueError(
            f"{len(offenders)} Spiel(e) liegen nach dem Stichtag {cutoff}: "
            f"{preview}"
        )

    return True


def group_by_team(matches):
    """
    Ordnet Spiele beiden beteiligten Teams zu.

    Rueckgabe: { team_id: [matches] }. Ein Spiel taucht bei beiden Teams
    auf - das ist beabsichtigt, denn es ist fuer beide ein Datenpunkt.
    """
    grouped = defaultdict(list)

    for match in matches or []:
        home = match.get("home_id")
        away = match.get("away_id")
        if home is not None:
            grouped[home].append(match)
        if away is not None:
            grouped[away].append(match)

    return dict(grouped)
