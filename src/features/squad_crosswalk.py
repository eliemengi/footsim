"""
football-data-Kennung -> API-Sports-Kennung fuer CL-Vereine (V2-C7).

DAS PROBLEM
-----------
Die Champions-League-Historie stammt von football-data.org und traegt
deren Team-Kennungen. Die Transferereignisse und der Spielerpool
stammen von API-Sports und tragen deren Kennungen. Es sind verschiedene
Zahlen fuer denselben Verein.

Wer sie gleichsetzt, bekommt lauter plausible Werte ueber einen
fremden Verein - und merkt es nie. Genau das hat eine Probe im Vorfeld
gezeigt: Eine naive Gleichsetzung "traf" 55 von 63 CL-Vereinen, aber
die Treffer waren zufaellige Kollisionen zweier Nummernkreise, keine
Zuordnungen.

DIE ZWEI QUELLEN DER BRUECKE
----------------------------
    V2-C2B (27 Vereine)
        match_timeline.CL_PARTICIPANT_CROSSWALK. Dort wurden die
        Teilnehmer ausserhalb der Top 5 einzeln aufgeloest und
        gegengeprueft. Diese Tabelle wird uebernommen, nicht neu
        gebaut.

    Nationale Pokaldateien (die uebrigen 36)
        DFB, FAC, CDR, CIT, CDF stammen von API-Sports und enthalten
        die Top-5-Vereine mit deren Kennungen. team_crosswalk.build_
        crosswalk gleicht sie INNERHALB derselben Wettbewerbssaison
        gegen die football-data-Namen ab - derselbe Mechanismus wie in
        V2-C2, mit denselben Sicherungen gegen unscharfe Treffer.

Nachgemessen: 63 von 63 CL-Vereinen der Saisons 2023 bis 2025 loesen
sich damit auf.

WIDERSPRUECHE BRECHEN AB
------------------------
Liefern zwei Quellen fuer dieselbe football-data-Kennung verschiedene
API-Sports-Kennungen, ist das ein Datenfehler und keine Ermessensfrage.
Er wird gemeldet und der Eintrag verworfen - eine von beiden waere
falsch, und es gibt keinen Grund, die richtige zu erraten.
"""

import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HISTORICAL_DIR = os.path.join(_PROJECT_ROOT, "data", "historical")

#: Pokalwettbewerb -> Liga, deren Vereine er enthaelt.
CUP_TO_LEAGUE = {"dfb": "bl1", "fac": "pl", "cdr": "pd",
                 "cit": "sa", "cdf": "fl1"}

#: Saisons, aus denen die Bruecke gebaut wird.
CROSSWALK_SEASONS = (2023, 2024, 2025)

#: Herkunft eines Eintrags - sie steht in der Diagnose.
ORIGIN_C2B = "v2c2b_cl_participant_crosswalk"

#: Konfidenz. Die C2B-Tabelle wurde einzeln gegengeprueft; die
#: Pokalableitung laeuft ueber den bestehenden, abgesicherten
#: Namensabgleich innerhalb einer Wettbewerbssaison.
CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_DERIVED = "derived_within_competition_season"


