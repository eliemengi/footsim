"""
Die einheitliche Point-in-Time-Profilfabrik fuer die Champions League.

WARUM ES DIESE DATEI GIBT
-------------------------
Bis V2-C1 gab es fuer dieselbe fachliche Frage - "wie stark war dieses
Team zu diesem Zeitpunkt?" - ZWEI Implementierungen:

    Training/Datensatz   src/ml/cl_dataset._Bestand
                         je Saison ueber cutoff gefiltert, Saisons auf
                         s <= season begrenzt, CL-Historie ueber alle
                         Saisons bis zur laufenden gepoolt

    Laufzeit             strength_provider._blend_top5_league_history_by_id
                         OHNE Stichtag, OHNE Saisonobergrenze, und die
                         CL-Quelle nur aus der EINEN laufenden Saison

Der Kommentar in cl_dataset sagte es selbst: "Aufbau wie
strength_provider._blend_top5_league_history_by_id ... Der Unterschied
ist der Stichtag". Zwei Fassungen derselben Fachlogik, von denen nur
eine zeitlich sauber war.

Die Folge war messbar: Ein Profil fuer die Saison 2024 war zur Laufzeit
identisch mit dem fuer 2025 - beide enthielten alle drei Saisons
2023-2025. Ein Modell, das auf stichtagsgenauen Profilen trainiert und
gemessen wurde, bekam im Betrieb einen anderen Informationsstand als im
Backtest.

Diese Datei ist die eine maßgebliche Quelle. Datensatz UND Laufzeit
rufen sie auf; es gibt keinen zweiten Weg mehr.

DER STICHTAG IST PFLICHT
------------------------
Es gibt bewusst KEINEN Standardwert. Kein "neueste Saison", kein
"neuester Snapshot", kein datetime.now() irgendwo tief in der Rechnung.
Wer ein Profil will, muss sagen, zu welchem Zeitpunkt.

Braucht die Laufzeit "jetzt", bestimmt sie diesen Zeitpunkt am RAND und
reicht ihn herein - runtime_cutoff() bietet dafuer genau eine Stelle.
Damit bleibt er in Tests steuerbar, statt an der Systemuhr zu haengen.

DIE REGEL AM STICHTAG SELBST
----------------------------
Uebernommen aus point_in_time.is_known_at und hier NICHT nachgebaut:

    Anstoss < Stichtag     bekannt
    Anstoss > Stichtag     unbekannt
    gleicher Tag           nur mit Uhrzeiten auf BEIDEN Seiten
                           entscheidbar; sonst gilt CUTOFF_INCLUSIVE

CUTOFF_INCLUSIVE ist False. Ein Spiel am Stichtag selbst gilt also als
unbekannt. Das ist die leak-sichere Wahl und der Grund, warum ein zu
prognostizierendes Spiel niemals Teil seines eigenen Profils wird.

WAS HIER NICHT PASSIERT
-----------------------
Kein Netzzugriff. Diese Fabrik liest ausschliesslich die lokale
Historie unter data/historical/. Braucht die Laufzeit Partien einer
noch laufenden Saison, die lokal nicht vorliegen, holt SIE sie und
reicht sie als extra_cl_matches herein - gefiltert wird auch dann hier,
mit demselben Stichtag. So bleibt die Fabrik deterministisch und ohne
Anbieter testbar, und trotzdem gibt es nur eine Filterstelle.
"""

from src.features.point_in_time import matches_known_at

#: Gilt ein Spiel am Stichtag selbst als bekannt?
#:
#: Nein. Bei gleichem Datum ohne verwertbare Uhrzeiten auf beiden Seiten
#: waere jede andere Antwort ein Leck: Das Zielspiel selbst traege dann
#: zu seiner eigenen Vorhersage bei.
CUTOFF_INCLUSIVE = False

#: Wie viele Saisons die nationale Historie zurueckreicht. Drei, weil
#: blend_profiles mit SEASON_DECAY 0,55 gewichtet - die vierte Saison
#: traegt danach unter 17 Prozent.
DEFAULT_SEASONS_BACK = 3

