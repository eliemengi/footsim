"""
Tests des reparierten nationalen Profilpfads (V2-C13).

WORUM ES GEHT
Der Profilpfad las fuenf von 23 vorhandenen Ligadateien. 321 von 1006
Champions-League-Teamseiten bekamen deshalb kein nationales Profil,
sondern eines aus 1 bis 27 CL-Partien. In V2-C12 kostete genau diese
Gruppe die Freigabe.

Die Reparatur bringt die uebrigen Ligen herein. Sie stammen von einem
anderen Anbieter mit einem EIGENEN Nummernkreis, und dort liegt die
Gefahr: 28 der 63 CL-Vereins-IDs bezeichnen im API-Football-Namensraum
einen anderen Verein.

Die schaerfsten Tests hier sind deshalb die Kollisionstests. Ein Test,
der zeigt, dass Ajax jetzt ein Profil hat, beweist wenig. Beweisen muss
man, dass Arsenal nicht die Spiele von Ipswich bekommt.
"""

import collections
import json
import pathlib
import re

import pytest

from src.data import national_sources as ns
from src.features import pit_profiles as pp
from src.features import point_in_time as pit
from src.features import team_identity as ti

WURZEL = pathlib.Path(__file__).resolve().parents[1]
HIST = WURZEL / "data" / "historical"


# ---------------------------------------------------------------------------
# Die Namensraeume, streng getrennt geladen
# ---------------------------------------------------------------------------

def _namen_je_provider():
    """
    Vereinsnamen je Anbieter, ohne Vermischung.

    Genau diese Trennung fehlte im forensischen Skript vor C13, und
    genau daraus entstand die Falschmeldung "Zaragoza spielt Champions
    League".
    """
    fd, api = {}, {}
    for pfad in sorted(HIST.glob("*.json")):
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:                                # pragma: no cover
            continue
        if not isinstance(daten, dict):
            continue
        quelle = (daten.get("meta") or {}).get("source")
        ziel = (fd if quelle == ns.PROVIDER_FOOTBALL_DATA
                else api if quelle == ns.PROVIDER_API_FOOTBALL else None)
        if ziel is None:
            continue
        for tid, block in (daten.get("teams") or {}).items():
            name = (block or {}).get("name")
            if name:
                ziel.setdefault(int(tid), name)
    return fd, api


FD_NAMEN, API_NAMEN = _namen_je_provider()


def _kollisionen():
    """
    Die numerischen Kollisionen, deterministisch aus lokalen Dateien.

    Eine ID kollidiert, wenn sie in beiden Namensraeumen vorkommt und
    dort verschiedene Vereine bezeichnet. Als "verschieden" gilt, was
    der Crosswalk NICHT aufeinander abbildet - das ist die
    verlaessliche Aussage, nicht ein Namensvergleich.
    """
    heraus = []
    for tid in sorted(set(FD_NAMEN) & set(API_NAMEN)):
        if ti.to_api_football(tid) != tid:
            heraus.append(tid)
    return heraus


KOLLISIONEN = _kollisionen()


def _cl_vereine():
    """Die Vereins-IDs, die in den CL-Dateien tatsaechlich auftauchen."""
    heraus = set()
    for pfad in sorted(HIST.glob("*.json")):
        if not pfad.name.startswith("CL"):
            continue
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:                                # pragma: no cover
            continue
        for partie in (daten.get("matches") or []):
            for feld in ("home_id", "away_id"):
                if partie.get(feld) is not None:
                    heraus.add(int(partie[feld]))
    return heraus


CL_VEREINE = _cl_vereine()

#: Die Teilmenge, die wirklich weh tut: kollidierende IDs, die zu einem
#: Champions-League-Verein gehoeren. Genau hier haette ein Fehler
#: Trainingsdaten verfaelscht.
CL_KOLLISIONEN = sorted(set(KOLLISIONEN) & CL_VEREINE)


def _heimatligen():
    """
    In welcher nationalen Liga ein Verein wirklich spielt.

    Unabhaengig vom Profilpfad aus den Ligadateien gelesen: In jeder
    Datei wird die Teamliste im Namensraum IHRES Providers gelesen und
    erst danach - falls noetig - auf football-data zurueckgefuehrt.

    Rueckgabe: fd_id -> {(ligacode, land, name_in_der_datei)}
    """
    from src.data.historical_loader import season_file_path
    from src.data.historical_loader import AVAILABLE_HISTORICAL_SEASONS

    heraus = collections.defaultdict(set)
    for code in ns.profile_source_codes():
        provider = ns.league_provider(code)
        land = ns.NATIONAL_LEAGUES[code]["country"]
        for saison in AVAILABLE_HISTORICAL_SEASONS:
            pfad = pathlib.Path(season_file_path(code, saison))
            if not pfad.is_file():
                continue
            try:
                daten = json.loads(pfad.read_text(encoding="utf-8"))
            except Exception:                            # pragma: no cover
                continue
            for tid, block in (daten.get("teams") or {}).items():
                tid = int(tid)
                name = (block or {}).get("name") or ""
                if provider == ns.PROVIDER_API_FOOTBALL:
                    fd_id = ti.to_football_data(tid)
                    if fd_id is None:
                        continue
                else:
                    fd_id = tid
                heraus[fd_id].add((code, land, name))
    return dict(heraus)


