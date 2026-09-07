"""
Der Sammler fuer Kader- und Verfuegbarkeitsmomentaufnahmen (V2-C6).

WAS HIER PASSIERT
-----------------
Planung, Netzzugriff mit Wiederholungen, Quotenwache, Sperre gegen
Doppellaeufe, Ablage ueber das bestehende Archiv und ein Laufbericht.
Die fachliche FORM der Snapshots steht in availability_snapshots.py,
die Ablage in snapshot_archive.py.

NICHT IM WEBPROZESS
-------------------
Dieser Sammler laeuft ausschliesslich als eigener Prozess ueber
collect_snapshots.py. Ihn an Gunicorn zu haengen waere aus zwei
Gruenden falsch: Mehrere Worker starteten ihn mehrfach, und ein
Neustart des Webdienstes loeste eine ungeplante Sammlung aus. Die
Sperre unten faengt das ab, aber sie ist die zweite Verteidigungslinie,
nicht die erste.

KEIN ZWEITER API-CLIENT
-----------------------
Adresse, Kopfzeilen und Fehlerklassen kommen unveraendert aus
src/api/apisports_api.py. Was hier dazukommt, ist das, was der
bestehende Client nicht tut und fuer einen Livepfad auch nicht tun
muss: Wiederholungen mit Backoff, Retry-After, das Auslesen der
Kontingentkopfzeilen und ein kontrolliertes Anhalten davor. Der
bestehende Client bleibt unberuehrt - ein Umbau haette jeden
Livepfad betroffen.
"""

import json
import os
import random
import time
from datetime import datetime, timedelta, timezone

from src.data import availability_snapshots as av
from src.data import snapshot_archive as archive

#: Fassung des Laufberichts.
RUN_REPORT_VERSION = 1

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Wo Sperre und Laufberichte liegen. Neben dem Archiv, nicht darin -
#: ein Bericht ist kein Snapshot und soll die Archivzaehlung nicht
#: verfaelschen.
RUN_DIR = os.path.join(_PROJECT_ROOT, "data", "snapshots", "_runs")
LOCK_PATH = os.path.join(_PROJECT_ROOT, "data", "snapshots", "collector.lock")

#: Wie lange eine Sperre gelten darf, bevor sie als verwaist gilt.
#:
#: Ein vollstaendiger Tageslauf dauert bei rund 400 Mannschaften und
#: einer Sekunde Abstand deutlich unter einer Stunde. Drei Stunden
#: lassen genug Luft fuer Wiederholungen und einen langsamen Anbieter,
#: ohne dass ein abgestuerzter Lauf den naechsten Tag blockiert.
STALE_LOCK_SECONDS = 3 * 60 * 60

#: Netzwerkverhalten.
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0

#: Abstand zwischen zwei Anfragen. Der Anbieter erlaubt 300 je Minute
#: (nachgemessen an x-ratelimit-limit); 0,25 s halten mit Abstand
#: darunter und machen einen Minutenlimit-Treffer unwahrscheinlich.
REQUEST_SPACING_SECONDS = 0.25

#: Ab wie vielen verbleibenden Tagesanfragen der Lauf kontrolliert
#: endet. Nicht null: Der uebrige Betrieb (Livesuche, Spielerprofile)
#: braucht Luft, und ein Sammler, der die Quote leerraeumt, legt die
#: Anwendung lahm.
QUOTA_SAFETY_MARGIN = 500

#: Statuswerte eines Laufs.
RUN_COMPLETE = "complete"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"

#: Ergebnis je Scope.
OUTCOME_STORED = "stored"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_EMPTY = "empty"
OUTCOME_FAILED = "failed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_DRY_RUN = "dry_run"


def _utc_now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------

class CollectorBusy(RuntimeError):
    """Ein anderer Sammellauf haelt die Sperre."""


