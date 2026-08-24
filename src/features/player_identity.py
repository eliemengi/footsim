"""
Identitaet von Spielern und Vereinen fuer GO 4 und GO 5.

WARUM DAS ZUERST KOMMT
----------------------
Player Importance, Kaderverfuegbarkeit und Transferwirkung haengen alle
daran, dass ein Spieler und sein Verein sicher erkannt werden. Eine
Verwechslung waere hier nicht ein ungenauer Wert, sondern ein falscher:
Faellt "der falsche Mueller" aus, bekommt das falsche Team einen Malus.

Dieses Modul ERWEITERT src/features/team_crosswalk.py (GO 3), es baut
keinen zweiten Crosswalk daneben. Die Vereinszuordnung kommt weiterhin
von dort; hier kommt die Spielerseite und die Aufloesung von
API-Sports-Teamnamen zu API-Sports-Team-IDs hinzu.

SPIELER: DIE ID IST DIE IDENTITAET
----------------------------------
Alle drei Quellen, die GO 4 und GO 5 brauchen, stammen von API-Sports
und fuehren dieselbe stabile Spieler-ID:

    Spielerpool     data/player_pool/pool_<liga>_<saison>.json
    Verletzungen    /injuries
    Transfers       /players/transfers

Damit ist Prioritaet 1 der geforderten Reihenfolge - stabile
Provider-ID - praktisch immer erfuellt. Namensabgleich ist der
Notbehelf, nicht der Regelfall.

Der Pool fuehrt KEIN Geburtsdatum, nur ein Alter. Ein Namensabgleich
liesse sich also nur ueber Name plus Alter plus Position stuetzen. Das
reicht fuer eine Diagnose, nicht fuer eine produktive Zuordnung -
deshalb liefert resolve_player_by_name() ausdruecklich Vorschlaege und
niemals eine stille Zuordnung.

DIE TEAMFALLE IM SPIELERPOOL
----------------------------
Der Pool fuehrt team_name, aber KEINE team_id - und team_name ist der
Verein zum Zeitpunkt des Imports, nicht der Verein in jener Saison.
Nachgemessen:

    pool_bl1_2020.json   82 verschiedene Teamnamen (statt 18)
    pool_bl1_2023.json  174 verschiedene Teamnamen
    pool_bl1_2025.json   91 verschiedene Teamnamen

darunter Chelsea, Juventus, Inter, Arsenal. Das sind Spieler, die
inzwischen woanders spielen.

Folge, und sie ist bindend: Der Pool taugt fuer die AKTUELLE
Kaderzugehoerigkeit (dort stimmt team_name per Konstruktion), aber
NICHT als historische Kaderzuordnung. Wer ihn rueckwirkend so benutzt,
setzt heutige Kader in vergangene Spiele ein - genau das Leck, das
dieser Auftrag verbietet. is_historical_squad_known() haelt das fest.
"""

import unicodedata

from src.features.team_crosswalk import _normalize as _normalize_team


#: Positionsgruppen, wie API-Sports sie fuehrt. Mehr gibt es dort nicht -
#: eine feinere Rollenaufteilung (Innen-/Aussenverteidiger, Sechser/
#: Zehner) waere erfunden.
POSITION_GROUPS = ("Goalkeeper", "Defender", "Midfielder", "Attacker")

#: Wie sicher eine Zuordnung ist. Nur "provider_id" und "crosswalk"
#: duerfen produktiv wirken.
CONFIDENCE_LEVELS = ("provider_id", "crosswalk", "alias", "suggested", "none")

#: Zuordnungen ab dieser Stufe wirken. Alles darunter ist Diagnose.
PRODUCTIVE_CONFIDENCE = ("provider_id", "crosswalk", "alias")


def _fold(text):
    """Akzente falten und kleinschreiben - fuer Namensvergleiche."""
    if not text:
        return ""
    zerlegt = unicodedata.normalize("NFKD", str(text))
    ohne = "".join(c for c in zerlegt if not unicodedata.combining(c))
    return " ".join(ohne.lower().split())