#: Die CL-Saisons, fuer die lokale Historie vorliegt.
DEFAULT_CL_SEASONS = (2023, 2024, 2025)

#: Die Stufen der Profilkaskade, maschinenlesbar. Datensatz und
#: Laufzeit benutzen dieselben Namen - vorher hiess dieselbe Stufe zur
#: Laufzeit "cl_current_season" und im Datensatz "cl_history_pit".
SOURCE_DOMESTIC = "domestic_pit"
SOURCE_CL_HISTORY = "cl_history_pit"
SOURCE_NEUTRAL = "neutral"
PROFILE_SOURCES = (SOURCE_DOMESTIC, SOURCE_CL_HISTORY, SOURCE_NEUTRAL)


class MissingCutoff(ValueError):
    """
    Es wurde ein Profil ohne Stichtag verlangt.

    Eigene Klasse, damit ein Aufrufer diesen Programmierfehler von einem
    fachlichen ValueError unterscheiden kann. Er wird nicht still
    behoben: Ein geratener Stichtag ist genau die Sorte Annahme, die
    V2-C1 beseitigt.
    """


def require_cutoff(cutoff):
    """
    Prueft und normalisiert einen Stichtag.

    Erlaubt sind date, datetime und Zeichenketten in ISO-Form. Der
    Rueckgabewert ist die ISO-Zeichenkette - sie ist hashbar und damit
    unmittelbar als Cacheschluessel brauchbar.

    Naive und zeitzonenbehaftete Zeitpunkte werden NICHT vermischt: Es
    wird ausschliesslich der Text verglichen, und point_in_time trennt
    Datums- und Uhrzeitanteil selbst. Ein Zeitzonenanhang wuerde dort
    den Uhrzeitvergleich verfaelschen, deshalb wird er hier abgewiesen
    statt stillschweigend abgeschnitten.
    """
    if cutoff is None:
        raise MissingCutoff(
            "Ein Point-in-Time-Profil braucht einen ausdruecklichen "
            "Stichtag. Fuer die Laufzeit liefert ihn runtime_cutoff().")

    text = cutoff.isoformat() if hasattr(cutoff, "isoformat") else str(cutoff)
    if len(text) < 10:
        raise MissingCutoff(f"Unbrauchbarer Stichtag: {cutoff!r}")

    if text.endswith("Z") or "+" in text[10:] or text[10:].count("-") > 0:
        raise MissingCutoff(
            f"Stichtag mit Zeitzonenangabe: {cutoff!r}. Die lokale "
            f"Historie traegt naive Zeitstempel; ein Vergleich waere "
            f"stillschweigend falsch.")

    return text


def runtime_cutoff(zeitpunkt=None):
    """
    Der Stichtag am Rand der Laufzeit.

    Die EINE Stelle, an der ein Laufzeitstichtag entsteht. Mit
    ausdruecklichem Zeitpunkt normalisiert sie ihn nur - etwa den von
    fixture_cutoff() aufgeloesten Anstoss eines historischen Spiels.
    Ohne Angabe gilt "jetzt".

    "Jetzt" ist bewusst der heutige Tag um 12 Uhr und nicht die
    laufende Uhrzeit: Dieselbe Simulation soll bei gleichem Startwert
    dasselbe Ergebnis liefern, und ein Stichtag, der mit jeder Sekunde
    weiterlaeuft, waere damit unvereinbar. Dieselbe Konvention benutzt
    bereits league_match_sim.simulate_league_match fuer seinen kickoff.
    """
    from datetime import date, datetime, time as dtime

    if zeitpunkt is None:
        zeitpunkt = datetime.combine(date.today(), dtime(12, 0))
    return require_cutoff(zeitpunkt)


