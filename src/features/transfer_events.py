"""
Transferereignisse in eine einheitliche, zeitlich saubere Form bringen.

DIE ROHDATEN
------------
API-Sports liefert Transfers nach SPIELER gruppiert, nicht nach Team:

    {"player": {"id": 113917, "name": "..."},
     "transfers": [{"date": "2010-01-05", "type": "Free",
                    "teams": {"in":  {"id": 106, "name": "..."},
                              "out": {"id": 20139, "name": "..."}}}]}

Lokal liegen 155 Teamdateien mit zusammen 106.707 Transferereignissen zu
24.404 Spielern (data/cache/apisports__transfers__team__*.json).

"in" ist der aufnehmende, "out" der abgebende Verein. Diese Richtung ist
die einzige verlaessliche Angabe - der Dateiname sagt nichts darueber,
ob der Transfer fuer dieses Team ein Zu- oder ein Abgang war.

DIE TYPEN
---------
Gemessene Haeufigkeiten ueber alle lokalen Dateien:

    Loan               33.207      Return from loan    3.547
    N/A                27.666      Free agent          3.153
    Free               16.975      Back from Loan      1.294
    Transfer            5.315      Free Transfer         789
    Betragsangaben     ca. 4.000   "-"                   533

Betragsangaben wie "€ 3M" werden ausdruecklich NUR als Beleg dafuer
gelesen, dass es ein fester Transfer war. Die SUMME wird nicht
uebernommen und nirgends verwendet: Eine Ablosesumme ist ein
Marktpreis, kein Leistungsmass, und dieser Auftrag verbietet ihre
Verwendung ebenso wie Marktwerte.

WAS HIER NICHT PASSIERT
-----------------------
Keine Bewertung. Dieses Modul stellt nur fest, WAS wann WOHIN passiert
ist. Wie stark ein Transfer wirkt, entscheidet src/features/go5.py aus
Importance und Quality.
"""

from datetime import date, datetime


#: Normalisierte Transferarten.
TRANSFER_TYPES = ("permanent", "loan", "loan_return", "unknown")

#: Providerbegriffe je Art. Reihenfolge der Pruefung ist Absicht:
#: "Return from loan" enthaelt "loan" und muss deshalb VOR der reinen
#: Leihe erkannt werden.
LOAN_RETURN_TOKENS = ("return from loan", "back from loan", "loan return",
                      "end of loan")
LOAN_TOKENS = ("loan",)
PERMANENT_TOKENS = ("transfer", "free", "signed", "permanent")

#: Angaben, die nichts ueber die Art aussagen.
UNKNOWN_TOKENS = ("n/a", "-", "", "none")


def normalize_type(raw_type):
    """
    Providerangabe auf eine der vier Arten abbilden.

    Eine Betragsangabe ("€ 3M") gilt als fester Transfer - dass ueberhaupt
    eine Summe genannt wird, belegt einen Kauf. Der Betrag selbst wird
    nicht ausgewertet.
    """
    text = (str(raw_type) if raw_type is not None else "").strip().lower()
    if not text or text in UNKNOWN_TOKENS:
        return "unknown"

    if any(token in text for token in LOAN_RETURN_TOKENS):
        return "loan_return"
    if any(token in text for token in LOAN_TOKENS):
        return "loan"
    if any(token in text for token in PERMANENT_TOKENS):
        return "permanent"

    # Waehrungszeichen oder Ziffern: eine Ablosesumme. Nur die Tatsache
    # zaehlt, nicht die Hoehe.
    if any(zeichen in text for zeichen in ("€", "$", "£")) or any(
            c.isdigit() for c in text):
        return "permanent"

    return "unknown"


