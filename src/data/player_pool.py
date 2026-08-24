"""
Spielerpool-Verwaltung fuer die Perzentilberechnung (Phase 3, Etappe 2).

Zustaendigkeit
--------------
Persistente Ablage der Referenzdaten, Importstatus, Sperre gegen parallele
Importe und ein resume-faehiger Importlauf.

Was dieses Modul NICHT tut
--------------------------
Es fuehrt keine HTTP-Requests selbst aus. Die Funktion import_league()
bekommt den Seitenabruf als Parameter uebergeben. Dadurch ist der komplette
Importablauf inklusive Wiederaufnahme ohne Netzwerk testbar, und die
Flask-Anwendung kann dieses Modul lesen, ohne je einen Import auszuloesen.

Warum kein Import im Nutzerrequest
----------------------------------
Der /players-Endpunkt von API-Sports liefert 20 Eintraege pro Seite. Eine
Top-5-Liga hat rund 500 bis 620 Spieler, also 26 bis 31 Seiten. Fuer alle
fuenf Ligen einer Saison sind das rund 136 bis 149 Requests. Mit sicherer
Drosselung dauert das ueber eine Minute. Das gehoert in einen Importjob,
nicht in eine Nutzeranfrage.

Ablageorte
----------
    data/player_pool/status.json            Importstatus aller Ligen
    data/player_pool/pool_{liga}_{saison}.json   Referenzdaten einer Liga
    data/player_pool/import.lock            Sperre gegen Doppelimporte
    data/percentiles/percentiles_{saison}.json   fertiger Snapshot

Die Rohpools bleiben ausserhalb der Versionsverwaltung, weil sie gross sind.
Der Snapshot dagegen ist kompakt und gehoert ins Repository, damit er nach
einem Deployment sofort vorliegt.
"""

import json
import os
import time
from datetime import datetime, timezone

from src.data.player_metrics import POSITION_GROUPS, normalize_position


# Absoluter Pfad, damit Importjob (Cron), Gunicorn und Tests unabhaengig vom
# aktuellen Arbeitsverzeichnis dieselben Dateien sehen. Ein relativer Pfad
# waere hier ein stiller Fehler: der Cronjob wuerde in ein anderes Verzeichnis
# schreiben als die Anwendung liest.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(_PROJECT_ROOT, "data", "player_pool")
STATUS_PATH = os.path.join(POOL_DIR, "status.json")
LOCK_PATH = os.path.join(POOL_DIR, "import.lock")

# Ein Lock, dessen Prozess nicht mehr laeuft und der aelter ist als diese
# Spanne, gilt als verwaist und darf uebernommen werden.
LOCK_STALE_SECONDS = 60 * 60  # 1 Stunde

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"

#: Der Anbieter hat geantwortet, aber inhaltlich zu wenig geliefert.
#:
#: Das ist der Status, der vorher fehlte. Bis dahin galt: Paginierung
#: durchgelaufen = complete. Eine Liga mit null Spielern auf einer Seite
#: bekam damit denselben Stempel wie eine vollstaendig importierte - und
#: wurde bei jedem weiteren Lauf ohne --force uebersprungen. Genau so ist
#: die Bundesliga 2026/27 mit 0 Spielern wochenlang als "vollstaendig"
#: stehen geblieben.
STATUS_PROVIDER_INCOMPLETE = "provider_incomplete"

#: Erwartete Vereinszahl je Liga.
#:
#: Zentral gepflegt, damit die Zahl nicht an drei Stellen als Magic Number
#: auftaucht. Stand der aktuellen Spielzeiten; die Ligue 1 spielt seit
#: 2023/24 mit 18 Vereinen.
EXPECTED_TEAM_COUNT = {
    "bl1": 18,
    "pl": 20,
    "pd": 20,
    "sa": 20,
    "fl1": 18,
}

#: Ab welchem Anteil der erwarteten Vereine ein Import als kaderseitig
#: vollstaendig gilt.
#:
#: Warum nicht 100 Prozent: Der Anbieter liefert Spieler seitenweise, und
#: ein Verein ohne einen einzigen gefuehrten Spieler kommt vor. 90 Prozent
#: lassen einen fehlenden Verein zu, schlagen aber bei den real
#: beobachteten Luecken an (Premier League 16 von 20 = 80 Prozent,
#: Serie A 12 von 20 = 60 Prozent).
MIN_TEAM_COVERAGE = 0.9

#: Wie viele Spieler eine Liga mindestens haben muss.
#:
#: Ein Kader hat rund 25 Spieler; 18 Vereine ergeben ueber 400. Der Wert
#: ist bewusst weit darunter angesetzt: Er soll den Totalausfall erkennen,
#: nicht eine knappe Seite bemaengeln.
MIN_PLAYERS_PER_LEAGUE = 100


def _now():
    return datetime.now(timezone.utc)


def _ensure_dir():
    os.makedirs(POOL_DIR, exist_ok=True)