#: Die Phasen, die die CL-Einzelspielsimulation fachlich abdeckt.
#: Innerhalb dieser Phasen ist eine Paarung (home_id, away_id) je
#: Saison nachweislich eindeutig - nachgemessen ueber 2023-2025.
#: Doppelte Paarungen entstehen ausschliesslich, wenn dieselben zwei
#: Mannschaften spaeter noch einmal im K.-o. aufeinandertreffen.
REGULAR_STAGES = ("GROUP_STAGE", "LEAGUE_STAGE")


def fixture_cutoff(season, home_id, away_id, repository=None):
    """
    Der Anstoss EINER Begegnung - aufgeloest aus der eigenen Historie.

    WARUM DAS BACKEND DAS SELBST TUT
    Der Stichtag entscheidet, welche Information in eine Prognose
    einfliesst. Ihn vom Client entgegenzunehmen hiesse, eine fachliche
    Wahrheit von aussen bestimmen zu lassen. Alles Noetige liegt hier
    ohnehin: Saison und Mannschaften stehen im Request, das Datum steht
    in derselben lokalen Historie, aus der auch die Profile entstehen.
    Deshalb gibt es kein neues Feld in der Nutzlast und keine
    Manipulationsflaeche.

    AUFLOESUNG
      1. Partien der Saison mit genau dieser Paarung suchen.
      2. Die regulaere Phase hat Vorrang - sie ist das, was die
         Einzelspielsimulation abdeckt, und dort ist die Paarung
         eindeutig.
      3. Bleiben mehrere (zwei K.-o.-Legs), gewinnt die FRUEHESTE.
         Das ist die leak-sichere Richtung: weniger Information, nie
         mehr.

    Rueckgabe: das Anstossdatum als ISO-Zeichenkette, oder None, wenn
    die Begegnung nicht in der Historie steht. None heisst "kuenftig
    oder unbekannt" - der Aufrufer nimmt dann den Laufzeitstichtag und
    faellt ausdruecklich NICHT auf die komplette Saison zurueck.
    """
    if season is None or home_id is None or away_id is None:
        return None

    repository = repository or PitProfileRepository()
    try:
        payload = repository.cl_payload(season)
    except Exception:
        # Eine unlesbare Historie darf keine Prognose verhindern.
        return None

    treffer = []
    for match in (payload or {}).get("matches") or []:
        if match.get("home_id") != home_id or match.get("away_id") != away_id:
            continue
        datum = match.get("date")
        if not datum:
            continue
        treffer.append((match.get("stage") not in REGULAR_STAGES, datum))

    if not treffer:
        return None

    # Sortiert nach (K.-o.? , Datum): regulaere Phase zuerst, darin die
    # frueheste Partie.
    treffer.sort()
    return treffer[0][1]