def parse_date(raw):
    """Transferdatum als date, oder None. Ein unlesbares Datum ist None."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw)[:10]
    try:
        jahr, monat, tag = (int(t) for t in text.split("-")[:3])
        return date(jahr, monat, tag)
    except (ValueError, TypeError):
        return None


def season_of(transfer_date, season_start_month=7):
    """
    Zu welcher Saison gehoert ein Transferdatum?

    Ein Wechsel im Januar 2025 gehoert zur Saison 2024 (2024/25), einer
    im August 2025 zur Saison 2025. Der Schnitt liegt im Juli, weil dort
    die Sommerpause endet und die neue Spielzeit beginnt - dieselbe
    Konvention, die das Projekt fuer Saisonjahre benutzt
    (Anfangsjahr = Saisonname).
    """
    if transfer_date is None:
        return None
    return transfer_date.year if transfer_date.month >= season_start_month \
        else transfer_date.year - 1


def normalize_transfer(player, raw_transfer, known_team_ids=None):
    """
    Ein Rohereignis in einen normalisierten Eintrag.

    known_team_ids: Menge der API-Sports-Team-IDs, die FootSim kennt.
        Ist sie gesetzt, wird vermerkt, ob abgebender und aufnehmender
        Verein zugeordnet werden konnten. Ein Transfer zwischen zwei
        unbekannten Vereinen bleibt wirkungslos - aber er wird
        aufgezeichnet, statt stillschweigend zu verschwinden.

    Rueckgabe: dict mit allen geforderten Feldern, oder None wenn nicht
    einmal ein Spieler oder ein Datum feststellbar ist.
    """
    pid = (player or {}).get("id")
    if pid is None:
        return None

    teams = (raw_transfer or {}).get("teams") or {}
    hinein = teams.get("in") or {}
    heraus = teams.get("out") or {}

    datum = parse_date(raw_transfer.get("date"))
    if datum is None:
        # Ohne Datum laesst sich nicht entscheiden, ob der Transfer vor
        # dem Zielspiel lag. Das ist der Kern der Punkt-in-Zeit-Regel -
        # ein solches Ereignis ist unbrauchbar, nicht "vermutlich alt".
        return None

    zu_id = hinein.get("id")
    von_id = heraus.get("id")

    if known_team_ids is None:
        zu_gemappt = zu_id is not None
        von_gemappt = von_id is not None
    else:
        zu_gemappt = zu_id is not None and int(zu_id) in known_team_ids
        von_gemappt = von_id is not None and int(von_id) in known_team_ids

    art = normalize_type(raw_transfer.get("type"))

    if art == "unknown":
        qualitaet = "partial"
    elif zu_gemappt or von_gemappt:
        qualitaet = "complete"
    else:
        qualitaet = "fallback"

    return {
        "player_id": int(pid),
        "player_name": (player or {}).get("name"),
        "date": datum.isoformat(),
        "season": season_of(datum),
        "from_team_id": int(von_id) if von_id is not None else None,
        "from_team_name": heraus.get("name"),
        "to_team_id": int(zu_id) if zu_id is not None else None,
        "to_team_name": hinein.get("name"),
        "transfer_type": art,
        "mapped_from_team": bool(von_gemappt),
        "mapped_to_team": bool(zu_gemappt),
        "source": "api-football.com/transfers",
        "data_quality": qualitaet,
    }


def _dedup_key(eintrag):
    """
    Was denselben Transfer ausmacht.

    Bewusst OHNE die Art: derselbe Wechsel wird von der Quelle mal als
    "Transfer", mal als "N/A" und mal mit Betrag gefuehrt. Nach Spieler,
    Datum und beiden Vereinen ist er eindeutig bestimmt.
    """
    return (eintrag["player_id"], eintrag["date"],
            eintrag["from_team_id"], eintrag["to_team_id"])


def load_transfer_events(known_team_ids=None, cache_dir=None):
    """
    Alle lokal vorhandenen Transferereignisse, normalisiert und dedupliziert.

    Liest ausschliesslich den vorhandenen Disk-Cache - kein Netzzugriff,
    auch nicht beim ersten Aufruf.

    Rueckgabe: (eintraege, diagnose)
    """
    import glob
    import json
    import os

    if cache_dir is None:
        from src.utils.disk_cache import CACHE_DIR
        cache_dir = CACHE_DIR

    muster = os.path.join(cache_dir, "apisports__transfers__team__*.json")

    gesehen = set()
    eintraege = []
    diagnose = {
        "files": 0, "raw_events": 0, "normalized": 0, "duplicates": 0,
        "without_date": 0, "without_player": 0,
        "by_type": {}, "unmapped_both_sides": 0,
    }

    for pfad in sorted(glob.glob(muster)):
        diagnose["files"] += 1
        try:
            with open(pfad, "r", encoding="utf-8") as datei:
                inhalt = json.load(datei)
        except (OSError, ValueError):
            # Eine beschaedigte Cachedatei darf den Rest nicht verhindern.
            continue

        for block in (inhalt.get("payload") or []):
            spieler = block.get("player") or {}
            if spieler.get("id") is None:
                diagnose["without_player"] += 1
                continue

            for roh in (block.get("transfers") or []):
                diagnose["raw_events"] += 1
                eintrag = normalize_transfer(spieler, roh, known_team_ids)
                if eintrag is None:
                    diagnose["without_date"] += 1
                    continue

                schluessel = _dedup_key(eintrag)
                if schluessel in gesehen:
                    diagnose["duplicates"] += 1
                    continue
                gesehen.add(schluessel)

                eintraege.append(eintrag)
                diagnose["normalized"] += 1
                art = eintrag["transfer_type"]
                diagnose["by_type"][art] = diagnose["by_type"].get(art, 0) + 1
                if not eintrag["mapped_from_team"] and not eintrag["mapped_to_team"]:
                    diagnose["unmapped_both_sides"] += 1

    eintraege.sort(key=lambda e: (e["date"], e["player_id"]))
    return eintraege, diagnose


def transfers_before(events, cutoff_date, team_id=None):
    """
    Transfers STRIKT vor dem Stichtag.

    Der Kern der Punkt-in-Zeit-Regel fuer GO 5: Ein Wechsel, der am Tag
    des Zielspiels oder spaeter bekannt wird, darf dieses Spiel nicht
    beeinflussen. Strikt kleiner, weil ein Spieler, der am Spieltag
    wechselt, fuer dieses Spiel nicht mehr zur Verfuegung stand.
    """
    if cutoff_date is None:
        return []

    grenze = parse_date(cutoff_date)
    if grenze is None:
        return []

    ergebnis = []
    for eintrag in events or []:
        datum = parse_date(eintrag["date"])
        if datum is None or datum >= grenze:
            continue
        if team_id is not None:
            if eintrag["to_team_id"] != team_id and eintrag["from_team_id"] != team_id:
                continue
        ergebnis.append(eintrag)
    return ergebnis


def team_window_transfers(events, team_id, cutoff_date, season,
                          window_days=365):
    """
    Die fuer EIN Team und EIN Zielspiel bedeutsamen Transfers.

    Zwei Filter, beide notwendig:

      1. Vor dem Zielspiel (Punkt-in-Zeit).
      2. Innerhalb der letzten window_days - ein Wechsel von 2019 sagt
         ueber die Aufstellung von 2025 nichts mehr. Ohne dieses Fenster
         wuerden 106.707 Ereignisse aus zwei Jahrzehnten in jede
         Rechnung eingehen.

    Rueckgabe: (zugaenge, abgaenge)
    """
    from datetime import timedelta

    grenze = parse_date(cutoff_date)
    if grenze is None:
        return [], []

    frueheste = grenze - timedelta(days=window_days)

    zugaenge = []
    abgaenge = []
    for eintrag in transfers_before(events, cutoff_date, team_id):
        datum = parse_date(eintrag["date"])
        if datum is None or datum < frueheste:
            continue
        if eintrag["to_team_id"] == team_id:
            zugaenge.append(eintrag)
        elif eintrag["from_team_id"] == team_id:
            abgaenge.append(eintrag)

    return zugaenge, abgaenge


def build_team_index(events):
    """
    Transfers nach beteiligtem Verein indizieren.

    Ohne Index muesste jede Abfrage alle 84.943 Ereignisse durchlaufen.
    Bei einem Backtest ueber mehrere Ligen und Saisons sind das
    Milliarden von Vergleichen - der erste Entwurf lief deshalb in eine
    Zeitueberschreitung.

    Ein Transfer steht unter BEIDEN Vereinen, weil er fuer den einen ein
    Zugang und fuer den anderen ein Abgang ist.
    """
    index = {}
    for eintrag in events or []:
        for schluessel in ("to_team_id", "from_team_id"):
            tid = eintrag.get(schluessel)
            if tid is not None:
                index.setdefault(int(tid), []).append(eintrag)
    for eintraege in index.values():
        eintraege.sort(key=lambda e: e["date"])
    return index


def team_window_transfers_indexed(index, team_id, cutoff_date, season,
                                  window_days=365):
    """
    Wie team_window_transfers, aber ueber den Index von build_team_index.

    Gleiches Ergebnis, ohne den vollstaendigen Durchlauf. Die
    Punkt-in-Zeit-Regel ist identisch: strikt vor dem Stichtag.
    """
    from datetime import timedelta

    grenze = parse_date(cutoff_date)
    if grenze is None or team_id is None:
        return [], []

    frueheste = grenze - timedelta(days=window_days)
    zugaenge = []
    abgaenge = []

    for eintrag in index.get(int(team_id)) or []:
        datum = parse_date(eintrag["date"])
        if datum is None or datum >= grenze or datum < frueheste:
            continue
        if eintrag["to_team_id"] == team_id:
            zugaenge.append(eintrag)
        elif eintrag["from_team_id"] == team_id:
            abgaenge.append(eintrag)

    return zugaenge, abgaenge