HEIMATLIGEN = _heimatligen()

_REPO_2025 = pp.PitProfileRepository()
PROFILE_2025 = _REPO_2025.domestic_profiles(2025, "2026-01-20")


# ===========================================================================
# 1  Ligainventar
# ===========================================================================

def test_alle_zugelassenen_ligen_liegen_lokal_vor():
    inventar = ns.league_inventory()
    fehlend = [c for c, l in inventar.items() if not l["usable"]]
    assert fehlend == [], fehlend
    assert len(inventar) == 23


def test_pokale_sind_ausdruecklich_ausgeschlossen():
    """
    Ein Pokal ist kein Ligabetrieb: gemischte Ligaebenen, zwischen
    einer und sieben Partien je Verein. Ein Profil daraus beschreibt
    nicht die Staerke gegen vergleichbare Gegner.
    """
    for code in ("CDR", "CIT", "CDF", "DFB", "FAC", "CL"):
        assert code in ns.EXCLUDED_COMPETITIONS
        assert code not in ns.NATIONAL_LEAGUES
        assert code not in ns.profile_source_codes()


def test_die_ligaliste_ist_ausgeschrieben_und_nicht_geglobbt():
    """
    Ein Verzeichnisglob wuerde beim naechsten heruntergeladenen
    Wettbewerb stillschweigend etwas aufnehmen, das kein nationaler
    Ligabetrieb ist.
    """
    quelle = (WURZEL / "src" / "data" / "national_sources.py").read_text(
        encoding="utf-8")
    import ast

    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Assign):
            ziele = [t.id for t in knoten.targets
                     if isinstance(t, ast.Name)]
            if "NATIONAL_LEAGUES" in ziele:
                assert isinstance(knoten.value, ast.Dict)
                assert len(knoten.value.keys) == 23
                return
    pytest.fail("NATIONAL_LEAGUES nicht als Literal gefunden")


def test_jede_liga_nennt_provider_und_land():
    for code, eintrag in ns.NATIONAL_LEAGUES.items():
        assert eintrag["provider"] in ns.PROVIDERS, code
        assert eintrag["country"], code
        assert eintrag["name"], code


def test_ein_unbekannter_wettbewerb_bricht_ab():
    """Kein Standardprovider. Wer ihn nicht kennt, darf keine ID nutzen."""
    with pytest.raises(KeyError, match="keine zugelassene"):
        ns.league_provider("CDR")
    with pytest.raises(KeyError):
        ns.league_provider("GIBTESNICHT")


def test_die_provideraufteilung_stimmt():
    assert len(ns.codes_for_provider(ns.PROVIDER_FOOTBALL_DATA)) == 5
    assert len(ns.codes_for_provider(ns.PROVIDER_API_FOOTBALL)) == 18


# ===========================================================================
# 2  Identitaet und Kollisionen
# ===========================================================================

def test_es_gibt_ueberhaupt_kollisionen():
    """
    Ohne diesen Test koennte die Kollisionsmenge leer sein und alle
    folgenden Tests waeren wertlos.
    """
    assert len(KOLLISIONEN) >= 20, len(KOLLISIONEN)


@pytest.mark.parametrize("team_id", KOLLISIONEN)
def test_eine_kollidierende_id_wird_nie_direkt_uebernommen(team_id):
    """
    DER KERN VON C13.

    Fuer jede numerisch kollidierende ID gilt: Die Rueckuebersetzung
    aus dem API-Namensraum darf NICHT dieselbe Zahl liefern. Taete sie
    es, bekaeme ein Verein die Spiele eines fremden.
    """
    zurueck = ti.to_football_data(team_id)
    assert zurueck != team_id, (
        f"api {team_id} ({API_NAMEN.get(team_id)}) wurde auf dieselbe "
        f"Zahl abgebildet, die bei football-data "
        f"{FD_NAMEN.get(team_id)} bezeichnet")


def test_die_cl_kollisionsmenge_ist_vollstaendig():
    """
    28 der 63 Champions-League-Vereins-IDs bezeichnen im
    API-Football-Namensraum einen anderen Verein. Die Zahl steht hier
    fest, damit ein stiller Verlust der Testmenge auffaellt statt
    unbemerkt zu bleiben.
    """
    assert len(CL_VEREINE) == 63, len(CL_VEREINE)
    assert len(CL_KOLLISIONEN) == 28, len(CL_KOLLISIONEN)


