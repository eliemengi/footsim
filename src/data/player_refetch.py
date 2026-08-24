"""
Gezielter Neuabruf einzelner Spieler - statt einer ganzen Liga.

WARUM ES DIESE DATEI GIBT
-------------------------
Um zwei Spielerprofile zu erneuern, gab es bisher genau einen Weg:

    refresh_players.py --league pd --season 2026 --force --refetch-players

Das sind rund 450 Anbieterabrufe fuer zwei Spieler. Der naheliegende
Befehl existierte nicht:

    refresh_players.py --season 2026 --refetch-player 278

und quittierte mit "unrecognized arguments". Wer zwei Werte pruefen
wollte, musste eine komplette Liga neu laden - oder es lassen.

WAS DIESES MODUL ZUSICHERT
--------------------------
    Ein Request je Spieler. Nicht 450.
    Die Liga muss nicht angegeben werden - sie wird lokal aufgeloest.
    Eine ungueltige Antwort ueberschreibt NIEMALS einen guten Stand.
    Bei Rate Limit oder Ausfall bleibt alles, wie es war.
    Nur die betroffenen Pooleintraege aendern sich, kein einziger anderer.
    --dry-run schreibt garantiert nichts (Sperre in disk_cache.no_persist).

WAS ES AUSDRUECKLICH NICHT TUT
------------------------------
Es korrigiert keine Werte. Liefert der Anbieter weiterhin 38 Minuten,
stehen danach 38 Minuten im Pool - versehen mit dem Vermerk, dass der
Stand moeglicherweise vorlaeufig ist. Ein gezielter Refresh beweist
nicht, dass die Zahl stimmt; er beweist nur, dass sie frisch ist.

Und es kennt keine Spieler. Es gibt in dieser Datei keine ID, keinen
Namen und keinen Verein - jede Sonderbehandlung waere genau der Fehler,
den der Auftrag ausschliesst.
"""

from src.data.player_data_quality import (
    QUALITY_PROVIDER_ERROR,
    QUALITY_STALE_FALLBACK,
    classify_profile_quality,
    quality_block,
)
from src.utils import disk_cache


def profile_cache_key(player_id, season):
    """
    Der Cacheschluessel eines Spielerprofils.

    Eine einzige Stelle, weil er an drei Orten gebraucht wird: beim
    Umgehen, beim Lesen des alten Stands und in der Diagnoseausgabe.
    Frueher stand dieselbe f-Zeichenkette dreimal im Projekt.
    """
    return f"apisports:playerprofile:{int(player_id)}:{int(season)}"


# ---------------------------------------------------------------------------
# Eingaben pruefen
# ---------------------------------------------------------------------------

def normalize_ids(rohe_ids):
    """
    Spieler-IDs pruefen und entdoppeln.

    Rueckgabe: (gueltige_ids, abgewiesene). Die Reihenfolge der Eingabe
    bleibt erhalten - wer drei IDs nennt, will sie in seiner Reihenfolge
    im Bericht wiederfinden.
    """
    gueltig = []
    abgewiesen = []
    gesehen = set()

    for roh in rohe_ids or []:
        try:
            pid = int(roh)
        except (TypeError, ValueError):
            abgewiesen.append((roh, "keine ganze Zahl"))
            continue
        if pid <= 0:
            abgewiesen.append((roh, "keine positive ID"))
            continue
        if pid in gesehen:
            continue
        gesehen.add(pid)
        gueltig.append(pid)

    return gueltig, abgewiesen


# ---------------------------------------------------------------------------
# Herkunft aufloesen - ohne einen einzigen Anbieterabruf
# ---------------------------------------------------------------------------

