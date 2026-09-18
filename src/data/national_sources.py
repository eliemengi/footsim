"""
Die nationalen Profilquellen (V2-C13).

WARUM ES DIESE DATEI GIBT
-------------------------
Der Profilpfad las bis C13 genau fuenf Ligadateien:

    historical_loader.LEAGUE_CODES = {bl1, pl, pd, sa, fl1}

Lokal liegen aber 23 weitere Wettbewerbe. Die Folge war messbar: 321
von 1006 Teamseiten der Champions League bekamen kein nationales
Profil, sondern eines aus 1 bis 27 CL-Partien. In V2-C12 kostete genau
diese Gruppe die Freigabe.

Diese Datei sagt zentral und nachpruefbar, WELCHE Wettbewerbe als
nationale Profilquelle zugelassen sind, und aus WELCHEM Namensraum
ihre Team-IDs stammen.

KEINE GLOB-LOGIK
----------------
Die Liste steht ausgeschrieben. Ein Verzeichnisglob wuerde beim
naechsten heruntergeladenen Wettbewerb stillschweigend etwas
aufnehmen, das kein nationaler Ligabetrieb ist - einen Pokal, einen
Kontinentalwettbewerb, ein Freundschaftsturnier. Was hier nicht steht,
wird nicht gelesen.

WARUM POKALE DRAUSSEN BLEIBEN
-----------------------------
Ein Pokal ist kein Ligabetrieb. Die Teilnehmerfelder sind gemischt
(Erst- gegen Viertligist), die Partienzahl je Verein schwankt zwischen
einer und sieben, und ein Profil aus solchen Partien beschreibt nicht
die Staerke gegen vergleichbare Gegner. Sie liegen lokal vor und
werden ausdruecklich NICHT verwendet.

DIE ID-FALLE
------------
football-data.org und API-Football fuehren getrennte Nummernkreise.
Nachgemessen: 28 Champions-League-Vereins-IDs bezeichnen im
API-Football-Namensraum einen ANDEREN Verein.

    football-data 498 = Sporting CP      API-Football 498 = Sampdoria
    football-data 732 = Celtic           API-Football 732 = Zaragoza
    football-data  57 = Arsenal          API-Football  57 = Ipswich

Eine Zahl allein ist deshalb keine Vereinsidentitaet. Jede Liga traegt
hier ihren Provider, und wer eine ID benutzt, muss wissen, aus welchem
Namensraum sie stammt.
"""

import os

#: Die beiden Namensraeume. Es gibt keinen dritten.
PROVIDER_FOOTBALL_DATA = "football-data.org"
PROVIDER_API_FOOTBALL = "api-football.com"

PROVIDERS = (PROVIDER_FOOTBALL_DATA, PROVIDER_API_FOOTBALL)


#: Die nationalen Ligen, die ein Teamprofil tragen duerfen.
#:
#: provider  aus welchem Namensraum die Team-IDs stammen
#: country   Laenderkuerzel, dient der Identitaetspruefung
#: name      Klartext fuer Berichte
NATIONAL_LEAGUES = {
    # -- football-data.org, derselbe Namensraum wie die CL -------------
    "BL1":  {"provider": PROVIDER_FOOTBALL_DATA, "country": "DE",
             "name": "Bundesliga"},
    "PL":   {"provider": PROVIDER_FOOTBALL_DATA, "country": "EN",
             "name": "Premier League"},
    "PD":   {"provider": PROVIDER_FOOTBALL_DATA, "country": "ES",
             "name": "LaLiga"},
    "SA":   {"provider": PROVIDER_FOOTBALL_DATA, "country": "IT",
             "name": "Serie A"},
    "FL1":  {"provider": PROVIDER_FOOTBALL_DATA, "country": "FR",
             "name": "Ligue 1"},

    # -- API-Football, eigener Namensraum, nur ueber Crosswalk --------
    "NL1":  {"provider": PROVIDER_API_FOOTBALL, "country": "NL",
             "name": "Eredivisie"},
    "PT1":  {"provider": PROVIDER_API_FOOTBALL, "country": "PT",
             "name": "Primeira Liga"},
    "BE1":  {"provider": PROVIDER_API_FOOTBALL, "country": "BE",
             "name": "Pro League"},
    "AT1":  {"provider": PROVIDER_API_FOOTBALL, "country": "AT",
             "name": "Bundesliga (AT)"},
    "CH1":  {"provider": PROVIDER_API_FOOTBALL, "country": "CH",
             "name": "Super League"},
    "SCO1": {"provider": PROVIDER_API_FOOTBALL, "country": "SCO",
             "name": "Premiership"},
    "TR1":  {"provider": PROVIDER_API_FOOTBALL, "country": "TR",
             "name": "Sueper Lig"},
    "GR1":  {"provider": PROVIDER_API_FOOTBALL, "country": "GR",
             "name": "Super League 1"},
    "CZ1":  {"provider": PROVIDER_API_FOOTBALL, "country": "CZ",
             "name": "Chance Liga"},
    "HR1":  {"provider": PROVIDER_API_FOOTBALL, "country": "HR",
             "name": "HNL"},
    "RS1":  {"provider": PROVIDER_API_FOOTBALL, "country": "RS",
             "name": "Super Liga"},
    "UA1":  {"provider": PROVIDER_API_FOOTBALL, "country": "UA",
             "name": "Premier Liha"},
    "DK1":  {"provider": PROVIDER_API_FOOTBALL, "country": "DK",
             "name": "Superliga"},
    "NO1":  {"provider": PROVIDER_API_FOOTBALL, "country": "NO",
             "name": "Eliteserien"},
    "SK1":  {"provider": PROVIDER_API_FOOTBALL, "country": "SK",
             "name": "Nike Liga"},
    "CY1":  {"provider": PROVIDER_API_FOOTBALL, "country": "CY",
             "name": "First Division"},
    "KZ1":  {"provider": PROVIDER_API_FOOTBALL, "country": "KZ",
             "name": "Premier League (KZ)"},
    "AZ1":  {"provider": PROVIDER_API_FOOTBALL, "country": "AZ",
             "name": "Premyer Liqa"},
}