def build_team_crosswalk(seasons=CROSSWALK_SEASONS, directory=None):
    """
    Die Bruecke football-data -> API-Sports.

    Rueckgabe: (mapping, diagnose).

    mapping: {football_data_id: apisports_id}
    diagnose: Herkunft und Konfidenz je Eintrag, plus die Widersprueche.
    """
    from src.features.match_timeline import CL_PARTICIPANT_CROSSWALK
    from src.features.team_crosswalk import build_crosswalk

    directory = directory or HISTORICAL_DIR

    mapping = {}
    herkunft = {}
    widersprueche = []

    for fd_id, as_id in CL_PARTICIPANT_CROSSWALK.items():
        mapping[int(fd_id)] = int(as_id)
        herkunft[int(fd_id)] = {"origin": ORIGIN_C2B,
                                "confidence": CONFIDENCE_VERIFIED}

    for cup, liga in sorted(CUP_TO_LEAGUE.items()):
        for saison in seasons:
            pfad = os.path.join(directory, f"{cup.upper()}_{saison}.json")
            if not os.path.exists(pfad):
                continue
            try:
                with open(pfad, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                continue

            as_teams = {}
            for roh_id, info in (payload.get("teams") or {}).items():
                try:
                    as_teams[int(roh_id)] = (info or {}).get("name")
                except (TypeError, ValueError):
                    continue

            ergebnis = build_crosswalk(liga, saison, as_teams)
            for as_id, fd_id in (ergebnis.get("mapping") or {}).items():
                if fd_id is None:
                    continue
                fd_id, as_id = int(fd_id), int(as_id)
                vorhanden = mapping.get(fd_id)
                if vorhanden is None:
                    mapping[fd_id] = as_id
                    herkunft[fd_id] = {"origin": f"{cup}_{saison}",
                                       "confidence": CONFIDENCE_DERIVED}
                elif vorhanden != as_id:
                    # Zwei Quellen, zwei Antworten. Eine davon ist
                    # falsch, und Raten ist hier nicht zulaessig.
                    widersprueche.append({
                        "football_data_id": fd_id,
                        "existing": vorhanden, "conflicting": as_id,
                        "existing_origin": herkunft[fd_id]["origin"],
                        "conflicting_origin": f"{cup}_{saison}"})

    for eintrag in widersprueche:
        # Ein widerspruechlicher Eintrag wird ENTFERNT, nicht
        # ueberschrieben: Unbekannt ist besser als vielleicht falsch.
        mapping.pop(eintrag["football_data_id"], None)
        herkunft.pop(eintrag["football_data_id"], None)

    umkehr = {}
    doppelte_ziele = []
    for fd_id, as_id in mapping.items():
        if as_id in umkehr:
            doppelte_ziele.append({"apisports_id": as_id,
                                   "football_data_ids": [umkehr[as_id], fd_id]})
        umkehr[as_id] = fd_id

    return mapping, {
        "entries": len(mapping),
        "by_confidence": {
            CONFIDENCE_VERIFIED: sum(1 for h in herkunft.values()
                                     if h["confidence"] == CONFIDENCE_VERIFIED),
            CONFIDENCE_DERIVED: sum(1 for h in herkunft.values()
                                    if h["confidence"] == CONFIDENCE_DERIVED),
        },
        "origins": {str(fd): h for fd, h in sorted(herkunft.items())},
        "conflicts": widersprueche,
        "duplicate_targets": doppelte_ziele,
        "note": ("Zwei Vereine auf derselben API-Sports-Kennung waeren ein "
                 "Datenfehler - sie wuerden sich ihre Transferhistorie "
                 "teilen. duplicate_targets nennt solche Faelle."),
    }


def cl_team_coverage(mapping, seasons=CROSSWALK_SEASONS, directory=None):
    """
    Wie viele CL-Vereine loesen sich auf - und welche nicht?

    Die Frage gehoert ins Artefakt: Ein nicht aufgeloester Verein
    bekommt keine C7-Merkmale, und das muss sichtbar sein statt als
    stille Luecke durchzulaufen.
    """
    directory = directory or HISTORICAL_DIR

    alle, namen = set(), {}
    for saison in seasons:
        pfad = os.path.join(directory, f"CL_{saison}.json")
        if not os.path.exists(pfad):
            continue
        try:
            with open(pfad, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        for roh_id, info in (payload.get("teams") or {}).items():
            try:
                tid = int(roh_id)
            except (TypeError, ValueError):
                continue
            alle.add(tid)
            namen[tid] = (info or {}).get("name")

    aufgeloest = alle & set(mapping)
    fehlend = sorted(alle - set(mapping))
    return {
        "cl_teams_total": len(alle),
        "resolved": len(aufgeloest),
        "resolved_pct": (round(100.0 * len(aufgeloest) / len(alle), 2)
                         if alle else 0.0),
        "unresolved": [{"football_data_id": tid, "name": namen.get(tid)}
                       for tid in fehlend],
    }