class CollectorLock:
    """
    Eine Dateisperre, die auf Windows und Linux gleich funktioniert.

    WARUM O_CREAT|O_EXCL UND NICHT fcntl/msvcrt
    Die beiden Betriebssysteme haben keine gemeinsame Sperr-API:
    fcntl.flock gibt es unter Windows nicht, msvcrt.locking nicht unter
    Linux. Das Anlegen einer Datei mit O_EXCL ist dagegen auf beiden
    atomar - das Betriebssystem garantiert, dass genau ein Prozess
    gewinnt. Die lokale Entwicklung laeuft unter Windows, der VPS unter
    Ubuntu; eine Sperre, die nur auf einem von beiden greift, waere
    genau dort nutzlos, wo sie gebraucht wird.

    VERWAISTE SPERREN
    Ein abgestuerzter Lauf hinterlaesst seine Datei. Sie wird uebernommen,
    wenn sie aelter als STALE_LOCK_SECONDS ist UND der eingetragene
    Prozess nachweislich nicht mehr laeuft. Beides zusammen - eine
    Sperre nur nach Alter zu brechen wuerde einen langsamen, aber
    lebenden Lauf abschiessen.
    """

    def __init__(self, path=None, stale_seconds=None):
        # BEWUSST None statt LOCK_PATH als Vorgabewert: Ein
        # Vorgabeargument wird EINMAL beim Import ausgewertet. Stuende
        # hier LOCK_PATH, liesse sich der Pfad danach nicht mehr
        # aendern - ein Test, der ihn umlenkt, wuerde stillschweigend
        # weiter die echte Sperre benutzen, und zwei angeblich
        # getrennte Laeufe teilten sich eine Datei.
        self.path = path if path is not None else LOCK_PATH
        self.stale_seconds = (stale_seconds if stale_seconds is not None
                              else STALE_LOCK_SECONDS)
        self.acquired = False
        self.takeover = None

    # -- Hilfen ----------------------------------------------------------

    def read(self):
        """Der Inhalt der Sperre - oder None."""
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _process_alive(pid):
        """
        Laeuft dieser Prozess noch?

        Rueckgabe None, wenn es sich nicht entscheiden laesst - dann
        gilt die Sperre als lebend. Im Zweifel NICHT uebernehmen: Zwei
        gleichzeitige Sammellaeufe sind schlimmer als ein blockierter.
        """
        if not pid:
            return None
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return None

        if os.name == "nt":                              # pragma: no cover
            try:
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(
                    0x1000, False, pid)
                if not handle:
                    return False
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            except Exception:
                return None
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:                                  # pragma: no cover
            return None

    def stale_state(self, now=None):
        """
        (ist_verwaist, begruendung) fuer eine vorhandene Sperre.
        """
        inhalt = self.read()
        if inhalt is None:
            # Unlesbar oder halb geschrieben. Das Alter der DATEI
            # entscheidet - eine kaputte Sperre darf nicht ewig blocken.
            try:
                alter = (now or _utc_now()).timestamp() \
                    - os.path.getmtime(self.path)
            except OSError:
                return True, "Sperrdatei verschwunden"
            if alter > self.stale_seconds:
                return True, f"unlesbare Sperre, {int(alter)} s alt"
            return False, "unlesbare Sperre, aber frisch"

        gestartet = inhalt.get("started_at")
        try:
            beginn = datetime.fromisoformat(gestartet)
        except (TypeError, ValueError):
            beginn = None

        alter = None
        if beginn is not None:
            if beginn.tzinfo is None:
                beginn = beginn.replace(tzinfo=timezone.utc)
            alter = ((now or _utc_now()) - beginn).total_seconds()

        lebt = self._process_alive(inhalt.get("pid"))
        if lebt:
            return False, (f"Prozess {inhalt.get('pid')} laeuft noch"
                           + (f", seit {int(alter)} s" if alter else ""))
        if alter is None:
            return False, "Startzeit unlesbar - im Zweifel nicht uebernehmen"
        if alter <= self.stale_seconds:
            return False, (f"Sperre erst {int(alter)} s alt - Grenze liegt "
                           f"bei {self.stale_seconds} s")
        return True, (f"Prozess {inhalt.get('pid')} laeuft nicht mehr und "
                      f"die Sperre ist {int(alter)} s alt")

    # -- Kontextmanager --------------------------------------------------

    def acquire(self, now=None):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        inhalt = json.dumps({
            "pid": os.getpid(),
            "started_at": (now or _utc_now()).isoformat(),
            "host": os.environ.get("HOSTNAME") or os.environ.get(
                "COMPUTERNAME") or "unknown",
            "collector_version": av.COLLECTOR_VERSION,
        }).encode("utf-8")

        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            verwaist, grund = self.stale_state(now=now)
            if not verwaist:
                raise CollectorBusy(
                    f"ein Sammellauf laeuft bereits: {grund}")
            # Uebernahme: erst entfernen, dann NEU und wieder exklusiv
            # anlegen. Ein blosses Ueberschreiben waere nicht atomar -
            # zwei Prozesse koennten die verwaiste Sperre gleichzeitig
            # fuer sich beanspruchen.
            self.takeover = grund
            try:
                os.remove(self.path)
            except OSError:                              # pragma: no cover
                pass
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:                      # pragma: no cover
                raise CollectorBusy(
                    "ein anderer Prozess war beim Uebernehmen schneller")

        with os.fdopen(fd, "wb") as handle:
            handle.write(inhalt)
        self.acquired = True
        return self

    def release(self):
        if not self.acquired:
            return
        try:
            os.remove(self.path)
        except OSError:                                  # pragma: no cover
            pass
        self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
        return False


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