@pytest.mark.parametrize("team_id", CL_KOLLISIONEN)
def test_kein_cl_verein_erbt_die_spiele_eines_fremden(team_id):
    """
    Die schaerfste Form des Kollisionstests.

    Fuer jeden betroffenen CL-Verein gilt beides:
      - seine football-data-Kennung fuehrt NICHT auf dieselbe Zahl im
        anderen Namensraum,
      - und dieselbe Zahl aus dem API-Namensraum fuehrt nicht auf ihn
        zurueck.

    Andernfalls bekaeme Arsenal die Ergebnisse von Ipswich.
    """
    assert ti.to_api_football(team_id) != team_id, (
        f"fd {team_id} ({FD_NAMEN.get(team_id)}) wuerde die Spiele von "
        f"{API_NAMEN.get(team_id)} bekommen")
    assert ti.to_football_data(team_id) != team_id


@pytest.mark.parametrize("team_id", CL_KOLLISIONEN)
def test_das_profil_stammt_aus_der_liga_des_richtigen_vereins(team_id):
    """
    Nicht nur die Abbildung, auch das ERGEBNIS wird geprueft: Das
    nationale Profil eines betroffenen Vereins muss aus einer Liga
    seines eigenen Landes stammen.

    Arsenal aus der PL, nicht aus der Eredivisie.
    """
    profil = PROFILE_2025.get(team_id)
    if profil is None:
        pytest.skip("kein nationales Profil - eigener Test dafuer")

    liga = profil["source_league"]
    heimat = HEIMATLIGEN.get(team_id, set())
    assert heimat, f"{FD_NAMEN.get(team_id)} in keiner Ligadatei gefunden"

    erlaubt = {eintrag[0] for eintrag in heimat}
    assert liga in erlaubt, (
        f"{FD_NAMEN.get(team_id)} bekaeme ein Profil aus {liga}, spielt "
        f"aber in {sorted(erlaubt)}")


#: Vier Vereine heissen bei den beiden Anbietern nachweislich
#: verschieden. Das sind Schreibweisen desselben Vereins, keine
#: Verwechslungen - jede einzeln geprueft. Sie stehen hier
#: ausgeschrieben, damit die Namenspruefung streng bleiben kann,
#: statt sie mit einer laxen Aehnlichkeitsschwelle aufzuweichen.
SCHREIBWEISEN = {
    1876: "FC Kobenhavn = FC Copenhagen (daenisch und englisch)",
    11034: "Paphos = Pafos (griechische Transliteration)",
}


def _normalisiert(name):
    """Namen vergleichbar machen, ohne sie gleichzumachen."""
    import unicodedata

    zerlegt = unicodedata.normalize("NFKD", name.lower())
    ohne_akzente = "".join(z for z in zerlegt
                           if not unicodedata.combining(z))
    bereinigt = re.sub(r"[^a-z0-9 ]", " ", ohne_akzente)
    rauschen = {"fc", "cf", "sc", "ac", "afc", "club", "de", "sk", "fk",
                "bk", "if", "sv", "tsv", "vfb", "vfl", "bv", "cp", "sad",
                "sl", "nk", "hnk", "gnk", "fsv", "rc", "ss", "us", "as",
                "ssc", "bsc", "cd", "ud", "sd", "kv", "kaa", "rsc"}
    return {t for t in bereinigt.split() if t and t not in rauschen}


@pytest.mark.parametrize("team_id", sorted(CL_VEREINE))
def test_jeder_cl_verein_ist_nach_name_und_liga_validiert(team_id):
    """
    DIE FORDERUNG AUS DER PRUEFUNG DES VORIGEN BERICHTS.

    Eine Abdeckungszahl darf nicht als Beleg gelten, solange nicht
    jede einzelne Zuordnung an Teamname, Land und Liga nachvollzogen
    ist. Genau das passiert hier, fuer alle 63 Vereine einzeln:

      - der Verein hat ein nationales Profil,
      - es stammt aus einer Liga, in deren Teamliste er wirklich
        steht,
      - und der Name dort ist seiner - oder eine der vier
        namentlich aufgefuehrten Schreibweisen.
    """
    profil = PROFILE_2025.get(team_id)
    assert profil is not None, (
        f"{FD_NAMEN.get(team_id)} ohne nationales Profil")

    liga = profil["source_league"]
    eintraege = [e for e in HEIMATLIGEN.get(team_id, set())
                 if e[0] == liga]
    assert eintraege, (
        f"{FD_NAMEN.get(team_id)} bekaeme ein Profil aus {liga}, steht "
        f"dort aber in keiner Teamliste")

    eigener = _normalisiert(FD_NAMEN.get(team_id) or "")
    dort = set().union(*[_normalisiert(e[2]) for e in eintraege])
    if not (eigener & dort):
        assert team_id in SCHREIBWEISEN, (
            f"{FD_NAMEN.get(team_id)!r} bekaeme ein Profil aus {liga}, "
            f"wo er {sorted(e[2] for e in eintraege)!r} heisst")