class PitProfileRepository:
    """
    Haelt geladene Saisondateien und die je Stichtag gebauten Profile.

    Ohne diesen Zwischenspeicher baute der Datensatz fuer jede der rund
    500 CL-Partien die Profile aller fuenf Ligen neu - obwohl sich viele
    Partien denselben Spieltag teilen.

    DER STICHTAG STEHT IM SCHLUESSEL
    Jeder Zwischenspeicher hier ist auf (season, cutoff) verschluesselt.
    Ein Profil zum 01.10.2024 kann deshalb niemals durch einen Treffer
    fuer den 01.03.2025 ersetzt werden - genau der Fehler, den ein nur
    auf die Saison verschluesselter Speicher erlaubt haette.

    Eine Instanz ist nicht threadsicher und auch nicht dafuer gedacht:
    Sie lebt fuer die Dauer eines Datensatzbaus oder eines Requests.
    """

    def __init__(self, seasons_back=DEFAULT_SEASONS_BACK,
                 cl_seasons=DEFAULT_CL_SEASONS):
        self.seasons_back = seasons_back
        self.cl_seasons = tuple(cl_seasons)
        self._saisons = {}
        self._domestic = {}
        self._cl = {}
        self._cl_payloads = {}

    # -- Rohdaten ---------------------------------------------------------

    def domestic_payload(self, api_code, season):
        from src.data.historical_loader import load_season

        key = (api_code, season)
        if key not in self._saisons:
            self._saisons[key] = load_season(api_code, season)
        return self._saisons[key]

    def cl_payload(self, season):
        from src.data.historical_loader import load_cl_season

        if season not in self._cl_payloads:
            self._cl_payloads[season] = load_cl_season(season)
        return self._cl_payloads[season]

    # -- Profile ----------------------------------------------------------

    def domestic_profiles(self, season, cutoff):
        """
        Top-5-Ligaprofile zum Stichtag, ueber alle fuenf Ligen vereinigt.

        Je Liga die verfuegbaren Saisons blenden, dann je Team das Profil
        mit der groesseren Datenbasis behalten. Ein Team koennte
        theoretisch ueber mehrere Ligen erscheinen (etwa bei einem
        Datenfehler); dann gewinnt die groessere Grundlage.

        ZWEI ZEITLICHE GRENZEN, BEIDE NOETIG
          1. Saisonobergrenze s <= season - keine spaetere Saison.
          2. Stichtag innerhalb jeder Saison - keine spaetere Partie.

        Die erste allein liesse noch den Rest der laufenden Saison
        durch, die zweite allein die kompletten Folgesaisons. Genau
        Letzteres tat der alte Laufzeitpfad.
        """
        cutoff = require_cutoff(cutoff)

        key = (season, cutoff)
        if key in self._domestic:
            return self._domestic[key]

        from src.data.historical_loader import (
            AVAILABLE_HISTORICAL_SEASONS, LEAGUE_CODES)
        from src.features.team_profile import blend_profiles, build_season_profiles

        # Neueste zuerst - blend_profiles gewichtet in dieser Reihenfolge.
        kandidaten = [s for s in sorted(AVAILABLE_HISTORICAL_SEASONS, reverse=True)
                      if s <= season][:self.seasons_back]

        vereinigt = {}
        for api_code in LEAGUE_CODES.values():
            je_saison = []
            for s in kandidaten:
                payload = self.domestic_payload(api_code, s)
                if not payload:
                    continue
                gebaut = build_season_profiles(payload, cutoff=cutoff)
                if gebaut["profiles"]:
                    je_saison.append(gebaut)

            if not je_saison:
                continue

            for team_id, profil in blend_profiles(je_saison).items():
                vorhanden = vereinigt.get(team_id)
                if vorhanden is None or (profil.get("matches_used", 0)
                                         > vorhanden.get("matches_used", 0)):
                    vereinigt[team_id] = profil

        self._domestic[key] = vereinigt
        return vereinigt

    def cl_history(self, season, cutoff, extra_matches=None):
        """
        Profile und Ligaschnitt aus FRUEHEREN CL-Partien.

        Gepoolt ueber alle CL-Saisons bis einschliesslich der laufenden,
        gefiltert auf das, was zum Stichtag bereits gespielt war. Damit
        stehen fuer eine Mannschaft ohne Top-5-Historie sowohl die
        Vorsaisons als auch die bisherigen Partien der laufenden Saison
        zur Verfuegung - und nichts darueber hinaus.

        extra_matches: Partien, die lokal nicht vorliegen - typischerweise
        eine laufende Saison, die die Laufzeit beim Anbieter geholt hat.
        Sie durchlaufen DENSELBEN Stichtagsfilter. Diese Fabrik holt sie
        nicht selbst: Ein Netzzugriff mitten in der Profilrechnung waere
        weder deterministisch noch ohne Anbieter testbar.

        Rueckgabe: (profile, league_avg, bekannte_partien).

        Die dritte Stelle ist die LISTE der benutzten Partien, nicht nur
        ihre Anzahl: Der Aufrufer baut daraus seine Herkunftsangabe und
        soll dafuer nicht ein zweites Mal filtern muessen.
        """
        cutoff = require_cutoff(cutoff)

        # extra_matches gehen NICHT in den Schluessel: Sie sind je
        # Aufruf verschieden und wuerden den Speicher wirkungslos
        # machen. Stattdessen wird bei Zusatzpartien gar nicht
        # zwischengespeichert - lieber langsam als falsch.
        key = (season, cutoff)
        if not extra_matches and key in self._cl:
            return self._cl[key]

        from src.features.team_profile import build_season_profiles

        gepoolt, teams = [], {}
        for s in sorted(self.cl_seasons):
            if s > season:
                break
            payload = self.cl_payload(s)
            if not payload:
                continue
            gepoolt.extend(payload.get("matches") or [])
            for tid, info in (payload.get("teams") or {}).items():
                try:
                    teams[int(tid)] = info
                except (TypeError, ValueError):
                    continue

        if extra_matches:
            gepoolt.extend(extra_matches)

        # Ein einziger Filterpunkt fuer die gesamte CL-Historie.
        bekannt = [m for m in matches_known_at(gepoolt, cutoff,
                                               inclusive=CUTOFF_INCLUSIVE)
                   if m.get("home_goals") is not None
                   and m.get("away_goals") is not None]

        gebaut = build_season_profiles({"matches": bekannt, "teams": teams})
        ergebnis = (gebaut["profiles"], gebaut["league_avg"], bekannt)

        if not extra_matches:
            self._cl[key] = ergebnis
        return ergebnis

    def team_names(self, season):
        payload = self.cl_payload(season) or {}
        namen = {}
        for tid, info in (payload.get("teams") or {}).items():
            try:
                namen[int(tid)] = (info or {}).get("name")
            except (TypeError, ValueError):
                continue
        return namen