#: Kopfzeilen des Anbieters, die das Kontingent beschreiben.
#: Nachgemessen am 06.09.2026 - der bestehende Client verwirft sie.
QUOTA_HEADERS = ("x-ratelimit-requests-limit",
                 "x-ratelimit-requests-remaining",
                 "x-ratelimit-limit", "x-ratelimit-remaining")


class TransportResult:
    """Antwort einer Anfrage samt allem, was der Bericht braucht."""

    def __init__(self, ok, payload=None, error=None, status_code=None,
                 attempts=1, quota=None, retried=0):
        self.ok = ok
        self.payload = payload
        self.error = error
        self.status_code = status_code
        self.attempts = attempts
        self.quota = quota or {}
        self.retried = retried


def parse_quota(headers):
    """
    Die Kontingentangaben aus den Kopfzeilen.

    Nur die vier bekannten Namen, klein geschrieben verglichen. Alles
    andere wird nicht angefasst - eine Kopfzeile mit dem Schluessel
    darf niemals in einen Bericht geraten.
    """
    if not headers:
        return {}
    klein = {str(k).lower(): v for k, v in headers.items()}
    werte = {}
    for name in QUOTA_HEADERS:
        if name in klein:
            try:
                werte[name] = int(klein[name])
            except (TypeError, ValueError):
                werte[name] = None
    return werte


def _sleep(seconds):                                     # pragma: no cover
    time.sleep(seconds)