def test_die_abdeckung_ist_vollstaendig_und_nicht_nur_behauptet():
    """
    Die Zusammenfassung des Einzelnachweises. Sie steht bewusst NACH
    ihm: Ohne die 63 Einzelpruefungen waere diese Zahl wieder nur eine
    Behauptung.
    """
    assert len(CL_VEREINE) == 63
    ohne = sorted(t for t in CL_VEREINE if t not in PROFILE_2025)
    assert ohne == [], [(t, FD_NAMEN.get(t)) for t in ohne]


def test_die_schreibweisenliste_ist_nicht_groesser_als_noetig():
    """
    Ein Ausnahmenkatalog, der stillschweigend waechst, entwertet die
    Pruefung. Jede Ausnahme muss noch gebraucht werden.
    """
    for team_id, begruendung in SCHREIBWEISEN.items():
        assert team_id in CL_VEREINE, team_id
        assert len(begruendung) > 20, team_id
        profil = PROFILE_2025.get(team_id)
        eintraege = [e for e in HEIMATLIGEN.get(team_id, set())
                     if e[0] == profil["source_league"]]
        eigener = _normalisiert(FD_NAMEN.get(team_id) or "")
        dort = set().union(*[_normalisiert(e[2]) for e in eintraege])
        assert not (eigener & dort), (
            f"{team_id} braucht keine Ausnahme mehr")


@pytest.mark.parametrize("fd_id,erwartet", [
    (498, "Sporting"), (732, "Celtic"), (57, "Arsenal"),
    (678, "Ajax"), (1903, "Benfica"), (1877, "Salzburg"),
    (610, "Galatasaray"),
])
def test_bekannte_vereine_loesen_korrekt_auf(fd_id, erwartet):
    assert erwartet.lower() in (FD_NAMEN.get(fd_id) or "").lower()
    api_id = ti.to_api_football(fd_id)
    assert api_id is not None, f"{erwartet} ohne Crosswalkziel"
    assert ti.to_football_data(api_id) == fd_id, "Rundreise gebrochen"


def test_die_beiden_beruehmten_faelle_bleiben_getrennt():
    """
    football-data 498 = Sporting CP, API-Football 498 = Sampdoria.
    football-data 732 = Celtic,      API-Football 732 = Zaragoza.
    """
    assert "Sporting" in FD_NAMEN[498]
    assert "Sampdoria" in API_NAMEN[498]
    assert "Celtic" in FD_NAMEN[732]
    assert "Zaragoza" in API_NAMEN[732]

    assert ti.to_api_football(498) != 498
    assert ti.to_api_football(732) != 732
    assert ti.to_football_data(498) != 498
    assert ti.to_football_data(732) != 732


def test_ein_unbekannter_verein_bekommt_kein_fremdes_profil():
    """
    None heisst "nicht aufloesbar" und nicht "nimm dieselbe Zahl".
    """
    assert ti.to_football_data(99_999_999) is None
    assert ti.to_api_football(99_999_999) is None


def test_die_bruecke_ist_in_beide_richtungen_eindeutig():
    bericht = ti.identity_report()
    assert bericht["ambiguous_targets"] == {}
    assert bericht["forward_entries"] == bericht["backward_entries"]


def test_ein_mehrdeutiges_ziel_wird_aus_beiden_richtungen_entfernt(
        monkeypatch):
    """
    Ein Profil, das zwei Vereinen gehoeren koennte, gehoert keinem.
    Dieselbe Regel wie im C7-Crosswalk.
    """
    from src.features import squad_crosswalk as sc

    monkeypatch.setattr(sc, "build_team_crosswalk",
                        lambda *a, **k: ({1: 100, 2: 100, 3: 300}, {}))
    ti.reset_cache()
    try:
        assert ti.to_football_data(100) is None
        assert ti.to_api_football(1) is None
        assert ti.to_api_football(2) is None
        assert ti.to_api_football(3) == 300
        assert ti.identity_report()["ambiguous_targets"] == {100: [1, 2]}
    finally:
        ti.reset_cache()