def resolve_player(player_id, season, league_codes=None):
    """
    Zu welcher Liga und welchem Verein gehoert dieser Spieler?

    Rein lokal. Drei Quellen, in dieser Reihenfolge:

        1. Die Pools der gefragten Saison - die genaueste Quelle, weil
           dort bereits ein vollstaendiger Eintrag steht.
        2. Der gecachte Kaderindex - kennt auch Neuzugaenge, die noch
           keinen Statistiksatz haben.
        3. Die Pools frueherer Saisons - nur als Hinweis auf die Liga.

    Der Kaderindex wird ausdruecklich NUR gelesen, nie gebaut: Ein Aufbau
    kostet rund hundert Anbieterabrufe, und das waere das Gegenteil
    dessen, wofuer dieses Modul da ist.

    Rueckgabe: dict mit player_id, name, team_name, team_id, league_code,
    source - oder mit lauter None-Werten, wenn nichts bekannt ist. Ein
    unbekannter Spieler ist KEIN Fehler: Er kann trotzdem abgerufen
    werden, nur laesst sich sein Pooleintrag dann nicht zuordnen.
    """
    from src.data.player_compare_loader import COMPARE_LEAGUE_CODES
    from src.data.player_pool import read_pool

    codes = list(league_codes or COMPARE_LEAGUE_CODES)
    leer = {"player_id": player_id, "name": None, "team_name": None,
            "team_id": None, "league_code": None, "source": None}

    # 1. Pools der gefragten Saison.
    for code in codes:
        for eintrag in read_pool(code, season).get("players") or []:
            if eintrag.get("player_id") == player_id:
                return {
                    "player_id": player_id,
                    "name": eintrag.get("name"),
                    "team_name": eintrag.get("team_name"),
                    "team_id": eintrag.get("team_id"),
                    "league_code": code,
                    "source": "pool",
                }

    # 2. Kaderindex - nur aus dem Cache.
    for eintrag in cached_squad_index(season):
        if eintrag.get("player_id") == player_id:
            return {
                "player_id": player_id,
                "name": eintrag.get("name"),
                "team_name": eintrag.get("team_name"),
                "team_id": eintrag.get("team_id"),
                "league_code": eintrag.get("league_code"),
                "source": "squad_index",
            }

    # 3. Fruehere Saisons - der Verein kann inzwischen ein anderer sein,
    #    deshalb wird nur die Liga als Hinweis uebernommen und der Verein
    #    ausdruecklich NICHT.
    for zurueck in (1, 2):
        for code in codes:
            for eintrag in read_pool(code, season - zurueck).get("players") or []:
                if eintrag.get("player_id") == player_id:
                    return {
                        "player_id": player_id,
                        "name": eintrag.get("name"),
                        "team_name": None,
                        "team_id": None,
                        "league_code": code,
                        "source": f"pool_{season - zurueck}",
                    }

    return leer


def cached_squad_index(season):
    """
    Der Kaderindex, ausschliesslich aus dem Cache.

    squad_index() wuerde bei einem Fehltreffer rund hundert Abrufe
    ausloesen, um den Index zu bauen. Fuer einen gezielten Refresh von
    zwei Spielern waere das absurd - deshalb liest diese Funktion nur.
    Fehlt der Index, ist die Rueckgabe leer und der Aufrufer arbeitet
    ohne ihn weiter.
    """
    eintrag = disk_cache.read_entry(f"apisports:squad_index:{int(season)}")
    return (eintrag or {}).get("payload") or []


def team_player_ids(team_id, season):
    """
    Die Spieler-IDs eines Vereins aus dem gecachten Kaderindex.

    Rueckgabe: (ids, teamname). Leere Liste, wenn der Index fehlt oder
    den Verein nicht kennt - dann kann der Teamrefresh ehrlich melden,
    dass er ohne Index nichts ausrichten kann.
    """
    ids = []
    name = None
    for eintrag in cached_squad_index(season):
        if eintrag.get("team_id") == team_id:
            name = name or eintrag.get("team_name")
            if eintrag.get("player_id") is not None:
                ids.append(int(eintrag["player_id"]))
    return ids, name


# ---------------------------------------------------------------------------
# Antworten pruefen
# ---------------------------------------------------------------------------