def request_with_retry(endpoint, params, session=None, max_retries=MAX_RETRIES,
                       timeout=REQUEST_TIMEOUT_SECONDS, sleeper=None,
                       rng=None):
    """
    Eine Anfrage mit kontrollierten Wiederholungen.

    WANN WIEDERHOLT WIRD
      - Netzwerkfehler und Zeitueberschreitung
      - HTTP 429 (Rate Limit) und 5xx

    WANN NICHT
      - jeder andere 4xx. Ein 404 wird beim zweiten Versuch nicht zu
        einem 200, und ein 401 schon gar nicht - Wiederholungen
        verbrauchen dort nur Kontingent.

    Retry-After wird beachtet, wenn der Anbieter ihn schickt; sonst
    gilt exponentielles Backoff mit Jitter. Der Jitter ist kein
    Schmuck: Ohne ihn laufen mehrere wiederholende Anfragen im
    Gleichtakt und treffen dieselbe Grenze erneut gemeinsam.
    """
    import requests

    from src.api.apisports_api import BASE_URL, _headers

    sleeper = sleeper or _sleep
    rng = rng or random.Random(0)
    session = session or requests

    url = f"{BASE_URL}/{endpoint}"
    letzte_quota = {}
    versuch = 0
    wiederholt = 0

    while True:
        versuch += 1
        try:
            antwort = session.get(url, headers=_headers(), params=params,
                                  timeout=timeout)
        except Exception as fehler:
            # Der Text einer Netzwerkausnahme kann die URL enthalten,
            # aber niemals die Kopfzeilen - der Schluessel steckt dort.
            if versuch > max_retries:
                return TransportResult(
                    False, error=f"Netzwerkfehler: {type(fehler).__name__}",
                    attempts=versuch, quota=letzte_quota, retried=wiederholt)
            wiederholt += 1
            sleeper(_backoff(versuch, rng))
            continue

        letzte_quota = parse_quota(getattr(antwort, "headers", {}))
        code = getattr(antwort, "status_code", None)

        if code == 200:
            try:
                daten = antwort.json()
            except ValueError:
                return TransportResult(
                    False, error="Antwort ist kein JSON", status_code=code,
                    attempts=versuch, quota=letzte_quota, retried=wiederholt)

            fehlerblock = daten.get("errors") or {}
            if fehlerblock:
                # API-Sports meldet auch Kontingentfehler mit HTTP 200.
                if isinstance(fehlerblock, dict) and (
                        "requests" in fehlerblock or "rateLimit" in fehlerblock):
                    if versuch > max_retries:
                        return TransportResult(
                            False, error="Kontingent erschoepft",
                            status_code=code, attempts=versuch,
                            quota=letzte_quota, retried=wiederholt)
                    wiederholt += 1
                    sleeper(_backoff(versuch, rng))
                    continue
                return TransportResult(
                    False, error=f"Anbieterfehler: {fehlerblock}",
                    status_code=code, attempts=versuch, quota=letzte_quota,
                    retried=wiederholt)

            return TransportResult(True, payload=daten, status_code=code,
                                   attempts=versuch, quota=letzte_quota,
                                   retried=wiederholt)

        if code == 429 or (code is not None and 500 <= code < 600):
            if versuch > max_retries:
                return TransportResult(
                    False, error=f"HTTP {code} nach {versuch} Versuchen",
                    status_code=code, attempts=versuch, quota=letzte_quota,
                    retried=wiederholt)
            wiederholt += 1
            sleeper(_retry_after(antwort) or _backoff(versuch, rng))
            continue

        # Dauerhafter Fehler - keine Wiederholung.
        return TransportResult(False, error=f"HTTP {code}", status_code=code,
                               attempts=versuch, quota=letzte_quota,
                               retried=wiederholt)


def _retry_after(antwort):
    """Die vom Anbieter gewuenschte Wartezeit - oder None."""
    kopf = getattr(antwort, "headers", {}) or {}
    klein = {str(k).lower(): v for k, v in kopf.items()}
    wert = klein.get("retry-after")
    if wert is None:
        return None
    try:
        sekunden = float(wert)
    except (TypeError, ValueError):
        return None
    # Nach oben begrenzt: Ein Anbieter, der eine Stunde verlangt, soll
    # den Lauf beenden und nicht blockieren.
    return max(0.0, min(sekunden, BACKOFF_MAX_SECONDS))


def _backoff(versuch, rng):
    """Exponentiell mit Jitter, nach oben begrenzt."""
    roh = min(BACKOFF_BASE_SECONDS * (2 ** (versuch - 1)), BACKOFF_MAX_SECONDS)
    return roh * (0.5 + rng.random() * 0.5)


# ---------------------------------------------------------------------------
# Planung
# ---------------------------------------------------------------------------

class Scope:
    """Eine geplante Einheit Arbeit."""

    def __init__(self, kind, endpoint, params, key, label, priority=100):
        self.kind = kind
        self.endpoint = endpoint
        self.params = dict(params)
        self.key = key
        self.label = label
        self.priority = priority

    def identity(self):
        """
        Was diesen Scope eindeutig macht.

        Ueber diesen Wert wird dedupliziert: Eine Mannschaft, die in
        der Bundesliga UND in der Champions League spielt, steht in
        beiden Teamlisten - abgefragt wird sie trotzdem nur einmal.
        """
        return (self.kind, self.endpoint,
                tuple(sorted((k, str(v)) for k, v in self.params.items())))

    def as_dict(self):
        return {"kind": self.kind, "endpoint": self.endpoint,
                "params": dict(self.params), "key": self.key,
                "label": self.label, "priority": self.priority}