#: Lokal vorhanden, aber ausdruecklich KEINE Profilquelle.
#:
#: Die Begruendung steht daneben, damit spaeter niemand sie fuer eine
#: Nachlaessigkeit haelt und sie beilaeufig aufnimmt.
EXCLUDED_COMPETITIONS = {
    "CDR": "Copa del Rey - Pokal, gemischte Ligaebenen",
    "CIT": "Coppa Italia - Pokal, gemischte Ligaebenen",
    "CDF": "Coupe de France - Pokal, gemischte Ligaebenen",
    "DFB": "DFB-Pokal - Pokal, gemischte Ligaebenen",
    "FAC": "FA Cup - Pokal, gemischte Ligaebenen",
    "CL":  "Champions League - der auszuwertende Wettbewerb selbst",
}


def league_provider(code):
    """
    Der Namensraum einer Liga - oder ein Fehler.

    Es gibt keinen Standardwert. Wer den Provider nicht kennt, darf
    keine ID benutzen; genau daraus entstehen die 28 nachgewiesenen
    Verwechslungen.
    """
    eintrag = NATIONAL_LEAGUES.get(code)
    if eintrag is None:
        raise KeyError(
            f"{code!r} ist keine zugelassene nationale Profilquelle. "
            f"Zugelassen sind {sorted(NATIONAL_LEAGUES)}; ausdruecklich "
            f"ausgeschlossen {sorted(EXCLUDED_COMPETITIONS)}.")
    return eintrag["provider"]


def codes_for_provider(provider):
    """Alle zugelassenen Ligacodes eines Namensraums."""
    if provider not in PROVIDERS:
        raise ValueError(f"unbekannter Provider: {provider!r}")
    return sorted(code for code, e in NATIONAL_LEAGUES.items()
                  if e["provider"] == provider)


def profile_source_codes():
    """Alle zugelassenen nationalen Profilquellen, in fester Ordnung."""
    return sorted(NATIONAL_LEAGUES)


# ---------------------------------------------------------------------------
# Inventar
# ---------------------------------------------------------------------------

def league_inventory(directory=None, seasons=None):
    """
    Was tatsaechlich auf der Platte liegt - je Liga und Saison.

    Liest ausschliesslich lokale Dateien und ruft nichts ab. Gibt
    NICHT zurueck, was zugelassen ist, sondern was vorhanden ist; die
    Schnittmenge beider bildet die nutzbare Grundlage.
    """
    import json

    from src.data.historical_loader import (
        AVAILABLE_HISTORICAL_SEASONS, HISTORICAL_DIR, season_file_path)

    directory = directory or HISTORICAL_DIR
    seasons = seasons or AVAILABLE_HISTORICAL_SEASONS

    heraus = {}
    for code in profile_source_codes():
        eintrag = NATIONAL_LEAGUES[code]
        saisons = {}
        for season in sorted(seasons):
            pfad = season_file_path(code, season)
            if directory != HISTORICAL_DIR:          # pragma: no cover
                pfad = os.path.join(directory,
                                    os.path.basename(pfad))
            if not os.path.isfile(pfad):
                continue
            try:
                with open(pfad, encoding="utf-8") as datei:
                    payload = json.load(datei)
            except (OSError, ValueError):            # pragma: no cover
                continue

            partien = payload.get("matches") or []
            beendet = [m for m in partien
                       if str(m.get("status", "FINISHED")).upper()
                       in ("FINISHED", "FT", "AET", "PEN")]
            mit_toren = [m for m in beendet
                         if m.get("home_goals") is not None
                         and m.get("away_goals") is not None]
            daten = sorted(m.get("date") for m in partien if m.get("date"))

            saisons[season] = {
                "matches": len(partien),
                "finished": len(beendet),
                "with_goals": len(mit_toren),
                "teams": len(payload.get("teams") or {}),
                "first_date": daten[0] if daten else None,
                "last_date": daten[-1] if daten else None,
                "has_kickoff": any(m.get("kickoff") for m in partien),
                "file_source": (payload.get("meta") or {}).get("source"),
            }

        heraus[code] = {
            "provider": eintrag["provider"],
            "country": eintrag["country"],
            "name": eintrag["name"],
            "seasons": saisons,
            "usable": bool(saisons),
        }
    return heraus


def inventory_summary(inventar=None):
    """Eine kompakte Zusammenfassung fuer Berichte und Artefakte."""
    inventar = inventar if inventar is not None else league_inventory()
    partien = sum(s["with_goals"]
                  for liga in inventar.values()
                  for s in liga["seasons"].values())
    return {
        "leagues_allowed": len(NATIONAL_LEAGUES),
        "leagues_present": sum(1 for l in inventar.values() if l["usable"]),
        "leagues_by_provider": {
            p: len(codes_for_provider(p)) for p in PROVIDERS},
        "competitions_excluded": dict(EXCLUDED_COMPETITIONS),
        "matches_with_goals": partien,
    }