def validate_profile(raw, player_id, season):
    """
    Ist diese Anbieterantwort brauchbar genug, um einen guten Stand zu ersetzen?

    Rueckgabe: (ok, begruendung).

    Die Pruefung ist bewusst streng, weil ihr Ergebnis darueber
    entscheidet, ob ein vorhandener, moeglicherweise korrekter Stand
    ueberschrieben wird. Im Zweifel gewinnt der Bestand: Ein
    verlorengegangener Datenstand laesst sich nicht wiederherstellen, ein
    nicht durchgefuehrter Refresh dagegen jederzeit wiederholen.

    Was NICHT geprueft wird: ob die Zahlen plausibel sind. 38 Minuten
    sind eine gueltige Antwort. Ob sie stimmen, ist eine Frage an den
    Anbieter, nicht an diesen Code.
    """
    if raw is None:
        return False, "leere Antwort"
    if not isinstance(raw, dict):
        return False, f"unerwarteter Antworttyp {type(raw).__name__}"

    spieler = raw.get("player")
    if not isinstance(spieler, dict) or spieler.get("id") is None:
        return False, "kein Spielerblock in der Antwort"

    try:
        geliefert = int(spieler["id"])
    except (TypeError, ValueError):
        return False, f"unlesbare Spieler-ID {spieler.get('id')!r}"

    if geliefert != int(player_id):
        return False, (f"falsche Spieler-ID: angefragt {player_id}, "
                       f"geliefert {geliefert}")

    statistiken = raw.get("statistics")
    if statistiken is None:
        return False, "kein statistics-Feld"
    if not isinstance(statistiken, list):
        return False, "statistics ist keine Liste"

    # Saisonplausibilitaet: Traegt mindestens ein Block eine Saison, muss
    # eine davon passen. Traegt keiner eine, wird nicht widersprochen -
    # der Anbieter laesst das Feld gelegentlich weg.
    saisons = set()
    for block in statistiken:
        if not isinstance(block, dict):
            return False, "statistics enthaelt einen ungueltigen Block"
        liga = block.get("league") or {}
        if liga.get("season") is not None:
            try:
                saisons.add(int(liga["season"]))
            except (TypeError, ValueError):
                pass

    if saisons and int(season) not in saisons:
        return False, (f"Saison passt nicht: angefragt {season}, "
                       f"geliefert {sorted(saisons)}")

    return True, f"gueltig ({len(statistiken)} Wettbewerbsbloecke)"


# ---------------------------------------------------------------------------
# Pooleintrag bauen
# ---------------------------------------------------------------------------

def build_entry_from_raw(source_raw, season, league_code):
    """
    Baut einen Pooleintrag aus einer vollstaendigen Rohantwort.

    Herausgeloest aus refresh_players._build_entry(), damit der gezielte
    Refresh und der Ligaimport nachweislich denselben Eintrag erzeugen.
    Zwei getrennte Aufbauwege waeren eine sichere Quelle fuer
    Abweichungen zwischen "frisch importiert" und "gezielt erneuert".

    Rueckgabe: Pooleintrag oder None, wenn der Spieler ohne verwertbare
    Vereinsdaten dasteht.
    """
    from src.data.player_compare_loader import (
        COMPETITION_SCOPES, build_player_profile, compute_player_metrics,
    )
    from src.data.player_metrics import METRICS
    from src.data.player_pool import build_pool_entry

    alle_kennzahlen = list(METRICS.keys())

    profile_by_scope = {}
    metrics_by_scope = {}
    for scope in COMPETITION_SCOPES:
        profil = build_player_profile(source_raw, season, scope=scope)
        profile_by_scope[scope] = profil
        if profil.get("data_available") and profil.get("position") is not None:
            metrics_by_scope[scope] = compute_player_metrics(profil, alle_kennzahlen)
        else:
            metrics_by_scope[scope] = {}

    primaer = profile_by_scope.get("club_all")
    if (not primaer or not primaer.get("data_available")
            or primaer.get("position") is None):
        return None

    return build_pool_entry(profile_by_scope, metrics_by_scope,
                            league_code=league_code)


def _minutes_by_scope(eintrag):
    """Die Minuten je Wettbewerbsumfang eines Pooleintrags."""
    return dict((eintrag or {}).get("minutes_by_scope") or {})


# ---------------------------------------------------------------------------
# Der eigentliche Refresh
# ---------------------------------------------------------------------------