def plan_scopes(teams, leagues, season, kinds=av.SNAPSHOT_KINDS):
    """
    Der Sammelplan - dedupliziert und nach Vorrang sortiert.

    teams:   Liste von {"team_id", "label", "priority"}
    leagues: Liste von {"league_id", "label", "priority"}

    VORRANG BEI KNAPPEM KONTINGENT
    Verfuegbarkeit zuerst: Eine Ligaabfrage liefert die Ausfaelle einer
    ganzen Saison in EINER Anfrage (nachgemessen: 2832 Eintraege fuer
    die Bundesliga), waehrend ein Kader eine Anfrage je Mannschaft
    kostet. Bricht der Lauf ab, ist der wertvollere Teil bereits
    gesichert.

    Innerhalb einer Art entscheidet die uebergebene Prioritaet, dann
    der Bezeichner - damit zwei Laeufe dieselbe Reihenfolge ergeben.
    """
    geplant = []

    if av.KIND_AVAILABILITY in kinds:
        for liga in leagues:
            lid = int(liga["league_id"])
            geplant.append(Scope(
                kind=av.KIND_AVAILABILITY,
                endpoint=av.ENDPOINT_INJURIES,
                params={"league": lid, "season": int(season)},
                key=av.availability_key(lid, season),
                label=liga.get("label") or f"league {lid}",
                priority=int(liga.get("priority", 10)),
            ))

    if av.KIND_SQUAD in kinds:
        for team in teams:
            tid = int(team["team_id"])
            geplant.append(Scope(
                kind=av.KIND_SQUAD,
                endpoint=av.ENDPOINT_SQUAD,
                params={"team": tid},
                key=av.squad_key(tid),
                label=team.get("label") or f"team {tid}",
                priority=int(team.get("priority", 100)),
            ))

    eindeutig = {}
    for scope in geplant:
        vorhanden = eindeutig.get(scope.identity())
        if vorhanden is None or scope.priority < vorhanden.priority:
            eindeutig[scope.identity()] = scope

    return sorted(eindeutig.values(),
                  key=lambda s: (s.priority, s.kind, s.label, s.key))


def plan_fingerprint(scopes):
    """
    Ein Fingerabdruck der Planung.

    Er beantwortet spaeter die Frage, ob zwei Laeufe ueberhaupt
    dasselbe vorhatten - ohne ihn liesse sich ein Coverage-Unterschied
    nicht von einem Planungsunterschied trennen.
    """
    return archive.content_fingerprint([s.as_dict() for s in scopes])


# ---------------------------------------------------------------------------
# Sammeln
# ---------------------------------------------------------------------------

def _normalise(scope, roh):
    """Die Rohantwort in die Snapshotform - je nach Art."""
    antwort = roh.get("response") if isinstance(roh, dict) else None
    if scope.kind == av.KIND_SQUAD:
        return av.normalise_squad(antwort, team_id=scope.params.get("team"))
    if scope.kind == av.KIND_AVAILABILITY:
        return av.normalise_availability(
            antwort, league_id=scope.params.get("league"),
            season=scope.params.get("season"))
    return None, [f"unbekannte Snapshotart: {scope.kind}"]


def _paging(roh):
    seiten = (roh or {}).get("paging") or {}
    try:
        return int(seiten.get("current") or 1), int(seiten.get("total") or 1)
    except (TypeError, ValueError):                      # pragma: no cover
        return 1, 1