def normalize_player_name(name):
    """
    Spielername in eine vergleichbare Form.

    API-Sports kuerzt Vornamen haeufig ab ("B. Oczipka"). Der Punkt
    entfaellt, der Rest bleibt stehen - ein abgekuerzter Vorname darf
    NICHT weggeworfen werden, sonst faellt der Unterschied zwischen
    zwei gleichnamigen Bruedern weg.
    """
    gefaltet = _fold(name)
    return " ".join(t.rstrip(".") for t in gefaltet.split() if t.rstrip("."))


def is_productive(confidence):
    """Darf eine Zuordnung dieser Sicherheit die Simulation beeinflussen?"""
    return confidence in PRODUCTIVE_CONFIDENCE


# ---------------------------------------------------------------------------
# Spieler
# ---------------------------------------------------------------------------

def resolve_player(player_id, name=None):
    """
    Spieleridentitaet aus der Provider-ID.

    Rueckgabe:
        {"player_id":, "name":, "confidence":, "source":}

    Ohne ID gibt es keine produktive Identitaet. Das ist streng und
    gewollt: Ein Spieler ohne ID ist ein Spieler, den wir nicht sicher
    kennen, und der darf keine Teamstaerke veraendern.
    """
    if player_id is None:
        return {"player_id": None, "name": name,
                "confidence": "none", "source": "missing_id"}
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return {"player_id": None, "name": name,
                "confidence": "none", "source": "unparsable_id"}

    return {"player_id": pid, "name": name,
            "confidence": "provider_id", "source": "apisports_player_id"}


def build_player_index(pool_players):
    """
    Nachschlagewerk ueber die Spieler eines Pools.

    Rueckgabe:
        {"by_id": {id: spieler}, "by_name": {norm_name: [spieler, ...]},
         "duplicate_names": [norm_name, ...]}

    Gleichnamige Spieler landen bewusst gemeinsam unter einem
    Namensschluessel - so ist die Mehrdeutigkeit sichtbar, statt dass
    einer den anderen ueberschreibt.
    """
    by_id = {}
    by_name = {}
    for spieler in pool_players or []:
        pid = spieler.get("player_id")
        if pid is not None:
            by_id[int(pid)] = spieler
        norm = normalize_player_name(spieler.get("name"))
        if norm:
            by_name.setdefault(norm, []).append(spieler)

    doppelt = sorted(n for n, eintraege in by_name.items() if len(eintraege) > 1)
    return {"by_id": by_id, "by_name": by_name, "duplicate_names": doppelt}


def resolve_player_by_name(index, name, position=None, age=None):
    """
    Namensbasierte Aufloesung - AUSDRUECKLICH NUR ALS VORSCHLAG.

    Rueckgabe: {"player_id":, "confidence": "suggested"|"none",
                "candidates": [...], "reason":}

    Auch bei genau einem Treffer bleibt die Stufe "suggested". Der Pool
    fuehrt kein Geburtsdatum; Name plus Alter plus Position kann zwei
    Spieler nicht sicher trennen. Diese Funktion existiert fuer die
    Diagnose - welche Kadermitglieder haben keine Statistik? - und
    nicht, um eine fehlende ID zu ersetzen.
    """
    norm = normalize_player_name(name)
    kandidaten = list((index.get("by_name") or {}).get(norm) or [])

    if position:
        gefiltert = [k for k in kandidaten if k.get("position") == position]
        if gefiltert:
            kandidaten = gefiltert
    if age is not None:
        gefiltert = [k for k in kandidaten if k.get("age") == age]
        if gefiltert:
            kandidaten = gefiltert

    if not kandidaten:
        return {"player_id": None, "confidence": "none",
                "candidates": [], "reason": "no_match"}
    if len(kandidaten) > 1:
        return {"player_id": None, "confidence": "none",
                "candidates": [k.get("player_id") for k in kandidaten],
                "reason": "ambiguous"}

    return {"player_id": kandidaten[0].get("player_id"),
            "confidence": "suggested",
            "candidates": [kandidaten[0].get("player_id")],
            "reason": "unique_name_match"}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