def refetch_player(player_id, season, dry_run=False, throttle_seconds=0.0,
                   fetch=None, update_pool=True):
    """
    Einen einzelnen Spieler frisch beim Anbieter holen.

    Genau EIN Profilrequest. Der Cache wird ausschliesslich fuer diesen
    einen Schluessel umgangen und danach wieder wie vorher behandelt.

    dry_run=True fragt den Anbieter, schreibt aber garantiert nichts:
    disk_cache.no_persist() sperrt das Schreiben an der schmalsten
    Stelle, und der Pool wird gar nicht erst angefasst. Die Sperre sitzt
    bewusst tief - eine if-Abfrage je Aufrufer koennte man vergessen.

    fetch: nur fuer Tests. Ohne Angabe wird get_player_season_raw benutzt.

    Rueckgabe: dict mit dem vollstaendigen Ergebnis, siehe CLI-Ausgabe.
    Es wird KEINE Ausnahme nach aussen getragen - ein Ausfall ist ein
    Ergebniszustand, kein Absturz.
    """
    from src.api.apisports_api import ApisportsRateLimit, ApisportsUnavailable

    schluessel = profile_cache_key(player_id, season)
    herkunft = resolve_player(player_id, season)

    # Der Stand VOR dem Abruf - er ist der Vergleichsmassstab und im
    # Fehlerfall das, was erhalten bleibt.
    alt_eintrag = disk_cache.read_entry(schluessel)
    alt_meta = (alt_eintrag or {}).get("meta") or {}
    alt_payload = (alt_eintrag or {}).get("payload") or []
    alt_raw = alt_payload[0] if alt_payload else None

    ergebnis = {
        "player_id": player_id,
        "name": herkunft.get("name"),
        "team_name": herkunft.get("team_name"),
        "league_code": herkunft.get("league_code"),
        "resolved_from": herkunft.get("source"),
        "cache_key": schluessel,
        "old_fetched_at": alt_meta.get("fetched_at"),
        "new_fetched_at": None,
        "old_minutes": None,
        "new_minutes": None,
        "changed": False,
        "quality": None,
        "quality_reason": None,
        "pool_updated": False,
        "persisted": not dry_run,
        "dry_run": bool(dry_run),
        "ok": False,
        "error": None,
        "requests": 0,
    }

    if alt_raw is not None:
        alt_kandidat = build_entry_from_raw(alt_raw, season,
                                            herkunft.get("league_code"))
        ergebnis["old_minutes"] = _minutes_by_scope(alt_kandidat)

    if fetch is None:
        from src.data.player_compare_loader import get_player_season_raw
        fetch = get_player_season_raw

    def hole():
        return fetch(player_id, season, throttle_seconds=throttle_seconds)

    try:
        # Nur DIESEN einen Schluessel umgehen. Ausserhalb des Blocks gilt
        # wieder, was vorher galt.
        if dry_run:
            with disk_cache.no_persist():
                with disk_cache.bypass(schluessel):
                    neu_raw = hole()
        else:
            with disk_cache.bypass(schluessel):
                neu_raw = hole()
        ergebnis["requests"] = 1

    except ApisportsRateLimit as fehler:
        ergebnis["error"] = f"Rate Limit: {fehler}"
        ergebnis["quality"] = (QUALITY_STALE_FALLBACK if alt_raw
                               else QUALITY_PROVIDER_ERROR)
        ergebnis["quality_reason"] = ("Abruf abgelehnt, vorhandener Stand "
                                      "bleibt unveraendert")
        return ergebnis

    except ApisportsUnavailable as fehler:
        ergebnis["error"] = f"Anbieter nicht erreichbar: {fehler}"
        ergebnis["quality"] = (QUALITY_STALE_FALLBACK if alt_raw
                               else QUALITY_PROVIDER_ERROR)
        ergebnis["quality_reason"] = ("Abruf gescheitert, vorhandener Stand "
                                      "bleibt unveraendert")
        return ergebnis

    except Exception as fehler:                        # pragma: no cover
        ergebnis["error"] = f"unerwarteter Fehler: {fehler}"
        ergebnis["quality"] = QUALITY_PROVIDER_ERROR
        ergebnis["quality_reason"] = "Abruf gescheitert"
        return ergebnis

    gueltig, begruendung = validate_profile(neu_raw, player_id, season)
    if not gueltig:
        # Der entscheidende Schutz: Eine ungueltige Antwort ersetzt
        # NICHTS. Der alte Cacheeintrag steht noch auf der Platte -
        # disk_cached_call hat ihn nur uebergangen, nicht geloescht.
        ergebnis["error"] = f"Antwort abgewiesen: {begruendung}"
        ergebnis["quality"] = (QUALITY_STALE_FALLBACK if alt_raw
                               else QUALITY_PROVIDER_ERROR)
        ergebnis["quality_reason"] = begruendung
        return ergebnis

    ergebnis["ok"] = True
    ergebnis["new_fetched_at"] = (disk_cache.get_meta(schluessel) or {}).get(
        "fetched_at") if not dry_run else "(nicht geschrieben)"

    zustand, grund = classify_profile_quality(neu_raw)
    ergebnis["quality"] = zustand
    ergebnis["quality_reason"] = grund

    # Name und Verein aus der frischen Antwort ergaenzen, falls lokal
    # nichts bekannt war.
    spieler = neu_raw.get("player") or {}
    ergebnis["name"] = ergebnis["name"] or spieler.get("name")

    neuer_eintrag = build_entry_from_raw(neu_raw, season,
                                         herkunft.get("league_code"))
    ergebnis["new_minutes"] = _minutes_by_scope(neuer_eintrag)
    ergebnis["team_name"] = (ergebnis["team_name"]
                             or (neuer_eintrag or {}).get("team_name"))
    ergebnis["changed"] = ergebnis["old_minutes"] != ergebnis["new_minutes"]

    if dry_run or not update_pool:
        return ergebnis

    if neuer_eintrag is None:
        # Kein Vereinsblock. Der Spieler bleibt ueber den Kaderindex
        # auffindbar; sein bisheriger Pooleintrag wird NICHT geloescht.
        # Ihn zu entfernen hiesse, eine Anbieterluecke in einen
        # Datenverlust zu verwandeln.
        ergebnis["quality_reason"] += " - Pooleintrag bleibt unveraendert"
        return ergebnis

    if not herkunft.get("league_code"):
        ergebnis["quality_reason"] += (" - keine Liga aufloesbar, "
                                       "Pool nicht aktualisiert")
        return ergebnis

    ergebnis["pool_updated"] = _update_pool_entry(
        herkunft["league_code"], season, neuer_eintrag,
        zustand, grund,
        (disk_cache.get_meta(schluessel) or {}).get("fetched_at"),
    )
    return ergebnis