def collect_scope(scope, transport=None, dry_run=False, archive_module=None,
                  now=None, max_pages=20):
    """
    Ein einzelner Scope: abrufen, normalisieren, ablegen.

    Rueckgabe: dict mit outcome, requests, retries und Diagnose.

    PAGINATION
    Beide C6-Endpunkte liefern derzeit alles auf einer Seite
    (nachgemessen: paging.total = 1, auch bei 2832 Eintraegen). Der
    Code arbeitet trotzdem alle Seiten ab - eine Antwort, die morgen
    umbricht, wuerde sonst stillschweigend abgeschnitten. max_pages
    begrenzt das nach oben, damit ein fehlerhaftes paging keinen
    Endlosverbrauch ausloest.

    LEER IST NICHT KAPUTT
    Eine leere Antwort (results = 0, keine Fehler) ist ein gueltiger
    Zustand - eine Liga ohne gemeldete Ausfaelle etwa. Sie wird als
    OUTCOME_EMPTY gefuehrt und NICHT als Fehler. Beides zu vermengen
    waere der sicherste Weg, eine echte Stoerung zu uebersehen.
    """
    transport = transport or request_with_retry
    archive_module = archive_module or archive
    jetzt = now or _utc_now()

    ergebnis = {
        "scope": scope.as_dict(),
        "requests": 0,
        "retries": 0,
        "pages": 0,
        "quota": {},
        "errors": [],
        "notes": [],
    }

    gesammelt = []
    seite = 1
    gesamt_seiten = 1

    while seite <= gesamt_seiten and seite <= max_pages:
        params = dict(scope.params)
        if seite > 1:
            params["page"] = seite

        antwort = transport(scope.endpoint, params)
        ergebnis["requests"] += 1
        ergebnis["retries"] += getattr(antwort, "retried", 0)
        if getattr(antwort, "quota", None):
            ergebnis["quota"] = antwort.quota

        if not antwort.ok:
            ergebnis["outcome"] = OUTCOME_FAILED
            ergebnis["errors"].append(antwort.error)
            return ergebnis

        teil = (antwort.payload or {}).get("response")
        if isinstance(teil, list):
            gesammelt.extend(teil)
        aktuell, gesamt_seiten = _paging(antwort.payload)
        ergebnis["pages"] += 1
        seite = max(seite + 1, aktuell + 1)

    if gesamt_seiten > max_pages:
        ergebnis["notes"].append(
            f"Pagination bei {max_pages} Seiten begrenzt "
            f"(Anbieter meldet {gesamt_seiten})")

    if not gesammelt:
        ergebnis["outcome"] = OUTCOME_EMPTY
        ergebnis["notes"].append("Anbieter lieferte keine Eintraege")
        return ergebnis

    payload, beanstandungen = _normalise(scope, {"response": gesammelt})
    ergebnis["notes"].extend(beanstandungen or [])

    if payload is None:
        ergebnis["outcome"] = OUTCOME_EMPTY
        return ergebnis

    fingerabdruck = archive_module.content_fingerprint(payload)
    ergebnis["content_fingerprint"] = fingerabdruck

    vorher = archive_module.latest_fingerprint(scope.kind, scope.key)
    if vorher == fingerabdruck:
        ergebnis["outcome"] = OUTCOME_UNCHANGED
        return ergebnis

    if dry_run:
        ergebnis["outcome"] = OUTCOME_DRY_RUN
        return ergebnis

    meta = av.snapshot_meta(scope.kind, scope.endpoint, scope.params)
    meta["content_fingerprint"] = fingerabdruck
    meta["fetched_at"] = jetzt.isoformat()
    if beanstandungen:
        meta["quality_notes"] = list(beanstandungen)

    pfad = archive_module.archive_snapshot(
        scope.kind, scope.key, payload, source=av.SOURCE_APISPORTS,
        extra_meta=meta, captured_at=jetzt)

    ergebnis["outcome"] = OUTCOME_STORED
    ergebnis["path"] = os.path.basename(pfad)
    return ergebnis


def _quota_remaining(quota):
    return (quota or {}).get("x-ratelimit-requests-remaining")