def test_translate_profiles_verwirft_unaufloesbare_vereine():
    """
    Die Reihenfolge ist der Schutz: erst alle Profile im Namensraum
    der Liga bauen, dann zurueckuebersetzen. Wer sich nicht
    zurueckfuehren laesst, faellt weg.
    """
    roh = {194: {"matches_used": 30}, 99_999_999: {"matches_used": 30}}
    heraus, spur = ti.translate_profiles(roh, "NL1")
    assert 99_999_999 not in heraus
    assert spur["dropped_unmapped"] == 1
    assert ti.to_football_data(194) in heraus


def test_football_data_ligen_werden_nicht_uebersetzt():
    """
    Sie stehen bereits im Namensraum der Champions League.

    V2-C18: Die KENNUNG wandert hier weiterhin nicht - der Schluessel
    65 bleibt 65. Der Payload traegt seine Identitaet seit C18 aber
    ausdruecklich mit, und zwar fuer beide Provider ohne
    Fallunterscheidung. Bis dahin stand sie nur im Schluessel, und
    inference._ligastaerke_anwenden las sie aus dem Payload - fuer die
    18 mit C13 ergaenzten Ligen war das eine andere Zahl.
    """
    roh = {65: {"matches_used": 30}}
    heraus, spur = ti.translate_profiles(roh, "PL")
    assert set(heraus) == set(roh)
    assert spur["translated"] == 0
    assert heraus[65]["matches_used"] == 30
    assert heraus[65]["team_id"] == 65
    # Die Eingabe bleibt unberuehrt.
    assert roh[65] == {"matches_used": 30}


def test_keine_zwei_cl_vereine_teilen_ein_nationales_profil():
    repo = pp.PitProfileRepository()
    profile = repo.domestic_profiles(2025, "2026-01-20")
    # Profile sind je football-data-ID eindeutig; zwei Vereine mit
    # demselben Objekt waeren ein Zeichen fuer eine Doppelabbildung.
    ids = [id(p) for p in profile.values()]
    assert len(ids) == len(set(ids))


# ===========================================================================
# 3  Point in Time
# ===========================================================================

def test_profile_wachsen_monoton_mit_dem_stichtag():
    """
    Ein spaeterer Stichtag darf nie WENIGER Partien sehen. Faellt die
    Zahl, hat die Filterung ein Loch.
    """
    repo = pp.PitProfileRepository()
    tiefen = []
    for tag in ("2025-08-15", "2025-10-01", "2025-12-01", "2026-01-20"):
        profil = repo.domestic_profiles(2025, tag).get(678)
        assert profil is not None, tag
        tiefen.append(profil["matches_used"])
    assert tiefen == sorted(tiefen), tiefen
    assert tiefen[-1] > tiefen[0]


def test_eine_partie_am_stichtag_zaehlt_nicht():
    """
    Die Grenze ist strikt. Sonst koennte ein Spiel Teil seines eigenen
    Profils werden.
    """
    partie = {"date": "2025-10-01", "kickoff": "2025-10-01T18:30:00+00:00",
              "status": "FT"}
    assert pit.is_known_at(partie, "2025-10-01") is False
    assert pit.is_known_at(partie, "2025-10-02") is True


def test_die_api_dateien_aendern_die_zeitsemantik_nicht():
    """
    Die api-football-Dateien fuehren ein kickoff-Feld, die
    football-data-Dateien nicht. point_in_time liest es NICHT, und das
    bleibt so: Ein zusaetzliches Zeitfeld dort wuerde die
    projektweite Cutoff-Semantik aller Aufrufer verschieben. Die
    Folge ist konservativ - Partien am Stichtag bleiben draussen.
    """
    partie = {"date": "2025-10-01", "kickoff": "2025-10-01T06:00:00+00:00",
              "status": "FT"}
    assert pit.match_time(partie) is None
    assert pit.is_known_at(partie, "2025-10-01") is False


def test_eine_spaetere_partie_veraendert_ein_frueheres_profil_nicht():
    """
    MANIPULATIONSTEST. Ein sauberer Durchlauf beweist nur, dass die
    Filterung diesmal nichts zu tun hatte.
    """
    from src.features.team_profile import build_season_profiles

    basis = [{"date": "2025-09-%02d" % t, "home_id": 1, "away_id": 2,
              "home_goals": 2, "away_goals": 1, "status": "FT"}
             for t in (1, 8, 15)]
    zukunft = {"date": "2025-12-01", "home_id": 1, "away_id": 2,
               "home_goals": 9, "away_goals": 0, "status": "FT"}

    ohne = build_season_profiles({"matches": basis, "teams": {}},
                                 cutoff="2025-10-01")
    mit = build_season_profiles({"matches": basis + [zukunft],
                                 "teams": {}}, cutoff="2025-10-01")
    assert ohne["profiles"] == mit["profiles"]