def build_team_name_index(apisports_teams):
    """
    API-Sports-Teamnamen zu API-Sports-Team-IDs, innerhalb einer Liga.

    apisports_teams: {team_id: name}

    Benutzt dieselbe Normalisierung wie der GO-3-Crosswalk, damit beide
    Seiten dieselbe Vorstellung von "gleicher Name" haben. Mehrdeutige
    Namen werden gemeldet und NICHT zugeordnet.
    """
    nach_name = {}
    for tid, name in (apisports_teams or {}).items():
        norm = _normalize_team(name)
        if norm:
            nach_name.setdefault(norm, []).append(int(tid))

    return {
        "by_name": {n: ids for n, ids in nach_name.items() if len(ids) == 1},
        "ambiguous": {n: ids for n, ids in nach_name.items() if len(ids) > 1},
    }


def resolve_team_name(index, name):
    """
    Teamname zu API-Sports-ID.

    Rueckgabe: {"team_id":, "confidence":, "reason":}

    Mehrdeutig heisst nicht zugeordnet. Ein falsch zugeordneter Verein
    ist schaedlicher als ein fehlender.
    """
    norm = _normalize_team(name)
    if not norm:
        return {"team_id": None, "confidence": "none", "reason": "empty_name"}
    if norm in (index.get("ambiguous") or {}):
        return {"team_id": None, "confidence": "none", "reason": "ambiguous"}

    treffer = (index.get("by_name") or {}).get(norm)
    if treffer:
        return {"team_id": treffer[0], "confidence": "crosswalk",
                "reason": "normalized_name_in_league"}
    return {"team_id": None, "confidence": "none", "reason": "no_match"}


def is_historical_squad_known(as_of=None, has_snapshot=False):
    """
    Duerfen wir fuer diesen Zeitpunkt eine Kaderzugehoerigkeit behaupten?

    Nur zwei Faelle sind zulaessig:

      1. Kein Stichtag (as_of=None) - es geht um JETZT. Der Spielerpool
         fuehrt den aktuellen Verein, das ist belegt.
      2. Es gibt einen archivierten Kaderstand am oder vor dem Stichtag.

    Alles andere ist unbekannt. Der Pool rueckwirkend zu verwenden waere
    ein Leck (siehe Modulkopf) - deshalb gibt es hier kein "wird schon
    stimmen".
    """
    if as_of is None:
        return True
    return bool(has_snapshot)


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------

def identity_report(pool_players, squad_player_ids=None, injury_player_ids=None,
                    transfer_player_ids=None):
    """
    Wie gut sind Spieler und Teams erfasst?

    Beantwortet ausdruecklich die vom Auftrag geforderten Fragen:
    Kadermitglieder ohne Statistik, Statistiken ohne Kaderzuordnung,
    gleichnamige Spieler, fehlende IDs.

    Enthaelt nur Zahlen und IDs - keine Pfade, keine Schluessel.
    """
    index = build_player_index(pool_players)
    pool_ids = set(index["by_id"])

    ohne_id = sum(1 for p in (pool_players or []) if p.get("player_id") is None)
    positionen = {}
    for spieler in pool_players or []:
        pos = spieler.get("position") or "unknown"
        positionen[pos] = positionen.get(pos, 0) + 1

    bericht = {
        "pool_players": len(pool_players or []),
        "pool_with_id": len(pool_ids),
        "pool_without_id": ohne_id,
        "duplicate_names": len(index["duplicate_names"]),
        "duplicate_name_examples": index["duplicate_names"][:5],
        "by_position": positionen,
        "unknown_position": positionen.get("unknown", 0),
    }

    if squad_player_ids is not None:
        kader = {int(p) for p in squad_player_ids if p is not None}
        bericht["squad_players"] = len(kader)
        bericht["squad_without_stats"] = len(kader - pool_ids)
        bericht["stats_without_squad"] = len(pool_ids - kader)

    if injury_player_ids is not None:
        verletzt = {int(p) for p in injury_player_ids if p is not None}
        bericht["injury_entries"] = len(verletzt)
        bericht["injuries_without_stats"] = len(verletzt - pool_ids)

    if transfer_player_ids is not None:
        transfers = {int(p) for p in transfer_player_ids if p is not None}
        bericht["transfer_players"] = len(transfers)
        bericht["transfers_without_stats"] = len(transfers - pool_ids)

    return bericht