def resolve_profile(team_id, team_name, domestic, cl_profiles):
    """
    Die Kaskade fuer EIN Team.

    Rueckgabe: (profil, quelle, tiefe).

    tiefe ist die Zahl der Partien, auf denen das Profil beruht - bei
    neutral_profile null. Sie geht NICHT als Modellmerkmal in den
    Datensatz (siehe feature_groups: Merkmalstiefe ist eine Eigenschaft
    der Datenherkunft, keine des Fussballs), wohl aber als
    Auswertungsgroesse.
    """
    from src.features.team_profile import neutral_profile

    profil = domestic.get(team_id)
    if profil is not None:
        return profil, SOURCE_DOMESTIC, profil.get("matches_used") or 0

    profil = cl_profiles.get(team_id)
    if profil is not None:
        return profil, SOURCE_CL_HISTORY, profil.get("matches_used") or 0

    return neutral_profile(team_id, team_name), SOURCE_NEUTRAL, 0


def cl_profile_sources(season, cutoff, repository=None, extra_cl_matches=None):
    """
    Die beiden Profilquellen einer CL-Partie - zum Stichtag.

    Das ist der Einstieg, den die Laufzeit benutzt. Er liefert bewusst
    KEINE fertigen Profile je Team, sondern die Quellen, aus denen
    resolve_profile je Mannschaft waehlt: Fuer eine Einzelspiel-
    simulation werden nur zwei der 36 Teilnehmer gebraucht.

    Rueckgabe:
    {
      "domestic_by_id":  { team_id: profil },
      "cl_history_by_id": { team_id: profil },
      "league_avg": {...} oder None,
      "cutoff": "...",
      "cl_matches_known": int,
    }

    league_avg ist None, wenn zum Stichtag noch keine einzige CL-Partie
    gespielt war. Der Ersatzwert gehoert nicht hierher - er ist eine
    Produktentscheidung des Aufrufers und wird dort ausgewiesen.
    """
    cutoff = require_cutoff(cutoff)
    repository = repository or PitProfileRepository()

    domestic = repository.domestic_profiles(season, cutoff)
    cl_profile, cl_avg, cl_basis = repository.cl_history(
        season, cutoff, extra_matches=extra_cl_matches)

    return {
        "domestic_by_id": domestic,
        "cl_history_by_id": cl_profile,
        "league_avg": cl_avg if (cl_avg or {}).get("matches") else None,
        "cutoff": cutoff,
        "cl_matches_used": cl_basis,
        "cl_matches_known": len(cl_basis),
    }