def test_eine_frueher_gelegte_partie_wirkt_sehr_wohl():
    """Die Gegenprobe. Ohne sie koennte der Filter alles verwerfen."""
    from src.features.team_profile import build_season_profiles

    basis = [{"date": "2025-09-%02d" % t, "home_id": 1, "away_id": 2,
              "home_goals": 2, "away_goals": 1, "status": "FT"}
             for t in (1, 8, 15)]
    frueher = {"date": "2025-09-20", "home_id": 1, "away_id": 2,
               "home_goals": 9, "away_goals": 0, "status": "FT"}

    ohne = build_season_profiles({"matches": basis, "teams": {}},
                                 cutoff="2025-10-01")
    mit = build_season_profiles({"matches": basis + [frueher],
                                 "teams": {}}, cutoff="2025-10-01")
    assert ohne["profiles"] != mit["profiles"]


def test_der_c10_stichtagsvertrag_bleibt_unveraendert():
    from src.features import prediction_cutoff as pc
    from src.ml import dataset as ds

    assert pc.CUTOFF_HOUR == 12
    assert pc.CUTOFF_INCLUSIVE is False
    assert pc.assert_hours_match() is True
    assert ds.prediction_cutoff("2025-03-11").hour == 12


def test_es_werden_keine_aktuellen_snapshots_gelesen():
    """
    Der Profilpfad liest historische Matchdateien, keine
    Kader-, Tabellen- oder Verletzungsstaende von heute.
    """
    import ast

    for datei in ("src/features/pit_profiles.py",
                  "src/features/team_identity.py",
                  "src/data/national_sources.py"):
        baum = ast.parse((WURZEL / datei).read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if (isinstance(knoten, (ast.Module, ast.ClassDef,
                                    ast.FunctionDef))
                    and ast.get_docstring(knoten)):
                knoten.body = knoten.body[1:]
        code = ast.unparse(baum)
        for verboten in ("snapshot_reader", "current_squads",
                         "squad_availability", "fixture_refresh"):
            assert verboten not in code, f"{datei}: {verboten}"


def test_der_profilpfad_braucht_kein_netz_und_keine_env():
    import ast

    for datei in ("src/data/national_sources.py",
                  "src/features/team_identity.py"):
        baum = ast.parse((WURZEL / datei).read_text(encoding="utf-8"))
        importiert = set()
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Import):
                for name in knoten.names:
                    importiert.add(name.name.split(".")[0])
            elif isinstance(knoten, ast.ImportFrom) and knoten.module:
                importiert.add(knoten.module.split(".")[0])
        assert not (importiert & {"requests", "urllib", "socket", "httpx",
                                  "dotenv"}), datei


# ===========================================================================
# 4  Abdeckung und Determinismus
# ===========================================================================

@pytest.fixture(scope="module")
def alle_zeilen():
    """
    Der Datensatz, einmal je Modul gebaut.

    Er kostet ein paar Minuten. Ihn je Test neu zu bauen waere reine
    Wartezeit, denn er haengt nur an lokalen Dateien.
    """
    from src.ml import dataset as ds

    zeilen, _ = ds.build_dataset(include_cl=True)
    return zeilen


@pytest.fixture(scope="module")
def cl_zeilen(alle_zeilen):
    return [r for r in alle_zeilen if r.get("league") == "cl"]


@pytest.fixture(scope="module")
def artefakt(alle_zeilen):
    from src.ml import c13_contract as c13

    return c13.build_artifact(alle_zeilen)


def test_kein_cl_history_profil_bleibt_uebrig(cl_zeilen):
    """
    Vorher: 321 von 1006 Teamseiten. Die nationale Historie war
    vorhanden, sie wurde nur nicht gelesen.
    """
    rest = [r for r in cl_zeilen
            for seite in ("home", "away")
            if r.get(seite + "_profile_source") == "cl_history_pit"]
    assert rest == []


def test_kein_neutrales_profil_bleibt_uebrig(cl_zeilen):
    rest = [r for r in cl_zeilen
            for seite in ("home", "away")
            if r.get(seite + "_profile_source") == "neutral"]
    assert rest == []


def test_alle_teamseiten_haben_ein_nationales_profil(cl_zeilen):
    quellen = collections.Counter(
        r.get(seite + "_profile_source")
        for r in cl_zeilen for seite in ("home", "away"))
    assert set(quellen) == {"domestic_pit"}
    assert quellen["domestic_pit"] == 2 * len(cl_zeilen) == 1006


def test_mehr_auswertbare_partien_als_vorher(cl_zeilen):
    ee = sum(1 for r in cl_zeilen if r.get("evaluation_eligible"))
    assert ee == 363, ee
    assert ee > 238, "vor C13 waren es 238"