def _write_json_atomic(path, payload):
    """
    Schreibt JSON atomar: erst temporaer, dann umbenennen.

    Verhindert, dass ein parallel lesender Gunicorn-Worker eine halb
    geschriebene Datei sieht.
    """
    _ensure_dir()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(temp_path, path)


def _read_json(path, fallback=None):
    if not os.path.exists(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# Sperre
# ---------------------------------------------------------------------------

_LOCK_STALE_SECONDS = 7200  # 2 Stunden; ein echter Import braucht hoechstens 10 Minuten


def _lock_is_stale(lock_data):
    """
    Prueft ob ein Lockfile veraltet ist.

    Timestamp-Ansatz statt Prozess-Check.

    os.kill(pid, 0) funktioniert auf Linux zuverlaessig, aber auf Windows
    mit Python 3.9 blockiert es oder wirft falsche Ausnahmen. Deshalb kein
    Prozess-Check: Ein Lock gilt als verwaist wenn er aelter als 2 Stunden
    ist. Ein echter Import braucht maximal 10 Minuten.
    """
    if not lock_data:
        return True
    started_at = lock_data.get("started_at")
    if not started_at:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except (ValueError, TypeError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = (_now() - started).total_seconds()
    return age > _LOCK_STALE_SECONDS


def read_lock():
    return _read_json(LOCK_PATH)


def acquire_lock():
    """
    Versucht die Importsperre zu setzen.

    Rueckgabe: (True, None) bei Erfolg,
               (False, info) wenn ein anderer Import laeuft.

    Ein Lock eines nicht mehr existierenden Prozesses wird uebernommen,
    ebenso ein sehr alter Lock. Sonst wuerde ein Absturz den Import
    dauerhaft blockieren.
    """
    existing = read_lock()

    if existing and not _lock_is_stale(existing):
        return False, existing

    _write_json_atomic(LOCK_PATH, {
        "pid": os.getpid(),
        "started_at": _now().isoformat(),
    })
    return True, None


def release_lock():
    """Entfernt die Sperre. Muss immer im finally-Zweig aufgerufen werden."""
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def pool_key(league_code, season):
    return f"{league_code}_{season}"


def pool_path(league_code, season):
    return os.path.join(POOL_DIR, f"pool_{league_code}_{season}.json")


def read_status():
    return _read_json(STATUS_PATH, fallback={}) or {}


def write_status(status):
    _write_json_atomic(STATUS_PATH, status)


def update_pool_status(league_code, season, **fields):
    """Aktualisiert den Statuseintrag einer Liga und schreibt ihn sofort weg."""
    status = read_status()
    key = pool_key(league_code, season)
    entry = status.get(key) or {
        "league": league_code,
        "season": season,
        "status": STATUS_PENDING,
        "total_pages": None,
        "loaded_pages": 0,
        "player_count": None,
        "updated_at": None,
    }
    entry.update(fields)
    entry["updated_at"] = _now().isoformat(timespec="seconds")
    status[key] = entry
    write_status(status)
    return entry


def get_pool_status(league_code, season):
    return read_status().get(pool_key(league_code, season))


def is_pool_complete(league_code, season):
    """
    Sagt der GESPEICHERTE Vermerk, dass der Import durchgelaufen ist?

    Das ist bewusst eine technische Aussage ueber den Importvorgang, nicht
    ueber die Datenqualitaet. Wer wissen will, ob der Pool inhaltlich
    taugt, nimmt effective_pool_status().
    """
    entry = get_pool_status(league_code, season)
    return bool(entry and entry.get("status") == STATUS_COMPLETE)


def completed_leagues(season, league_codes):
    return [code for code in league_codes if is_pool_complete(code, season)]


def effective_pool_status(league_code, season):
    """
    Der Poolstatus, wie er wirklich ist: Vermerk UND Inhalt.

    WARUM ES DAS BRAUCHT
    --------------------
    Es gab zwei Wahrheiten ueber dieselbe Liga, und sie widersprachen
    einander:

        --report / --diagnose   bewerteten den Pool INHALTLICH
                                ueber evaluate_pool()
        der Import-Skip         las den GESPEICHERTEN Vermerk aus
                                status.json ueber is_pool_complete()

    LaLiga stand deshalb im Report als unvollstaendig und wurde beim
    Import trotzdem mit "bereits vollstaendig, uebersprungen" abgetan.
    Beide Aussagen waren fuer sich genommen korrekt - sie beantworteten
    nur verschiedene Fragen, ohne das kenntlich zu machen.

    DIE FUENF GETRENNTEN FRAGEN
    ---------------------------
    Sie wurden frueher unter dem einen Wort "complete" vermengt:

        import_done         Ist der Seitenimport technisch durchgelaufen?
        provider_covered    Sind alle Vereine vom Anbieter geliefert?
        usable              Ist der Pool fachlich verwendbar?
        fresh               Sind die Daten aktuell?
        percentile_ready    Reichen die Minuten fuer Vergleichskohorten?

    Nur die ersten drei entscheiden ueber "complete". Aktualitaet und
    Perzentilreife sind eigene Fragen: Eine junge Saison hat vollstaendige
    Kader und trotzdem kaum Minuten - das ist kein kaputter Import.

    Rueckgabe: dict mit stored, evaluated, status, agree, reason und den
    Kennzahlen aus evaluate_pool().
    """
    eintrag = get_pool_status(league_code, season) or {}
    gespeichert = eintrag.get("status")

    bewertung = evaluate_pool(read_pool(league_code, season), league_code)
    bewertet = bewertung["status"]

    # Ein nicht abgeschlossener Import schlaegt jede Inhaltsbewertung:
    # Was noch laeuft, ist nicht fertig, egal wie gut das Bisherige aussieht.
    if gespeichert != STATUS_COMPLETE:
        massgeblich = gespeichert or STATUS_PENDING
        grund = f"Importvermerk steht auf {massgeblich}"
    elif bewertet != STATUS_COMPLETE:
        # Der Vermerk sagt fertig, der Inhalt widerspricht. Der Inhalt
        # gewinnt - sonst entsteht genau der Widerspruch von oben.
        massgeblich = bewertet
        grund = "Vermerk sagt complete, der Inhalt widerspricht: " + \
                "; ".join(bewertung["issues"])
    else:
        massgeblich = STATUS_COMPLETE
        grund = "Vermerk und Inhalt stimmen ueberein"

    ergebnis = {
        "league": league_code,
        "season": season,
        "stored": gespeichert,
        "evaluated": bewertet,
        "status": massgeblich,
        "agree": gespeichert == bewertet,
        "reason": grund,
        "updated_at": eintrag.get("updated_at"),
    }
    ergebnis.update({k: bewertung[k] for k in (
        "players", "teams", "with_minutes", "expected_teams",
        "team_coverage", "issues")})
    return ergebnis


def is_import_skippable(league_code, season):
    """
    Darf der Import diese Liga ueberspringen?

    Nur wenn BEIDE Wahrheiten zustimmen: Der Vermerk sagt, der Import lief
    durch, UND der Pool haelt einer inhaltlichen Pruefung stand. Ein
    veralteter Vermerk allein reicht nicht mehr aus - genau daran ist
    frueher jeder Korrekturversuch gescheitert.
    """
    return effective_pool_status(league_code, season)["status"] == STATUS_COMPLETE


# ---------------------------------------------------------------------------
# Pooldaten
# ---------------------------------------------------------------------------

def read_pool(league_code, season):
    """
    Laedt die Referenzdaten einer Liga.

    Rueckgabe: dict mit "players" und "pages_done", oder ein leeres Geruest.
    """
    data = _read_json(pool_path(league_code, season))
    if not data:
        return {
            "league": league_code,
            "season": season,
            "pages_done": [],
            "players": [],
        }
    data.setdefault("pages_done", [])
    data.setdefault("players", [])
    return data


#: Schemafassung der Pooldateien. Wird bei jedem Schreiben vermerkt,
#: damit sich spaeter erkennen laesst, mit welcher Fassung ein Stand
#: entstanden ist.
POOL_SCHEMA_VERSION = 2


def pool_revision(pool):
    """
    Herkunftsangaben eines Poolstands.

    Der Anbieter aendert Daten auch fuer ABGESCHLOSSENE Saisons: Fuer einen
    Spieler wechselten zwischen dem 09.08. und dem 23.08.2026 sowohl die
    Positionsbezeichnung als auch die Minutenzahl der Saison 2025/26. Ohne
    Herkunftsvermerk laesst sich ein solcher Wechsel nicht von einem
    Rechenfehler unterscheiden - und ein spaeterer Backtest liefe
    unbemerkt auf zwei verschiedenen Datenstaenden.

    Der Vermerk ist bewusst schlank: vier Felder in der Pooldatei, keine
    Datenbank, keine Migration. Bestehende Dateien ohne diesen Block
    bleiben lesbar; sie melden schlicht "nicht vermerkt".
    """
    spieler = pool.get("players") or []
    return {
        "source": "api-football.com/players",
        "data_as_of": _now().isoformat(timespec="seconds"),
        "schema_version": POOL_SCHEMA_VERSION,
        "player_count": len(spieler),
        # Ein einfacher Inhaltsschluessel: Spielerzahl plus Summe der
        # Einsatzminuten. Aendert der Anbieter Werte, aendert sich diese
        # Zahl - ohne dass die ganze Datei verglichen werden muss.
        "content_key": f"{len(spieler)}:"
                       f"{sum(player_minutes(e) or 0 for e in spieler)}",
    }


def write_pool(pool):
    """
    Schreibt einen Pool atomar und vermerkt seine Herkunft.

    Der Herkunftsblock wird bei jedem Schreiben erneuert. Ein vorheriger
    Stand wird dabei NICHT ueberschrieben, sondern unter previous_revision
    behalten - so bleibt sichtbar, dass und wann sich der Inhalt geaendert
    hat.
    """
    vorher = pool.get("revision")
    neu = pool_revision(pool)

    if vorher and vorher.get("content_key") != neu.get("content_key"):
        neu["previous_revision"] = {
            k: vorher.get(k)
            for k in ("data_as_of", "content_key", "player_count")
        }
    elif vorher:
        # Inhalt unveraendert: den urspruenglichen Zeitpunkt behalten,
        # sonst sieht jeder Lauf wie eine Aenderung aus.
        neu["data_as_of"] = vorher.get("data_as_of", neu["data_as_of"])
        neu["previous_revision"] = vorher.get("previous_revision")

    pool["revision"] = neu
    _write_json_atomic(pool_path(pool["league"], pool["season"]), pool)


def load_all_players(season, league_codes, require_complete=False):
    """
    Sammelt die Spieler aller angegebenen Ligen zu einem Referenzpool.

    Beruecksichtigt wird jede Liga, die tatsaechlich Spieler enthaelt -
    auch eine, die der Anbieter nur teilweise geliefert hat.

    WARUM NICHT NUR VOLLSTAENDIGE LIGEN
    -----------------------------------
    "Vollstaendig" bedeutet seit der Datenreparatur inhaltlich geprueft.
    Waeren nur vollstaendige Ligen zugelassen, verschwaenden zum
    Saisonstart drei von fuenf Ligen aus Plots und Vergleichskohorte,
    obwohl dort hunderte Spieler mit echten Werten liegen. Eine sichtbare
    Teilmenge mit ehrlichem Hinweis ist besser als eine leere Ansicht.

    Eine Liga ohne einen einzigen Spieler bleibt dagegen draussen: Sie
    traegt nichts bei und wuerde nur den Eindruck erwecken, sie sei
    beteiligt gewesen.

    require_complete=True erzwingt die strenge Auswahl - fuer Aufrufer,
    die ausdruecklich eine gepruefte Grundlage brauchen.

    Rueckgabe: (players, used_leagues)
    """
    players = []
    used = []

    for code in league_codes:
        status = (get_pool_status(code, season) or {}).get("status")
        if status not in (STATUS_COMPLETE, STATUS_PROVIDER_INCOMPLETE):
            continue
        if require_complete and status != STATUS_COMPLETE:
            continue

        pool = read_pool(code, season)
        eintraege = pool.get("players") or []
        if not eintraege:
            continue

        players.extend(eintraege)
        used.append(code)

    return players, used


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def build_pool_entry(profile_by_scope, metrics_by_scope, league_code=None):
    """
    Reduziert die vier Wettbewerbsumfaenge eines Spielers auf das, was der
    Referenzpool braucht.

    Seit dieser Version speichert ein Pooleintrag NICHT mehr nur eine
    Kennzahlenmenge, sondern eine je Wettbewerbsumfang (club_all, league,
    national, all) - siehe COMPETITION_SCOPES in player_compare_loader.py.

    Warum: Radar und Scatter-Plots verwenden dieselbe Wettbewerbslogik.
    Der Standard ist "Alle Vereinswettbewerbe" - ein Scatter-Punkt fuer
    Tore/90 muss also auf denselben aggregierten Werten beruhen wie das
    Radar, nicht nur auf Ligaspielen.

    Kein zusaetzlicher API-Request dafuer: Alle vier Aggregationen werden
    aus DERSELBEN rohen API-Antwort berechnet, die der Importjob ohnehin
    schon fuer den Spieler abgerufen hat.

    Ehrlicher Grenzfall: Die Liga-Seiten-Abfrage (/players?league=X), die
    der Importjob nutzt, liefert je nach API-Sports-Verhalten unter
    Umstaenden nur den ligaeigenen statistics-Block. In dem Fall sind
    club_all und league schlicht identisch - das ist korrekt und wird
    nicht kuenstlich aufgebauscht.

    Die vollstaendigen Rohdaten werden weiterhin NICHT gespeichert, nur
    die bereits berechneten Kennzahlen je Scope. Das haelt die Dateien
    klein und den Import schnell.

    age, team_name, position: aus dem club_all-Profil entnommen. Die
    Position soll sich nicht danach richten, welcher Wettbewerbsumfang
    gerade gewaehlt ist - ein Spieler ist nicht "mehr Mittelfeldspieler",
    nur weil man seine Pokalspiele mitzaehlt.

    league_code: die Liga, in der der Spieler beim Import gefunden wurde
    (Seiten-Abfrage /players?league=X). Wird sie uebergeben, hat sie Vorrang
    vor der aus den aggregierten Statistiken abgeleiteten Liga. Grund: der
    Scatter filtert und faerbt nach dieser Liga; sie muss zu der Pooldatei
    passen, in der der Spieler liegt, nicht zur Liga mit den meisten
    Pokalminuten. Ohne Angabe gilt der bisherige Wert aus dem Profil.
    """
    primary = profile_by_scope.get("club_all") or next(iter(profile_by_scope.values()), {})

    minutes_by_scope = {
        scope: profile.get("minutes")
        for scope, profile in profile_by_scope.items()
    }

    return {
        "player_id": primary.get("player_id"),
        "name": primary.get("name"),
        "position": primary.get("position"),
        "league_code": league_code or primary.get("league_code"),

        # Filterdimensionen fuer spaetere Auswertungen (Scatter, ML)
        "age": primary.get("age"),
        "team_name": primary.get("team_name"),
        # Stabile Team-ID. Additiv - bestehende Pools ohne dieses Feld
        # bleiben lesbar, evaluate_pool faellt dann auf den Namen zurueck.
        "team_id": primary.get("team_id"),

        "minutes_by_scope": minutes_by_scope,
        "metrics_by_scope": {
            scope: {k: v for k, v in (values or {}).items() if v is not None}
            for scope, values in metrics_by_scope.items()
        },
    }



def _distinct_teams(players):
    """
    Die eindeutigen Vereine eines Pools.

    Gezaehlt wird ueber die stabile team_id, nicht ueber den Namen.
    Derselbe Verein kommt in Anbieterantworten in mehreren Schreibweisen
    vor; ueber Namen gezaehlt ergab LaLiga dadurch 22 von 20 Vereinen -
    eine Zahl, die es nicht geben kann.

    Pools aus der Zeit vor der team_id fallen auf den Namen zurueck. Sie
    bleiben damit lesbar, auch wenn ihre Zaehlung ungenauer ist.
    """
    ids = {p.get("team_id") for p in players if p.get("team_id") is not None}
    if ids:
        return ids
    return {p.get("team_name") for p in players if p.get("team_name")}


def evaluate_pool(pool, league_code=None):
    """
    Wie gut ist dieser Pool inhaltlich?

    Rueckgabe:
        {"players", "teams", "with_minutes", "expected_teams",
         "team_coverage", "issues": [...], "status": ...}

    Bewusst getrennt nach drei Dingen, die frueher vermengt waren:

        Kaderabdeckung   Sind alle Vereine mit Spielern vertreten?
        Statistikreife   Haben diese Spieler schon Einsatzminuten?
        Perzentilreife   Reichen die Minuten fuer eine Vergleichskohorte?

    Eine junge Saison hat vollstaendige Kader und trotzdem fast keine
    Minuten. Das ist KEIN unvollstaendiger Import - es ist eine junge
    Saison. Deshalb entscheidet ueber den Status allein die
    Kaderabdeckung, nie die Minutenzahl.
    """
    league_code = league_code or pool.get("league")
    players = pool.get("players") or []

    teams = _distinct_teams(players)
    mit_minuten = 0
    for spieler in players:
        if (player_minutes(spieler) or 0) > 0:
            mit_minuten += 1

    erwartet = EXPECTED_TEAM_COUNT.get(league_code)
    abdeckung = (len(teams) / erwartet) if erwartet else None

    issues = []
    if not players:
        issues.append("keine Spieler geliefert")
    elif len(players) < MIN_PLAYERS_PER_LEAGUE:
        issues.append(f"nur {len(players)} Spieler "
                      f"(erwartet mindestens {MIN_PLAYERS_PER_LEAGUE})")
    if not teams:
        issues.append("kein einziger Verein vertreten")
    elif erwartet and abdeckung < MIN_TEAM_COVERAGE:
        issues.append(f"nur {len(teams)} von {erwartet} Vereinen vertreten")

    return {
        "players": len(players),
        "teams": len(teams),
        "with_minutes": mit_minuten,
        "expected_teams": erwartet,
        "team_coverage": round(abdeckung, 3) if abdeckung is not None else None,
        "issues": issues,
        "status": STATUS_COMPLETE if not issues else STATUS_PROVIDER_INCOMPLETE,
    }


def player_minutes(entry, scope="club_all"):
    """
    Einsatzminuten eines Pooleintrags - die EINE maessgebliche Stelle.

    Ein Pooleintrag hat KEIN Feld "minutes" auf oberster Ebene. Genau das
    hat der Report frueher gelesen, weshalb dort dauerhaft null Spieler
    mit Minuten standen, obwohl 187 welche hatten.

    Massgeblich ist minutes_by_scope. Der Rueckfall auf
    metrics_by_scope[...]["minutes"] deckt Pools aus der Zeit ab, bevor
    minutes_by_scope eingefuehrt wurde.

    None wird zu 0 - aber erst hier, an einer Stelle, und nicht durch ein
    verstreutes "or 0", das echte Nullen und fehlende Werte vermengt.
    """
    if not isinstance(entry, dict):
        return 0

    by_scope = entry.get("minutes_by_scope")
    if isinstance(by_scope, dict) and scope in by_scope:
        return by_scope.get(scope) or 0

    metrics = (entry.get("metrics_by_scope") or {}).get(scope) or {}
    if "minutes" in metrics:
        return metrics.get("minutes") or 0

    return 0


#: Wie weit eine Kennzahl gegenueber dem Bestand fallen darf.
#:
#: 0.9 statt der frueheren 0.75. Die alte Grenze war nachweislich zu
#: locker: Bei einem Refresh fiel die Premier League von 16 auf 13
#: Vereine (Grenze war 12) und die Serie A von 12 auf 9 (Grenze war
#: exakt 9) - beide wurden durchgelassen. Mit 0.9 loesen beide aus.
MAX_RELATIVE_DROP = 0.9

#: Untergrenze der Ligaabdeckung, unabhaengig vom Bestand.
#:
#: DAS IST DIE WICHTIGERE HAELFTE. Ein rein relativer Vergleich misst
#: gegen den VORSTAND - und wenn der bereits schlecht war, gilt jede
#: weitere Verschlechterung als klein. So kann eine Liga ueber mehrere
#: Laeufe von 20 auf 16 auf 13 auf 10 Vereine rutschen, ohne dass die
#: Pruefung je anschlaegt. Genau das ist passiert: Die Serie A steht
#: inzwischen bei 9 von 20 Vereinen, also 45 Prozent.
#:
#: 0.8 ist bewusst nicht hoeher: Der Anbieter fuehrt gelegentlich einen
#: Verein ohne einen einzigen Spieler, und eine junge Saison ist nicht
#: sofort vollstaendig. Vier fehlende Vereine von zwanzig sind das
#: aeusserste, was noch als Schwankung durchgeht.
MIN_ABSOLUTE_TEAM_COVERAGE = 0.8


def is_better_pool(neu, alt, league_code=None):
    """
    Darf dieser neue Stand den bestehenden ersetzen?

    Rueckgabe: (darf_veroeffentlichen, begruendung)

    Geprueft wird MEHRDIMENSIONAL. Eine Verbesserung in einer Kennzahl
    darf eine starke Verschlechterung in einer anderen nicht verdecken -
    genau das ist vorher passiert: Die Spielerzahl blieb bei 240, waehrend
    die Vereinsabdeckung von 16 auf 13 fiel, und weil nur die Spielerzahl
    eine harte Rolle spielte, ging der Stand durch.

    Geprueft werden:

        Vereine (stabile IDs)     relativ zum Bestand UND absolut zur Liga
        Spieler                   relativ zum Bestand
        Spieler mit Minuten       relativ zum Bestand
        Seitenvollstaendigkeit    absolut

    Die absolute Abdeckung ist der Schutz gegen SCHLEICHENDE Degradation
    ueber mehrere Laeufe.
    """
    alt = alt or {}
    alt_players = alt.get("players") or []
    neu_players = (neu or {}).get("players") or []

    neu_bewertung = evaluate_pool(neu, league_code)
    alt_bewertung = evaluate_pool(alt, league_code)

    if not alt_players:
        return True, "kein bestehender Pool"

    if not neu_players:
        return False, (f"neuer Stand ist leer, bestehender hat "
                       f"{len(alt_players)} Spieler")

    gruende = []

    def pruefe(name, neu_wert, alt_wert):
        # "<=" statt "<": Ein Wert exakt auf der Grenze ist bereits der
        # Verlust, den die Grenze verhindern soll. Die Serie A lag mit 9
        # von zuvor 12 Vereinen exakt auf ihr und wurde durchgelassen.
        if alt_wert and neu_wert <= alt_wert * MAX_RELATIVE_DROP:
            gruende.append(f"{name}: {neu_wert} gegen bisher {alt_wert}")

    pruefe("Vereine", neu_bewertung["teams"], alt_bewertung["teams"])
    pruefe("Spieler", neu_bewertung["players"], alt_bewertung["players"])
    pruefe("Spieler mit Minuten",
           neu_bewertung["with_minutes"], alt_bewertung["with_minutes"])

    # Absolute Untergrenze - unabhaengig davon, wie schlecht der Bestand
    # bereits war.
    erwartet = neu_bewertung["expected_teams"]
    if erwartet:
        abdeckung = neu_bewertung["teams"] / erwartet
        bestand_abdeckung = (alt_bewertung["teams"] / erwartet) if erwartet else 0
        if (abdeckung < MIN_ABSOLUTE_TEAM_COVERAGE
                and abdeckung < bestand_abdeckung):
            gruende.append(
                f"Ligaabdeckung nur {neu_bewertung['teams']}/{erwartet} "
                f"({abdeckung:.0%}, Mindestmass "
                f"{MIN_ABSOLUTE_TEAM_COVERAGE:.0%})")

    if gruende:
        return False, "; ".join(gruende)

    return True, "neuer Stand mindestens gleichwertig"


def import_league(league_code, season, fetch_page, build_entry,
                  throttle_seconds=0.5, resume=True, progress=None):
    """
    Importiert alle Seiten einer Liga.

    fetch_page(page)  -> dict mit "response" und "paging" (siehe _get_full)
    build_entry(raw)  -> Pooleintrag oder None, wenn der Spieler nicht zaehlt

    Beide werden injiziert, damit dieser Ablauf ohne Netzwerk getestet
    werden kann.

    resume=True setzt einen abgebrochenen Lauf fort, statt bereits geladene
    Seiten erneut abzurufen. Bei rund 30 Requests pro Liga ist das den
    kleinen Mehraufwand wert.

    Rueckgabe: Statuseintrag der Liga.
    """
    # Der bestehende Stand wird IMMER gelesen, auch bei resume=False.
    # Nicht um ihn fortzusetzen, sondern um am Ende vergleichen zu koennen,
    # ob der neue Stand ueberhaupt besser ist (siehe is_better_pool).
    bestand = read_pool(league_code, season)

    pool = bestand if resume else {
        "league": league_code, "season": season, "pages_done": [], "players": [],
    }
    if not resume:
        # Bei --force darf der Vergleichsstand nicht dieselbe Liste sein,
        # die gleich befuellt wird.
        import copy
        bestand = copy.deepcopy(bestand)

    pages_done = set(pool.get("pages_done") or [])
    players_by_id = {
        entry.get("player_id"): entry
        for entry in pool.get("players") or []
        if entry.get("player_id") is not None
    }

    update_pool_status(league_code, season, status=STATUS_IN_PROGRESS)

    try:
        first = fetch_page(1)
        total_pages = int((first.get("paging") or {}).get("total") or 1)

        update_pool_status(
            league_code, season,
            status=STATUS_IN_PROGRESS,
            total_pages=total_pages,
            loaded_pages=len(pages_done),
        )

        for page in range(1, total_pages + 1):
            if page in pages_done:
                continue

            payload = first if page == 1 else fetch_page(page)

            for raw in payload.get("response") or []:
                entry = build_entry(raw)
                if entry and entry.get("player_id") is not None:
                    players_by_id[entry["player_id"]] = entry

            pages_done.add(page)

            pool["pages_done"] = sorted(pages_done)
            pool["players"] = list(players_by_id.values())
            write_pool(pool)

            update_pool_status(
                league_code, season,
                status=STATUS_IN_PROGRESS,
                total_pages=total_pages,
                loaded_pages=len(pages_done),
            )

            if progress:
                progress(league_code, season, len(pages_done), total_pages)

            # Drosselung gegen das Sekundenlimit der API.
            # Die letzte Seite braucht keine Pause mehr.
            if throttle_seconds and page < total_pages:
                time.sleep(throttle_seconds)

        pool["pages_done"] = sorted(pages_done)
        pool["players"] = list(players_by_id.values())

        # --- Veroeffentlichung erst nach Pruefung --------------------------
        #
        # Bis hierher wurde nach jeder Seite geschrieben, damit ein
        # abgebrochener Lauf fortsetzen kann. Jetzt entscheidet sich, ob
        # dieser Stand der neue Produktivpool wird.
        bewertung = evaluate_pool(pool, league_code)
        besser, begruendung = is_better_pool(pool, bestand, league_code)

        if not besser:
            # Der bestehende Pool war besser. Er wird wiederhergestellt -
            # der Anbieter hat voruebergehend weniger geliefert, und das
            # darf einen guten Stand nicht vernichten.
            write_pool(bestand)
            # Der Status beschreibt jetzt den BEHALTENEN Pool, nicht den
            # verworfenen. Vorher fehlten hier team_count und Abdeckung
            # ganz, sodass der Report fuer eine geschuetzte Liga "None"
            # anzeigte und man nicht erkennen konnte, wie gut der
            # behaltene Stand eigentlich ist.
            behalten = evaluate_pool(bestand, league_code)
            return update_pool_status(
                league_code, season,
                status=STATUS_PROVIDER_INCOMPLETE,
                total_pages=total_pages,
                loaded_pages=len(pages_done),
                player_count=behalten["players"],
                team_count=behalten["teams"],
                expected_teams=behalten["expected_teams"],
                team_coverage=behalten["team_coverage"],
                players_with_minutes=behalten["with_minutes"],
                rejected_player_count=bewertung["players"],
                rejected_team_count=bewertung["teams"],
                rejected_reason=begruendung,
                kept_existing_pool=True,
                issues=behalten["issues"] or ["Anbieterstand verworfen"],
            )

        write_pool(pool)

        return update_pool_status(
            league_code, season,
            status=bewertung["status"],
            total_pages=total_pages,
            loaded_pages=len(pages_done),
            player_count=bewertung["players"],
            team_count=bewertung["teams"],
            expected_teams=bewertung["expected_teams"],
            team_coverage=bewertung["team_coverage"],
            players_with_minutes=bewertung["with_minutes"],
            issues=bewertung["issues"],
            kept_existing_pool=False,
        )

    except Exception as error:
        # Teilergebnis bleibt erhalten, damit ein spaeterer Lauf fortsetzen kann.
        pool["pages_done"] = sorted(pages_done)
        pool["players"] = list(players_by_id.values())
        write_pool(pool)

        update_pool_status(
            league_code, season,
            status=STATUS_ERROR,
            loaded_pages=len(pages_done),
            error=str(error),
        )
        raise


def coverage_report(season, league_codes):
    """Uebersicht fuer die Kommandozeile und spaeter fuer eine Statusanzeige."""
    rows = []
    for code in league_codes:
        entry = get_pool_status(code, season) or {}
        rows.append({
            "league": code,
            "season": season,
            "status": entry.get("status", STATUS_PENDING),
            "loaded_pages": entry.get("loaded_pages", 0),
            "total_pages": entry.get("total_pages"),
            "player_count": entry.get("player_count"),
            "updated_at": entry.get("updated_at"),
        })
    return rows


# ---------------------------------------------------------------------------
# Scatter-Plot-Datenzugriff (Phase 3.2 Teil 2)
# ---------------------------------------------------------------------------
#
# Liest ausschliesslich den vorhandenen Pool. Kein einziger API-Request.
# Der Pool wird bereits von der Perzentil-Berechnung genutzt - Scatter ist
# eine zweite, rein lesende Sicht auf dieselben Daten. Kein neuer Import,
# keine neue Datenstruktur.

def load_scatter_points(season, league_codes, position, min_minutes,
                        x_key, y_key, scope="club_all"):
    """
    Baut die Punktliste fuer den Scatter-Plot.

    scope waehlt, aus welchem Wettbewerbsumfang die Achsenwerte stammen -
    dieselben Optionen wie im Radar (club_all/league/cl/euro/world_cup/
    national/all). Unbekannte Werte fallen auf club_all zurueck.

    scope und league_codes sind zwei VERSCHIEDENE Dimensionen und werden
    bewusst nicht vermischt:
      league_codes bestimmt, aus welchen Pooldateien die Spieler stammen
                   (ihre Herkunftsliga),
      scope        bestimmt, aus welchem Wettbewerb deren Zahlen stammen.
    "Bundesliga + Scope cl" heisst also: Spieler des Bundesliga-Pools,
    bewertet ausschliesslich nach ihren Champions-League-Werten.

    Liest nur vollstaendig importierte Ligen (ueber load_all_players()).
    Ein Spieler wird nur aufgenommen, wenn:
      - seine Einsatzminuten IM GEWAEHLTEN SCOPE mindestens min_minutes
        betragen (ein Spieler kann z. B. 3000 club_all-Minuten aber nur
        400 Nationalmannschaftsminuten haben - die Mindestminutengrenze
        muss sich auf denselben Scope beziehen wie die Achsenwerte)
      - beide gewaehlten Metriken IN DIESEM SCOPE einen Wert ungleich
        None haben
      - position leer ist ODER seine Position genau passt

    Ein Spieler ohne Daten im gewaehlten Scope faellt dadurch heraus, statt
    als Punkt bei (0,0) zu erscheinen: minutes_by_scope[scope] ist dann None
    und metrics_by_scope[scope] leer. Fuer cl/euro/world_cup heisst das
    konkret, dass nur Spieler mit echten Einsatzminuten in genau diesem
    Wettbewerb im Plot landen - ein nicht nominierter oder mit seinem Land
    nicht qualifizierter Spieler taucht gar nicht erst auf.

    Rueckgabe: (points, used_leagues)
      points: Liste von dicts mit id, name, team, league, position, age,
              minutes, x, y - fertig fuers Frontend
      used_leagues: welche der angefragten Ligen tatsaechlich vollstaendig
                    vorlagen (fuer einen ehrlichen Poolstatus im Endpunkt)
    """
    # Muss mit COMPETITION_SCOPES in player_compare_loader.py uebereinstimmen.
    # Lokal gehalten, damit dieses Modul importfrei von der Vergleichslogik
    # bleibt (siehe auch SNAPSHOT_SCOPES in percentile_engine.py).
    if scope not in ("club_all", "league", "cl", "euro", "world_cup",
                     "national", "all"):
        scope = "club_all"

    players, used_leagues = load_all_players(season, league_codes)

    points = []
    for entry in players:
        # Gespeicherte Position beim Lesen normalisieren - siehe
        # player_metrics.normalize_position. Ohne das faende ein Filter auf
        # "Attacker" die als "Forward" gespeicherten Spieler nicht.
        gruppe = normalize_position(entry.get("position"))
        if position and gruppe != position:
            continue

        minutes_by_scope = entry.get("minutes_by_scope") or {}
        minutes = minutes_by_scope.get(scope)
        if minutes is None or minutes < min_minutes:
            continue

        metrics = (entry.get("metrics_by_scope") or {}).get(scope) or {}
        x_value = metrics.get(x_key)
        y_value = metrics.get(y_key)
        if x_value is None or y_value is None:
            continue

        points.append({
            "id": entry.get("player_id"),
            "name": entry.get("name"),
            "team": entry.get("team_name"),
            "league": entry.get("league_code"),
            "position": entry.get("position"),
            "age": entry.get("age"),
            "minutes": minutes,
            "x": x_value,
            "y": y_value,
        })

    return points, used_leagues