# ---------------------------------------------------------------------------
# Gegnerstaerke zum Zeitpunkt der DAMALIGEN Partie (V2-C4)
# ---------------------------------------------------------------------------

class PitStrengthAtDate:
    """
    Wie stark war eine Mannschaft am Tag EINER FRUEHEREN Partie?

    WOZU DAS NOETIG IST
    Die Gegneradjustierung der Form fragt: "Wie schwer waren die
    Gegner, gegen die zuletzt gespielt wurde?" Die naheliegende
    Abkuerzung waere, die Staerke zum Stichtag des ZIELSPIELS zu
    nehmen - ein Lookup, fertig. Sie waere sogar leckagefrei
    gegenueber der Prognose, denn dieser Stichtag liegt vor dem
    Anpfiff.

    Sie waere trotzdem falsch. Ein Gegner, der im September geschlagen
    wurde und danach zehnmal gewann, war im September nicht der
    Verein, als der er im Dezember dasteht. Und schlimmer: Sein Profil
    zum Dezemberstichtag enthaelt das Ergebnis genau der Septemberpartie,
    die gerade bewertet wird. Der Wert wuesste dann bereits, wie das
    Spiel ausgegangen ist, dessen Schwierigkeit er beschreiben soll.

    Diese Klasse loest das, indem sie fuer jede historische Partie den
    Stichtag DIESER Partie benutzt.

    KOSTEN UND ZWISCHENSPEICHER
    Ein zusaetzlicher Stichtag kostet rund zehn Millisekunden, sobald
    die Saisondateien einmal gelesen sind - nachgemessen. Der
    Zwischenspeicher steht auf (season, cutoff), nie auf der Saison
    allein: Ein Wert vom 5. November darf niemals einen Treffer fuer
    den 12. November liefern.

    Die Saison im Schluessel ist die Saison des ZIELSPIELS und dient
    als Obergrenze. Der Stichtag schneidet innerhalb jeder Saison ab,
    deshalb kann eine spaetere Saison durch ihn nichts beitragen -
    beide Grenzen zusammen sind der Vertrag aus V2-C1.
    """

    def __init__(self, repository=None, season=None):
        self.repository = repository or PitProfileRepository()
        self.season = season
        self._cache = {}

    def _lookup(self, season, cutoff):
        schluessel = (season, cutoff)
        if schluessel in self._cache:
            return self._cache[schluessel]

        from src.features.go3_backtest import _team_strength_scalar

        domestic = self.repository.domestic_profiles(season, cutoff)
        cl_profile, _, _ = self.repository.cl_history(season, cutoff)

        # Dieselbe Rangfolge wie resolve_profile: Ligahistorie schlaegt
        # CL-Historie. Eine zweite Rangfolge waere eine zweite Wahrheit.
        werte = {}
        for team_id, profil in {**cl_profile, **domestic}.items():
            wert = _team_strength_scalar(profil)
            if wert is not None:
                werte[team_id] = float(wert)

        self._cache[schluessel] = werte
        return werte

    def __call__(self, team_id, kickoff, season=None):
        """
        Staerke einer Mannschaft STRIKT VOR dem angegebenen Zeitpunkt.

        Rueckgabe None, wenn ueber die Mannschaft zu diesem Zeitpunkt
        nichts bekannt war - ein Aufsteiger am ersten Spieltag, ein
        unterklassiger Pokalgegner. None heisst hier "unbekannt" und
        niemals "schwach".
        """
        if team_id is None or kickoff is None:
            return None
        ziel = season if season is not None else self.season
        if ziel is None:
            raise MissingCutoff(
                "PitStrengthAtDate braucht eine Saisonobergrenze - ohne "
                "sie waere nicht bestimmt, welche Saisons ueberhaupt "
                "beitragen duerfen")
        return self._lookup(ziel, kickoff).get(team_id)