def run_collection(scopes, transport=None, dry_run=False, limit=None,
                   quota_margin=QUOTA_SAFETY_MARGIN, archive_module=None,
                   now=None, spacing=0.0, sleeper=None, already_done=None):
    """
    Der vollstaendige Lauf ueber alle geplanten Scopes.

    limit:        hoechstens so viele Scopes bearbeiten (Probemodus)
    quota_margin: kontrolliert anhalten, bevor so wenige Tagesanfragen
                  uebrig sind
    already_done: Identitaeten bereits erledigter Scopes - damit ein
                  abgebrochener Lauf fortgesetzt werden kann, ohne
                  Kontingent fuer bereits Gesammeltes auszugeben

    TEILERFOLG BLEIBT ERHALTEN
    Ein fehlgeschlagener Scope beendet den Lauf NICHT. Jeder Snapshot
    wird einzeln geschrieben, sobald er vorliegt; ein Abbruch danach
    kann ihn nicht mehr zuruecknehmen. Genau deshalb wird auch nicht
    erst am Ende gespeichert.
    """
    sleeper = sleeper or _sleep
    begonnen = now or _utc_now()
    erledigt = set(already_done or ())

    ergebnisse = []
    uebersprungen = []
    beobachtete_quota = {}
    angehalten = None

    for index, scope in enumerate(scopes):
        if limit is not None and len(ergebnisse) >= limit:
            uebersprungen.append({"scope": scope.as_dict(),
                                  "reason": f"Probemodus: Grenze {limit}"})
            continue

        if scope.identity() in erledigt:
            uebersprungen.append({"scope": scope.as_dict(),
                                  "reason": "in diesem Lauf bereits erledigt"})
            continue

        uebrig = _quota_remaining(beobachtete_quota)
        if uebrig is not None and uebrig <= quota_margin:
            angehalten = (f"Kontingentgrenze erreicht: noch {uebrig} "
                          f"Tagesanfragen, Sicherheitsabstand "
                          f"{quota_margin}")
            uebersprungen.append({"scope": scope.as_dict(),
                                  "reason": angehalten})
            continue

        if index and spacing:
            sleeper(spacing)

        ergebnis = collect_scope(scope, transport=transport, dry_run=dry_run,
                                 archive_module=archive_module, now=now)
        if ergebnis.get("quota"):
            beobachtete_quota = ergebnis["quota"]
        ergebnisse.append(ergebnis)
        erledigt.add(scope.identity())

    return build_report(scopes, ergebnisse, uebersprungen, begonnen,
                        beobachtete_quota, dry_run=dry_run, limit=limit,
                        halted=angehalten, now=now)


# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------