def _update_pool_entry(league_code, season, eintrag, zustand, grund, fetched_at):
    """
    Ersetzt genau EINEN Spieler im Pool und schreibt ihn atomar.

    Alle uebrigen Eintraege werden unveraendert durchgereicht - nicht neu
    berechnet, nicht neu sortiert, nicht angefasst. Ein gezielter Refresh
    darf keine Nebenwirkung auf Spieler haben, nach denen niemand gefragt
    hat.

    Der Statuseintrag der Liga wird bewusst NICHT angefasst: Ein einzelner
    erneuerter Spieler macht aus einem unvollstaendigen Pool keinen
    vollstaendigen.
    """
    from src.data.player_pool import read_pool, write_pool

    pool = read_pool(league_code, season)
    spieler = list(pool.get("players") or [])

    eintrag = dict(eintrag)
    eintrag["data_quality"] = quality_block(
        zustand, grund, fetched_at=fetched_at,
        source="api-football.com/players",
    )

    pid = eintrag.get("player_id")
    for i, vorhanden in enumerate(spieler):
        if vorhanden.get("player_id") == pid:
            spieler[i] = eintrag
            break
    else:
        spieler.append(eintrag)

    pool["players"] = spieler
    write_pool(pool)
    return True


def refetch_many(player_ids, season, dry_run=False, throttle_seconds=0.0,
                 fetch=None, progress=None):
    """
    Mehrere Spieler nacheinander erneuern.

    Ein Teilfehler beendet den Lauf NICHT: Wer drei Spieler nennt und beim
    zweiten auf ein Rate Limit laeuft, soll den dritten trotzdem bekommen
    und am Ende sehen, was gelungen ist. Nur ein Rate Limit bricht ab -
    weitere Anfragen waeren nach einer Ablehnung ohnehin zwecklos und
    wuerden das Limit weiter belasten.

    Rueckgabe: (ergebnisse, zusammenfassung).
    """
    ergebnisse = []
    abgebrochen = False

    for pid in player_ids:
        ergebnis = refetch_player(pid, season, dry_run=dry_run,
                                  throttle_seconds=throttle_seconds,
                                  fetch=fetch)
        ergebnisse.append(ergebnis)
        if progress:
            progress(ergebnis)

        if (ergebnis.get("error") or "").startswith("Rate Limit"):
            abgebrochen = True
            break

    zusammenfassung = {
        "angefragt": len(player_ids),
        "bearbeitet": len(ergebnisse),
        "erfolgreich": sum(1 for e in ergebnisse if e["ok"]),
        "fehlgeschlagen": sum(1 for e in ergebnisse if not e["ok"]),
        "pool_aktualisiert": sum(1 for e in ergebnisse if e["pool_updated"]),
        "veraendert": sum(1 for e in ergebnisse if e["changed"]),
        "requests": sum(e["requests"] for e in ergebnisse),
        "abgebrochen": abgebrochen,
        "dry_run": bool(dry_run),
    }
    return ergebnisse, zusammenfassung