def test_verbleibende_ausschluesse_sind_ehrliche_datenluecken(cl_zeilen):
    """
    Was uebrig bleibt, sind Partien mit wirklich duenner Historie -
    keine Zuordnungsfehler. Sie werden nicht wegdefiniert.
    """
    rest = [r for r in cl_zeilen
            if not r.get("evaluation_eligible")
            and not r.get("knockout_eligible")]
    assert len(rest) == 21
    for r in rest:
        assert "Profiltiefe" in (r.get("exclusion_reason") or "")


def test_die_profiltiefe_ist_deutlich_gestiegen(cl_zeilen):
    tiefen = sorted(r[seite + "_profile_matches"]
                    for r in cl_zeilen for seite in ("home", "away")
                    if isinstance(r.get(seite + "_profile_matches"),
                                  (int, float)))
    median = tiefen[len(tiefen) // 2]
    assert median >= 40, median


def test_der_datensatzbau_ist_deterministisch():
    """
    Zwei Laeufe muessen dieselben Profile liefern. Haenge das Ergebnis
    an der Reihenfolge der Ligadateien, waere jede Messung darauf
    wertlos.
    """
    a = pp.PitProfileRepository().domestic_profiles(2025, "2026-01-20")
    b = pp.PitProfileRepository().domestic_profiles(2025, "2026-01-20")
    assert sorted(a) == sorted(b)
    for tid in a:
        assert a[tid]["matches_used"] == b[tid]["matches_used"]
        assert a[tid]["source_league"] == b[tid]["source_league"]


def test_die_reihenfolge_der_ligen_ist_festgelegt():
    """Sortiert, damit zwei Laeufe dieselbe Auswahl treffen."""
    assert ns.profile_source_codes() == sorted(ns.profile_source_codes())


# ===========================================================================
# 5  Der eingefrorene Vertrag bleibt
# ===========================================================================

def test_der_c9_schema_fingerprint_ist_unveraendert():
    """
    C13 aendert WERTE, nicht den Vertrag. Merkmalsanzahl, Namen,
    Reihenfolge und Semantik bleiben; nur die Datenbasis wird
    vollstaendiger.
    """
    from src.ml import early_v2 as e9

    assert e9.schema_fingerprint() == (
        "475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5")
    assert len(e9.selected_columns()) == 16
    assert e9.SELECTED_CANDIDATE == "team_profile_cl"


def test_die_sechzehn_merkmale_heissen_unveraendert():
    from src.ml import early_v2 as e9

    assert e9.selected_columns() == sorted([
        "home_attack_home", "home_attack_away", "home_defence_home",
        "home_defence_away", "home_goals_for_per_game",
        "home_goals_against_per_game", "home_points_per_game",
        "home_win_rate",
        "away_attack_home", "away_attack_away", "away_defence_home",
        "away_defence_away", "away_goals_for_per_game",
        "away_goals_against_per_game", "away_points_per_game",
        "away_win_rate"])


def test_c13_hat_kein_modell_angefasst():
    """
    GEAENDERT IN V2-C17.

    C13 hat einen Datenpfad repariert und kein Modell angefasst -
    daran aendert sich nichts. Aktiviert wurde spaeter das
    C16-Modell, ueber den regulaeren Weg. Die Zusicherung, um die es
    hier ging, wandert deshalb auf den Punkt: Das in C12 abgelehnte
    Modell ist nicht aktiv geworden.
    """
    from src.ml import model_registry as mr

    doc = mr.load_registry()
    for e in doc.get("models") or []:
        if e["evaluation_status"] == "rejected":
            assert e["stage"] != mr.STAGE_ACTIVE
            assert "approval" not in e

    eintrag, grund = mr.active_entry()
    if eintrag is None:
        assert grund == "no_active_model"
    else:
        assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED


def test_c13_hat_die_c12_gates_nicht_veraendert():
    from src.ml import c12_evaluation as c12

    assert c12.contract_fingerprint() == (
        "66cae83c51850070f44cffd73d5590c0c50dbd1bd674fbab314ead9ce2cb0ce4")


# ===========================================================================
# 6  Das Artefakt
# ===========================================================================

def test_vertrag_und_zustand_haben_getrennte_fingerabdruecke(artefakt):
    """
    DIE LEHRE AUS C11.

    Dort steckten Regel und Belegung in einem Wert. Jede Registrierung
    eines Modells veraenderte ihn, und niemand konnte mehr sehen, ob
    sich der Vertrag geaendert hatte oder nur der Zustand.
    """
    from src.ml import c13_contract as c13

    assert artefakt["contract_fingerprint"] != artefakt["state_fingerprint"]
    assert artefakt["contract_fingerprint"] == c13.contract_fingerprint()


def test_der_vertragsfingerabdruck_haengt_nicht_an_den_daten():
    """
    Neue Spieldaten sind kein Vertragsbruch. Der Vertragsfingerabdruck
    darf sich nur aendern, wenn jemand eine REGEL anfasst.
    """
    from src.ml import c13_contract as c13

    vorher = c13.contract_fingerprint()
    assert c13.contract_fingerprint() == vorher

    vertrag = c13.contract()
    assert "cl_coverage" not in json.dumps(vertrag)
    assert "matches" not in vertrag["profile_sources"]


def test_eine_geaenderte_regel_aendert_den_vertragsfingerabdruck(
        monkeypatch):
    """Die Gegenprobe. Ein Fingerabdruck, der nie reagiert, ist keiner."""
    from src.ml import c13_contract as c13

    vorher = c13.contract_fingerprint()
    monkeypatch.setitem(ns.NATIONAL_LEAGUES, "XX1",
                        {"provider": ns.PROVIDER_API_FOOTBALL,
                         "country": "XX", "name": "Testliga"})
    assert c13.contract_fingerprint() != vorher


def test_das_artefakt_ist_ohne_die_fluechtigen_felder_deterministisch(
        alle_zeilen):
    from src.ml import c13_contract as c13

    def ohne(a):
        return {k: v for k, v in a.items()
                if k not in ("created_at", "git_commit")}

    assert (ohne(c13.build_artifact(alle_zeilen))
            == ohne(c13.build_artifact(alle_zeilen)))


def test_das_artefakt_enthaelt_keine_rohdaten_und_keine_pfade(artefakt):
    """
    Keine Zugangsdaten, keine vollstaendigen Merkmalsvektoren, keine
    lokalen absoluten Pfade.
    """
    text = json.dumps(artefakt, ensure_ascii=False)
    for verboten in ("C:\\\\", "/home/", "Users\\\\", "api_key",
                     "APISPORTS_KEY", "token", "secret", "password"):
        assert verboten.lower() not in text.lower(), verboten


def test_das_artefakt_behauptet_keine_freigabe(artefakt):
    """
    C13 misst Abdeckung, nicht Guete. Das Artefakt muss das selbst
    sagen, damit es spaeter niemand als Freigabe liest.
    """
    behauptungen = " ".join(artefakt["what_this_does_not_claim"]).lower()
    assert "keine freigabe" in behauptungen
    assert "rejected" in behauptungen
    assert artefakt["unchanged_upstream"]["c9_schema_fingerprint"] == (
        "475b9be82c21c7ea977d71db1a714e3bc37fd4be2336897285730bc116694aa5")


def test_c13_aendert_werte_aber_keine_zielgroessen(alle_zeilen):
    """
    WARUM DER C9-ZIELFINGERABDRUCK TROTZDEM WANDERT.

    Der C9-Schemafingerabdruck bleibt gleich - C13 aendert keine
    Merkmalsmenge. Der Zielfingerabdruck wandert dennoch, und das
    verdient eine Erklaerung, statt spaeter als Widerspruch
    aufzutauchen:

    target_fingerprint hasht die Zielwerte GEMEINSAM mit den
    Identitaetsfeldern, und `evaluation_eligible` ist eines davon. Es
    steigt durch C13 von 238 auf 363 CL-Partien.

    Die Tore selbst sind unberuehrt. Genau das wird hier geprueft.
    """
    from src.ml import early_v2 as e9

    assert "evaluation_eligible" in e9.IDENTITY_FIELDS
    assert set(e9.TARGET_FIELDS) == {"home_goals", "away_goals", "outcome"}
    assert "evaluation_eligible" not in e9.TARGET_FIELDS

    # Kein Zielwert ist leer oder unplausibel geworden, und das
    # Ergebnis passt zu den Toren. 0 = Heimsieg, 1 = Unentschieden,
    # 2 = Auswaertssieg (go3_backtest._outcome_index).
    for zeile in alle_zeilen:
        tore_heim, tore_aus = zeile["home_goals"], zeile["away_goals"]
        assert isinstance(tore_heim, int) and tore_heim >= 0
        assert isinstance(tore_aus, int) and tore_aus >= 0
        erwartet = (0 if tore_heim > tore_aus
                    else 1 if tore_heim == tore_aus else 2)
        assert zeile["outcome"] == erwartet, zeile["row_id"]


def test_der_c9_schemafreeze_bleibt_die_verbindliche_groesse():
    """
    Der Freeze pinnt das SCHEMA, nicht die Daten. Waere es anders,
    duerfte nie wieder ein Spieltag hinzukommen.
    """
    import json as _json
    import pathlib as _pathlib

    from src.ml import early_v2 as e9

    manifest = _json.loads(_pathlib.Path(
        e9.MANIFEST_PATH).read_text(encoding="utf-8"))
    assert manifest["fingerprints"]["schema"] == e9.schema_fingerprint()