def build_report(scopes, ergebnisse, uebersprungen, begonnen, quota,
                 dry_run=False, limit=None, halted=None, now=None):
    """
    Der maschinenlesbare Laufbericht.

    DIE STATUSREGEL, AUSDRUECKLICH
        complete  jeder geplante Scope wurde bearbeitet und keiner ist
                  fehlgeschlagen
        partial   etwas wurde gesammelt, aber nicht alles - ein
                  fehlgeschlagener Scope, ein Kontingentstopp, eine
                  Probegrenze
        failed    nichts Verwertbares - kein einziger Scope erfolgreich,
                  obwohl welche geplant waren

    Ein Lauf mit Exit-Code 0 darf keinen unvollstaendigen Lauf als
    vollstaendig ausgeben; genau dafuer gibt es die drei Werte und die
    Zuordnung zu Exit-Codes in collect_snapshots.py.
    """
    from collections import Counter

    beendet = now or _utc_now()
    nach_ergebnis = Counter(e.get("outcome") for e in ergebnisse)
    fehlgeschlagen = [e for e in ergebnisse if e.get("outcome") == OUTCOME_FAILED]
    erfolgreich = [e for e in ergebnisse
                   if e.get("outcome") in (OUTCOME_STORED, OUTCOME_UNCHANGED,
                                           OUTCOME_EMPTY, OUTCOME_DRY_RUN)]

    if not scopes:
        status = RUN_COMPLETE
    elif erfolgreich and not fehlgeschlagen and not uebersprungen:
        status = RUN_COMPLETE
    elif erfolgreich:
        status = RUN_PARTIAL
    else:
        status = RUN_FAILED

    nach_endpunkt = Counter()
    for e in ergebnisse:
        nach_endpunkt[(e["scope"]["endpoint"], e.get("outcome"))] += 1

    return {
        "run_report_version": RUN_REPORT_VERSION,
        "collector_version": av.COLLECTOR_VERSION,
        "snapshot_schema_version": av.SNAPSHOT_SCHEMA_VERSION,
        "started_at": begonnen.isoformat(),
        "finished_at": beendet.isoformat(),
        "duration_seconds": round((beendet - begonnen).total_seconds(), 3),
        "status": status,
        "dry_run": bool(dry_run),
        "limit": limit,
        "halted_reason": halted,
        "planned_scopes": len(scopes),
        "attempted_scopes": len(ergebnisse),
        "skipped_scopes": len(uebersprungen),
        "plan_fingerprint": plan_fingerprint(scopes),
        "outcomes": dict(nach_ergebnis),
        "requests_attempted": sum(e.get("requests", 0) for e in ergebnisse),
        "requests_retried": sum(e.get("retries", 0) for e in ergebnisse),
        "requests_by_endpoint_and_outcome": {
            f"{endpunkt}:{ergebnis}": n
            for (endpunkt, ergebnis), n in sorted(nach_endpunkt.items())},
        "snapshots_stored": nach_ergebnis.get(OUTCOME_STORED, 0),
        "snapshots_unchanged": nach_ergebnis.get(OUTCOME_UNCHANGED, 0),
        "scopes_empty": nach_ergebnis.get(OUTCOME_EMPTY, 0),
        "scopes_failed": len(fehlgeschlagen),
        "failures": [{"label": e["scope"]["label"],
                      "kind": e["scope"]["kind"],
                      "errors": e.get("errors", [])} for e in fehlgeschlagen],
        "skipped": uebersprungen,
        "observed_quota": dict(quota or {}),
        "coverage": _coverage(scopes, ergebnisse),
        "results": ergebnisse,
    }


def _coverage(scopes, ergebnisse):
    """Wer wurde erfasst, wer nicht - und warum nicht."""
    geplant_je_art = {}
    for scope in scopes:
        geplant_je_art.setdefault(scope.kind, set()).add(scope.key)

    erfasst_je_art = {}
    ohne_je_art = {}
    for e in ergebnisse:
        art = e["scope"]["kind"]
        schluessel = e["scope"]["key"]
        if e.get("outcome") in (OUTCOME_STORED, OUTCOME_UNCHANGED):
            erfasst_je_art.setdefault(art, set()).add(schluessel)
        else:
            ohne_je_art.setdefault(art, set()).add(schluessel)

    bericht = {}
    for art, geplant in sorted(geplant_je_art.items()):
        erfasst = erfasst_je_art.get(art, set())
        bericht[art] = {
            "planned": len(geplant),
            "covered": len(erfasst),
            "not_covered": sorted(geplant - erfasst),
            "coverage_pct": (round(100.0 * len(erfasst) / len(geplant), 2)
                             if geplant else 0.0),
        }
    return bericht


def write_report(report, directory=None, now=None):
    """
    Den Bericht ablegen - atomar und ohne bestehende zu beruehren.

    Der Dateiname traegt den Startzeitpunkt; zwei Laeufe in derselben
    Sekunde bekommen einen Zaehler. Ueberschrieben wird nie.
    """
    # Aus demselben Grund wie bei CollectorLock: kein eingefrorenes
    # Vorgabeargument.
    directory = directory if directory is not None else RUN_DIR
    os.makedirs(directory, exist_ok=True)
    stempel = (now or _utc_now()).strftime("%Y%m%dT%H%M%SZ")
    basis = f"run__{stempel}"
    pfad = os.path.join(directory, f"{basis}.json")
    zaehler = 1
    while os.path.exists(pfad):
        pfad = os.path.join(directory, f"{basis}_{zaehler}.json")
        zaehler += 1

    archive._write_atomic(pfad, report)
    return pfad
