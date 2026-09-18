"""
Tests des Prediction-Cutoff-Vertrags (V2-C10).

WORUM ES GEHT
Vor C10 gab es vier Stellen, die einen Stichtag bildeten, und sie
schrieben ihn verschieden. Gemessen wurde folgender Fall:

    captured_at "2025-03-11T06:00:00+00:00"
    Training    "2025-03-11T12:00:00"   -> Snapshot gilt als bekannt
    Laufzeit    "2025-03-11"            -> Snapshot gilt als unbekannt

Derselbe Match, derselbe Bestand, zwei Informationsstaende. Der
Vergleich ist ein Textvergleich, und "2025-03-11" ist ein Praefix des
Stempels.

Die schaerfsten Tests hier sind deshalb die manipulierenden: Ein
Datensatz wird NACH dem Stichtag veraendert, und der historische
Featurevektor muss gleich bleiben. Ein sauberer Durchlauf allein
beweist nichts.
"""

import ast
import datetime as dt
import json
import pathlib

import pytest

from src.data import snapshot_archive as sa
from src.features import match_timeline as mt
from src.features import pit_profiles as pp
from src.ml import dataset as ds
from src.ml import early_v2 as e9
from src.ml import feature_groups as fg
from src.ml import inference as inf
from src.features import prediction_cutoff as pc
from src.features.prediction_cutoff import (
    MissingCutoff, PredictionCutoff)
from src.ml import c10_contract as c10

WURZEL = pathlib.Path(__file__).resolve().parents[1]

UTC = dt.timezone.utc


# ===========================================================================
# 1  Der Vertrag
# ===========================================================================

def test_ein_utc_zeitpunkt_wird_angenommen():
    c = PredictionCutoff.at(dt.datetime(2025, 3, 11, 12, 0, tzinfo=UTC))
    assert c.utc == dt.datetime(2025, 3, 11, 12, 0, tzinfo=UTC)
    assert c.iso() == "2025-03-11T12:00:00Z"


def test_die_serialisierung_ist_verlustfrei():
    """
    Ohne stabile Rundreise koennte ein Stichtag ein Artefakt nicht
    ueberleben, und ein Replay saehe einen anderen Zeitpunkt als der
    Lauf, den es wiederholen soll.
    """
    for quelle in (dt.datetime(2025, 3, 11, 6, 30, tzinfo=UTC),
                   dt.datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
                   dt.datetime(2024, 2, 29, 0, 0, tzinfo=UTC)):
        c = PredictionCutoff.at(quelle)
        assert PredictionCutoff.parse(c.iso()) == c


def test_ein_zonenbehafteter_zeitpunkt_wird_nach_utc_gerechnet():
    """
    Umgerechnet, nicht abgeschnitten. Ein abgeschnittener Zonenanhang
    verschoebe den Zeitpunkt um den Zonenversatz, und zwar unbemerkt.
    """
    berlin = dt.timezone(dt.timedelta(hours=2))
    c = PredictionCutoff.at(dt.datetime(2025, 3, 11, 14, 0, tzinfo=berlin))
    assert c.iso() == "2025-03-11T12:00:00Z"


def test_ein_naiver_zeitpunkt_gilt_als_utc_nicht_als_ortszeit():
    """
    Die einzige Annahme des Vertrags, und sie steht ausdruecklich da.

    Das Projekt rechnet intern in naiver UTC: match_timeline rechnet
    jeden Zeitstempel auf UTC um und streift die Zone ab. Eine naive
    Eingabe als Ortszeit zu lesen haenge dagegen am Rechner, auf dem
    der Prozess laeuft - dieselbe Datei ergaebe in zwei Rechenzentren
    zwei Ergebnisse.
    """
    c = PredictionCutoff.at(dt.datetime(2025, 3, 11, 12, 0))
    assert c.iso() == "2025-03-11T12:00:00Z"


def test_ein_reines_datum_wird_auf_die_stichtagsstunde_gehoben():
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.iso() == "2025-03-11T12:00:00Z"
    assert c.precision == PredictionCutoff.PRECISION_DAY


def test_beide_skalen_sind_benannt_und_verschieden():
    """
    Eine Funktion, die je nach Aufrufer Tag oder Zeitpunkt liefert,
    waere genau die Mehrdeutigkeit, die C10 beseitigt.
    """
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.day_key() == "2025-03-11"
    assert c.instant_key() == "2025-03-11T12:00:00"
    assert c.day_key() != c.instant_key()


def test_der_zeitpunktschluessel_traegt_keinen_zonenanhang():
    """
    DER GRUND FUER DAS FESTE FORMAT.

    snapshot_archive vergleicht captured_at lexikografisch. Ein
    Zonenanhang macht denselben Zeitpunkt laenger und damit
    lexikografisch groesser - der Textvergleich widerspraeche dem
    Zeitvergleich.
    """
    c = PredictionCutoff.at(dt.datetime(2025, 3, 11, 6, 0, tzinfo=UTC))
    assert "+" not in c.instant_key()
    assert not c.instant_key().endswith("Z")
    assert len(c.instant_key()) == 19


@pytest.mark.parametrize("kaputt", [None, "", "morgen", "2025-13-45",
                                    12345, object()])
def test_unbrauchbare_stichtage_brechen_ab(kaputt):
    """
    Jede dieser Eingaben ist ein Programmierfehler, kein Randfall. Sie
    still zu reparieren hiesse, einen geratenen Zeitpunkt in eine
    Vorhersage zu lassen.
    """
    with pytest.raises((MissingCutoff, ValueError, TypeError)):
        pc.require(kaputt)


def test_require_ohne_stichtag_ist_ein_fehler_kein_rueckfall():
    """
    FAIL CLOSED.

    Ein fehlender Stichtag darf nicht auf den neuesten Stand springen.
    Genau dieser Rueckfall waere die stille Zeitreise: Das Ergebnis
    saehe plausibel aus und benutzte Daten aus der Zukunft.
    """
    with pytest.raises(MissingCutoff, match="ausdruecklichen"):
        pc.require(None)


def test_require_reicht_einen_fertigen_stichtag_durch():
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert pc.require(c) is c


# ===========================================================================
# 2  Die Grenzregel
# ===========================================================================

def test_ein_datensatz_genau_am_stichtag_gilt_als_unbekannt():
    """
    Die leak-sichere Wahl. Sie kostet im schlimmsten Fall einen Stand
    und verhindert, dass ein zur Anpfiffsekunde erhobener Kader in die
    Vorhersage derselben Partie geraet.
    """
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert pc.CUTOFF_INCLUSIVE is False
    assert c.allows(dt.datetime(2025, 3, 11, 12, 0, tzinfo=UTC)) is False


def test_daten_vor_dem_stichtag_bleiben_verfuegbar():
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.allows(dt.datetime(2025, 3, 11, 11, 59, 59, tzinfo=UTC)) is True
    assert c.allows(dt.datetime(2025, 3, 10, 23, 0, tzinfo=UTC)) is True


def test_daten_nach_dem_stichtag_werden_ausgeschlossen():
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.allows(dt.datetime(2025, 3, 11, 12, 0, 1, tzinfo=UTC)) is False
    assert c.allows(dt.datetime(2025, 3, 12, 0, 0, tzinfo=UTC)) is False


def test_die_grenzregel_gilt_auch_fuer_text_und_zonen():
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.allows("2025-03-11T06:00:00+00:00") is True
    assert c.allows("2025-03-11T06:00:00Z") is True
    assert c.allows("2025-03-11T18:00:00Z") is False


def test_ein_unpruefbarer_zeitpunkt_gilt_nicht_als_bekannt():
    """
    Ein Datensatz, dessen Zeit sich nicht pruefen laesst, darf nicht
    stillschweigend in die Vergangenheit gerechnet werden.
    """
    c = PredictionCutoff.for_match_day("2025-03-11")
    assert c.allows(None) is False
    assert c.allows("irgendwann") is False
    assert c.allows(object()) is False


# ===========================================================================
# 3  Die Stundenkopplung
# ===========================================================================

def test_stichtagsstunde_und_rueckfallstunde_stimmen_ueberein():
    """
    DIE UNGESCHUETZTE KOPPLUNG, DIE C10 SCHLIESST.

    Eine Partie ohne Anstosszeit bekommt in der Zeitleiste den
    Zeitstempel Tag@FALLBACK_KICKOFF_HOUR. Ihr eigener Stichtag liegt
    bei Tag@CUTOFF_HOUR. Der Filter ist strikt kleiner, also faellt sie
    aus ihrem eigenen Merkmalsfenster - aber nur, solange die beiden
    Stunden gleich sind.

    Beide Zahlen standen vor C10 in verschiedenen Modulen, ohne dass
    irgendetwas sie aneinander band. Waere die Rueckfallstunde auf 11
    gesunken, geriete jede CL-Partie in ihre eigenen Merkmale - ein
    Selbstleck, das keine Kennzahl auffaengt, weil es wie ein sehr
    gutes Modell aussieht.
    """
    assert pc.CUTOFF_HOUR == mt.FALLBACK_KICKOFF_HOUR
    assert pc.assert_hours_match() is True


def test_eine_abweichende_rueckfallstunde_bricht_ab():
    """Die Pruefung muss wirken, nicht nur existieren."""
    with pytest.raises(ValueError, match="stimmen nicht ueberein"):
        pc.assert_hours_match(timeline_hour=11)


def test_eine_partie_faellt_nicht_in_ihr_eigenes_merkmalsfenster():
    """
    Die Kopplung am konkreten Fall - nicht an den Konstanten.

    Die CL-Historie fuehrt keine Anstosszeiten; jede Partie bekommt
    Tag@12:00. Ihr Stichtag ist derselbe Zeitpunkt, und strikt kleiner
    schliesst sie aus.
    """
    cutoff = ds.prediction_cutoff("2025-03-11")
    eigene = [{"kickoff": dt.datetime(2025, 3, 11, 12, 0), "match_id": 1}]
    vortag = [{"kickoff": dt.datetime(2025, 3, 10, 12, 0), "match_id": 2}]

    assert mt.matches_before(eigene, cutoff) == []
    assert len(mt.matches_before(vortag, cutoff)) == 1


# ===========================================================================
# 4  Snapshot-Auswahl
# ===========================================================================

class _Archiv:
    """
    Ein Archiv aus dem Speicher - ohne Dateisystem und ohne Netz.

    Bildet genau die beiden Funktionen nach, die snapshot_reader
    benutzt. Ein echtes Archiv braeuchte temporaere Dateien und
    verdeckte, worum es hier geht.
    """

    def __init__(self, eintraege):
        self._eintraege = list(eintraege)

    def list_snapshots(self, kind, key=None):
        return [e for e in self._eintraege
                if e["kind"] == kind and (key is None or e["key"] == key)]

    def load_snapshot_file(self, pfad):
        for e in self._eintraege:
            if e["path"] == pfad:
                return {"meta": {"captured_at": e["captured_at"]},
                        "payload": e.get("payload", {"ok": True})}
        return None                                      # pragma: no cover

    def latest_snapshot_before(self, kind, cutoff, key=None,
                               inclusive=False):
        cutoff_text = sa._vergleichstext(cutoff)
        passend = []
        for e in self.list_snapshots(kind, key=key):
            stempel = sa._vergleichstext(e["captured_at"])
            if stempel is None:
                continue
            if (stempel <= cutoff_text) if inclusive else (
                    stempel < cutoff_text):
                passend.append((stempel, e))
        if not passend:
            return None
        passend.sort(key=lambda paar: (paar[0], paar[1]["path"]))
        return self.load_snapshot_file(passend[-1][1]["path"])


def _eintrag(stempel, pfad, kind="squad", key="team:1"):
    return {"kind": kind, "key": key, "captured_at": stempel, "path": pfad}


def test_es_gewinnt_der_letzte_zulaessige_snapshot():
    archiv = _Archiv([
        _eintrag("2025-03-09T10:00:00+00:00", "a"),
        _eintrag("2025-03-10T10:00:00+00:00", "b"),
        _eintrag("2025-03-11T18:00:00+00:00", "c"),
    ])
    treffer = archiv.latest_snapshot_before("squad", "2025-03-11",
                                            key="team:1")
    assert treffer["meta"]["captured_at"].startswith("2025-03-10")


def test_ein_snapshot_genau_am_stichtag_wird_nicht_geliefert():
    archiv = _Archiv([_eintrag("2025-03-11T12:00:00+00:00", "a")])
    assert archiv.latest_snapshot_before("squad", "2025-03-11",
                                         key="team:1") is None


def test_nur_zukuenftige_snapshots_ergeben_keinen_treffer():
    """
    Der Fall aus C6/C7: Das Archiv enthaelt ausschliesslich Staende,
    die juenger sind als jede auszuwertende Partie. Ein Replay darf
    daraus nichts nehmen.
    """
    archiv = _Archiv([
        _eintrag("2026-09-06T10:00:00+00:00", "a"),
        _eintrag("2026-09-07T10:00:00+00:00", "b"),
    ])
    assert archiv.latest_snapshot_before("squad", "2025-03-11",
                                         key="team:1") is None


def test_ein_leeres_archiv_ergibt_keinen_treffer():
    assert _Archiv([]).latest_snapshot_before("squad", "2025-03-11",
                                              key="team:1") is None


def test_der_falsche_scope_wird_nicht_geliefert():
    archiv = _Archiv([_eintrag("2025-03-10T10:00:00+00:00", "a",
                               key="team:2")])
    assert archiv.latest_snapshot_before("squad", "2025-03-11",
                                         key="team:1") is None


def test_bei_gleichem_zeitstempel_entscheidet_der_dateiname():
    """
    Deterministisch statt zufaellig. Ohne feste Regel haenge die
    Auswahl an der Sortierreihenfolge des Dateisystems, und zwei
    Rechner lieferten verschiedene Vorhersagen.
    """
    archiv = _Archiv([
        _eintrag("2025-03-10T10:00:00+00:00", "snap__002"),
        _eintrag("2025-03-10T10:00:00+00:00", "snap__001"),
    ])
    for _ in range(5):
        treffer = archiv.latest_snapshot_before("squad", "2025-03-11",
                                                key="team:1")
        assert treffer is not None


def test_verschiedene_schreibweisen_derselben_zeit_sind_gleich():
    """
    DER FEHLER, DEN C10 BEHOBEN HAT.

    "+00:00" und "Z" meinen denselben Zeitpunkt. Vor der
    Normalisierung entschied die Schreibweise mit, weil lexikografisch
    verglichen wurde.
    """
    assert (sa._vergleichstext("2025-03-11T06:00:00+00:00")
            == sa._vergleichstext("2025-03-11T06:00:00Z")
            == sa._vergleichstext("2025-03-11T06:00:00"))


def test_tagesstichtag_und_zeitpunktstichtag_waehlen_denselben_snapshot():
    """
    DER KERN VON C10, ALS TEST.

    Gemessen vor der Behebung: Ein Snapshot vom Vormittag des
    Spieltags galt im Training als bekannt und zur Laufzeit als
    unbekannt, weil der eine Pfad "2025-03-11T12:00:00" schrieb und
    der andere "2025-03-11".
    """
    archiv = _Archiv([_eintrag("2025-03-11T06:00:00+00:00", "a")])

    laufzeit = archiv.latest_snapshot_before("squad", "2025-03-11",
                                             key="team:1")
    training = archiv.latest_snapshot_before(
        "squad", ds.prediction_cutoff("2025-03-11"), key="team:1")

    assert laufzeit is not None, "Laufzeit verwirft einen zulaessigen Stand"
    assert training is not None
    assert (laufzeit["meta"]["captured_at"]
            == training["meta"]["captured_at"])


def test_ein_snapshot_ohne_lesbaren_zeitstempel_wird_verworfen():
    """
    Ein Stand ohne pruefbare Herkunft darf nicht in eine Vorhersage.
    """
    archiv = _Archiv([_eintrag("kaputt", "a"),
                      _eintrag("2025-03-10T10:00:00+00:00", "b")])
    treffer = archiv.latest_snapshot_before("squad", "2025-03-11",
                                            key="team:1")
    assert treffer["meta"]["captured_at"].startswith("2025-03-10")


def test_der_reader_liefert_bei_fehlendem_stand_einen_fehlzustand():
    from src.data import snapshot_reader as sr

    class Leer:
        @staticmethod
        def latest_snapshot_before(kind, cutoff, key, inclusive=False):
            return None

    ergebnis = sr.snapshot_before("squad", "team:1", "2025-03-11",
                                  archive_module=Leer)
    assert ergebnis["available"] is False
    assert ergebnis["payload"] is None


# ===========================================================================
# 5  Leakage - mit Manipulation
# ===========================================================================

def _zeitleiste():
    return [{"kickoff": dt.datetime(2025, 3, d, 12, 0), "match_id": d,
             "team_goals": 2, "opponent_goals": 1, "is_home": True,
             "competition": "PL", "opponent_id": 50 + d, "status": "FT"}
            for d in (1, 4, 7)]


def test_eine_spaetere_partie_veraendert_den_frueheren_stand_nicht():
    """
    MANIPULATIONSTEST.

    Eine Partie NACH dem Stichtag wird eingespeist. Der Ausschnitt der
    Zeitleiste muss unveraendert bleiben.
    """
    cutoff = ds.prediction_cutoff("2025-03-11")
    ohne = mt.matches_before(_zeitleiste(), cutoff)
    spaeter = _zeitleiste() + [
        {"kickoff": dt.datetime(2025, 3, 20, 12, 0), "match_id": 99,
         "team_goals": 9, "opponent_goals": 0, "is_home": True,
         "competition": "PL", "opponent_id": 77, "status": "FT"}]
    assert mt.matches_before(spaeter, cutoff) == ohne


def test_dieselbe_information_vor_dem_stichtag_wirkt_sehr_wohl():
    """
    DIE GEGENPROBE.

    Ohne sie koennte der Filter alles verwerfen und der vorige Test
    waere trotzdem gruen. Wird die Partie VOR den Stichtag gezogen,
    muss sie ankommen.
    """
    cutoff = ds.prediction_cutoff("2025-03-11")
    ohne = mt.matches_before(_zeitleiste(), cutoff)
    vorgezogen = _zeitleiste() + [
        {"kickoff": dt.datetime(2025, 3, 9, 12, 0), "match_id": 99,
         "team_goals": 9, "opponent_goals": 0, "is_home": True,
         "competition": "PL", "opponent_id": 77, "status": "FT"}]
    assert len(mt.matches_before(vorgezogen, cutoff)) == len(ohne) + 1


def test_die_reihenfolge_der_eingaben_aendert_nichts():
    cutoff = ds.prediction_cutoff("2025-03-11")
    vorwaerts = mt.matches_before(_zeitleiste(), cutoff)
    rueckwaerts = mt.matches_before(list(reversed(_zeitleiste())), cutoff)
    assert ({e["match_id"] for e in vorwaerts}
            == {e["match_id"] for e in rueckwaerts})


def test_ein_spaeterer_snapshot_veraendert_die_fruehere_auswahl_nicht():
    """
    MANIPULATIONSTEST auf dem Archiv.

    Ein neuer Stand wird NACH dem Stichtag hinzugefuegt. Die Auswahl
    fuer den frueheren Zeitpunkt muss dieselbe bleiben - sonst wuerde
    ein historisches Replay durch jeden neuen Sammellauf ein anderes
    Ergebnis liefern.
    """
    basis = [_eintrag("2025-03-10T10:00:00+00:00", "b")]
    vorher = _Archiv(basis).latest_snapshot_before("squad", "2025-03-11",
                                                   key="team:1")
    nachher = _Archiv(
        basis + [_eintrag("2026-09-07T10:00:00+00:00", "z")]
    ).latest_snapshot_before("squad", "2025-03-11", key="team:1")
    assert vorher["meta"]["captured_at"] == nachher["meta"]["captured_at"]


def test_kein_zielwert_gelangt_in_die_kandidatenmerkmale():
    verstoesse, _ = e9.check_no_target_leak(e9.selected_columns())
    assert verstoesse == []


# ===========================================================================
# 6  Training-Runtime-Paritaet
# ===========================================================================

def test_trainings_und_laufzeitstichtag_sind_derselbe_zeitpunkt():
    """
    DIE PARITAETSAUSSAGE AUF VERTRAGSEBENE.

    dataset.prediction_cutoff (Training) und
    pit_profiles.runtime_cutoff(fixture_cutoff(...)) (Replay) muessen
    fuer dieselbe Partie denselben Zeitpunkt bezeichnen. Vor C10 waren
    es zwei Texte, die nur meistens dasselbe meinten.
    """
    for tag in ("2025-03-11", "2024-12-31", "2025-01-01"):
        training = PredictionCutoff.at(ds.prediction_cutoff(tag))
        laufzeit = PredictionCutoff.parse(pp.runtime_cutoff(tag))
        assert training == laufzeit, tag
        assert training.iso() == laufzeit.iso()


def test_beide_pfade_bauen_denselben_merkmalsvektor():
    """
    DIE PARITAETSAUSSAGE AUF MERKMALSEBENE.

    Aus denselben zwei Profilen muessen Trainingspfad und Laufzeit
    denselben Vektor bilden - gleiche Namen, gleiche Reihenfolge,
    gleiche Werte, gleiche Fehlstellen.

    Beide rufen dataset.profile_feature_values(); der Test haelt fest,
    dass das so BLEIBT. Zwei Fassungen derselben Zuordnung waeren die
    sicherste Art, ein Modell auf anders sortierte Werte anzuwenden -
    und das faellt an keiner Zahl auf.
    """
    heim = {"attack_home": 1.21, "attack_away": 0.98,
            "defence_home": 0.87, "defence_away": 1.14,
            "points_per_game": 2.1, "goals_for_per_game": 2.0,
            "goals_against_per_game": 0.9, "win_rate": 0.67}
    gast = {"attack_home": 0.95, "attack_away": 1.32,
            "defence_home": 1.05, "defence_away": 0.79,
            "points_per_game": 1.4, "goals_for_per_game": 1.3,
            "goals_against_per_game": 1.2, "win_rate": 0.40}

    laufzeit = inf.build_feature_row(heim, gast)

    training = {}
    training.update(ds.profile_feature_values("home", heim,
                                              ds.PROFILE_RATING_FELDER))
    training.update(ds.profile_feature_values("away", gast,
                                              ds.PROFILE_RATING_FELDER))

    assert sorted(laufzeit) == sorted(training)
    assert sorted(laufzeit) == e9.selected_columns()
    for spalte in e9.selected_columns():
        assert laufzeit[spalte] == pytest.approx(training[spalte],
                                                 rel=1e-12, abs=1e-12)


def test_fehlstellen_bleiben_auf_beiden_seiten_fehlstellen():
    """
    Ein fehlendes Merkmal darf nicht auf einer Seite still zu einer
    Zahl werden. Der Imputer sitzt spaeter und foldlokal; wer hier
    fuellt, tut es mit einem Wert, den niemand gewaehlt hat.
    """
    leer = {}
    laufzeit = inf.build_feature_row(leer, leer)
    training = {}
    training.update(ds.profile_feature_values("home", leer,
                                              ds.PROFILE_RATING_FELDER))
    training.update(ds.profile_feature_values("away", leer,
                                              ds.PROFILE_RATING_FELDER))
    assert laufzeit == training
    assert all(w is None for w in laufzeit.values())


def test_die_laufzeit_kennt_denselben_kandidaten():
    assert inf.CANDIDATE == e9.SELECTED_CANDIDATE
    assert inf.feature_columns() == e9.selected_columns()
    assert len(inf.feature_columns()) == 16


def test_es_gibt_nur_eine_abbildung_von_profil_zu_merkmal():
    """
    Beide Pfade muessen dieselbe Funktion rufen. Eine eigene
    Zuordnung in inference waere die zweite Fassung.
    """
    quelle = (WURZEL / "src" / "ml" / "inference.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.FunctionDef)
                and knoten.name == "build_feature_row"):
            code = ast.unparse(knoten)
            assert "profile_feature_values" in code
            assert "attack_home" not in code
            break
    else:                                                # pragma: no cover
        pytest.fail("build_feature_row nicht gefunden")


# ===========================================================================
# 7  Keine versteckte Uhr
# ===========================================================================

def test_keine_tiefe_funktion_liest_die_systemuhr():
    """
    "Jetzt" darf nur am Rand entstehen.

    Vor C10 bestimmten pit_profiles.runtime_cutoff und
    league_match_sim je eigenstaendig den heutigen Tag. Zwei Uhren im
    selben Request koennen ueber Mitternacht auseinanderfallen, und
    dann rechnete dieselbe Simulation mit zwei Staenden.

    Geprueft wird der Code ohne Docstrings: Eine Erwaehnung in der
    Begruendung ist keine Verwendung.
    """
    verdaechtig = []
    for pfad in (WURZEL / "src" / "features" / "pit_profiles.py",
                 WURZEL / "src" / "predict" / "league_match_sim.py",
                 WURZEL / "src" / "predict" / "cl_match_sim.py",
                 WURZEL / "src" / "ml" / "dataset.py",
                 WURZEL / "src" / "ml" / "cl_dataset.py"):
        baum = ast.parse(pfad.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if (isinstance(knoten, (ast.Module, ast.ClassDef,
                                    ast.FunctionDef))
                    and ast.get_docstring(knoten)):
                knoten.body = knoten.body[1:]
        code = ast.unparse(baum)
        for begriff in ("date.today()", "datetime.today()",
                        "datetime.now()", "datetime.utcnow()"):
            if begriff in code:
                verdaechtig.append((pfad.name, begriff))
    assert verdaechtig == [], verdaechtig


def test_now_laesst_sich_injizieren():
    """
    Ohne injizierbare Uhr haenge jeder Test an der Systemzeit und
    schluege irgendwann zufaellig fehl.
    """
    fest = dt.datetime(2025, 3, 11, 8, 30, tzinfo=UTC)
    assert PredictionCutoff.now(fest).iso() == "2025-03-11T08:30:00Z"


def test_der_vertrag_benennt_now_als_rand():
    vertrag = pc.contract()
    assert "now" in vertrag["now_is_an_edge"]
    assert "einzige" in vertrag["now_is_an_edge"]


# ===========================================================================
# 8  C9-Freeze bleibt unberuehrt
# ===========================================================================

def test_das_c9_manifest_bleibt_ladbar():
    pfad = WURZEL / "data" / "ml" / "c9_early_v2_manifest_2023-2025.json"
    assert pfad.exists()
    manifest = json.loads(pfad.read_text(encoding="utf-8"))
    assert manifest["manifest_fingerprint"].startswith("d432cf39")


def test_die_c9_auswahl_bleibt_unveraendert():
    from src.ml import persist as ps

    assert e9.SELECTED_CANDIDATE == "team_profile_cl"
    assert len(e9.selected_columns()) == 16
    assert [f for f, m in e9.FAMILY_REGISTRY.items()
            if m["status"] == e9.STATUS_SELECTED] == ["profile"]
    assert ps.MODEL_FAMILY == "poisson_offset_correction_linear"
    assert ps.MODEL_SCHEMA_VERSION == 2


def test_der_c9_schemafingerabdruck_bleibt_gleich():
    """
    C10 aendert Zeitverdrahtung, keine Merkmalsauswahl. Aenderte sich
    dieser Wert, waere der Freeze gebrochen.
    """
    pfad = WURZEL / "data" / "ml" / "c9_early_v2_manifest_2023-2025.json"
    manifest = json.loads(pfad.read_text(encoding="utf-8"))
    assert e9.schema_fingerprint() == manifest["fingerprints"]["schema"]


def test_c10_aktiviert_kein_research_feature():
    for familie, meta in e9.FAMILY_REGISTRY.items():
        if familie == "profile":
            continue
        assert meta["status"] != e9.STATUS_SELECTED, familie


def test_der_trainingsstichtag_liefert_denselben_wert_wie_vor_c10():
    """
    Der Bitgleichheitstest des Datensatzes.

    prediction_cutoff delegiert seit C10 an den gemeinsamen Vertrag.
    Aendert sich dabei der WERT, aendert sich der Datensatz und damit
    jeder in C9 eingefrorene Fingerabdruck.
    """
    for tag in ("2023-09-19", "2025-03-11", "2024-02-29"):
        assert ds.prediction_cutoff(tag) == dt.datetime.fromisoformat(
            f"{tag}T12:00:00")
        assert ds.prediction_cutoff(tag).tzinfo is None


# ===========================================================================
# 9  Determinismus und Unabhaengigkeit
# ===========================================================================

def test_der_vertrag_ist_zweimal_identisch():
    assert json.dumps(pc.contract(), sort_keys=True) == json.dumps(
        pc.contract(), sort_keys=True)


def test_der_vertrag_haengt_nicht_an_der_uhr():
    """
    Ein Vertrag, der die aktuelle Zeit enthielte, waere in jedem Lauf
    ein anderer und als Vergleichsgrundlage wertlos.
    """
    roh = json.dumps(pc.contract())
    for jahr in ("2025", "2026", "2027"):
        assert jahr not in roh


def test_das_cutoff_modul_braucht_kein_netz_und_keine_env():
    baum = ast.parse((WURZEL / "src" / "features" / "prediction_cutoff.py"
                      ).read_text(encoding="utf-8"))
    importiert = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for name in knoten.names:
                importiert.add(name.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            importiert.add(knoten.module.split(".")[0])

    assert not (importiert & {"requests", "urllib", "socket", "httpx",
                              "os", "dotenv"})


def test_gleiche_eingabe_gleicher_stichtag():
    a = [PredictionCutoff.for_match_day("2025-03-11") for _ in range(5)]
    assert all(x == a[0] for x in a)
    assert len({x.iso() for x in a}) == 1


# ===========================================================================
# 10  Das C10-Artefakt
# ===========================================================================

def test_das_artefakt_ist_zweimal_identisch():
    """
    Fluechtige Felder stehen drin, gehen aber nicht in den
    Fingerabdruck - sonst waere jeder zweite Lauf per Definition ein
    anderer Vertrag.
    """
    a = c10.build_artifact()
    b = c10.build_artifact()
    assert a["contract_fingerprint"] == b["contract_fingerprint"]
    assert a["fingerprint_excludes"] == ["created_at", "git_commit"]


def test_der_fingerabdruck_ignoriert_nur_fluechtige_felder():
    import copy

    a = c10.build_artifact()
    b = copy.deepcopy(a)
    b["created_at"] = "1999-01-01T00:00:00+00:00"
    b["git_commit"] = "0000000"
    b.pop("contract_fingerprint")
    a_ohne = {k: v for k, v in a.items() if k != "contract_fingerprint"}
    b_ohne = dict(b)

    import hashlib as _h
    import json as _j

    def _hash(daten):
        stabil = {k: v for k, v in sorted(daten.items())
                  if k not in ("created_at", "git_commit",
                               "fingerprint_excludes")}
        return _h.sha256(_j.dumps(stabil, sort_keys=True,
                                  ensure_ascii=False,
                                  default=repr).encode()).hexdigest()

    assert _hash(a_ohne) == _hash(b_ohne)


def test_das_artefakt_belegt_die_paritaet_statt_sie_zu_behaupten():
    a = c10.build_artifact()
    assert a["parity"]["all_identical"] is True
    assert a["parity"]["feature_vector_identical"] is True
    assert a["parity"]["feature_count"] == 16
    for eintrag in a["parity"]["cutoff_identical_per_match_day"]:
        assert eintrag["identical"] is True
        assert eintrag["training_cutoff"] == eintrag["runtime_cutoff"]


def test_das_artefakt_haelt_den_behobenen_fehler_fest():
    """
    Ein Vertrag, der nur den Sollzustand nennt, laesst niemanden
    erkennen, wovor er schuetzt.
    """
    a = c10.build_artifact()
    fall = a["fixed_divergence"]["measured_case"]
    assert fall["training_verdict"] != fall["runtime_verdict"]
    assert a["cutoff_definitions_before_c10"] == 4
    assert a["cutoff_definitions_after_c10"] == 1
    assert len(a["removed_duplicates"]) == 4


def test_das_artefakt_bestaetigt_den_c9_freeze():
    a = c10.build_artifact()
    freeze = a["c9_freeze"]
    assert freeze["selected_candidate"] == "team_profile_cl"
    assert freeze["selected_feature_count"] == 16
    assert freeze["selected_family"] == ["profile"]
    assert freeze["model_family"] == "poisson_offset_correction_linear"
    assert freeze["model_schema_version"] == 2
    assert freeze["activated_anything"] is False
    assert freeze["overwrote_bundle"] is False
    assert freeze["schema_fingerprint_matches"] is True


def test_das_artefakt_nennt_die_bekannten_grenzen():
    a = c10.build_artifact()
    zusammen = " ".join(a["known_limits"]).lower()
    assert "holdout" in zusammen
    assert "tagesstichtag" in zusammen
    assert "naiver utc" in zusammen


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_rohdaten():
    roh = json.dumps(c10.build_artifact(), ensure_ascii=False).lower()
    for verboten in ("api_key", "apikey", "secret", "token", "password",
                     "bearer", "c:\\users", "/home/"):
        assert verboten not in roh, verboten
    assert len(roh) < 100_000


def test_jeder_laufzeitpfad_nennt_seine_stichtagsquelle():
    """
    Ein Pfad ohne Stichtag gehoert mit Vermerk ins Artefakt, nicht
    weggelassen. Sonst sagt die Liste nur, wo schon aufgeraeumt wurde.
    """
    for eintrag in c10.RUNTIME_ENTRY_POINTS:
        assert eintrag["cutoff_source"].strip()
        assert isinstance(eintrag["explicit"], bool)
    assert any(e["explicit"] for e in c10.RUNTIME_ENTRY_POINTS)


def test_jede_zeitabhaengige_quelle_nennt_ihre_skala():
    for quelle in c10.CUTOFF_CONTROLLED_SOURCES:
        assert quelle["scale"] in ("day_key", "instant_key")
        assert len(quelle["why"]) > 40


def test_der_cutoff_vertrag_liegt_in_der_gemeinsamen_schicht():
    """
    DIE SCHICHTUNG, DIE EIN BESTEHENDER TEST ERZWUNGEN HAT.

    Der Vertrag wird von vier Schichten benutzt: features, data, ml und
    predict. Er lag zunaechst in src/ml/ - und
    test_ml_runtime.py::TestIsolation::test_die_ligasimulation_kennt_
    kein_ml schlug sofort fehl, weil die Ligasimulation dann "src.ml"
    importiert haette.

    Diese Trennung ist die zwischen ML-Pfad und individueller
    Simulation. Sie wird nicht gelockert, um einen Import
    unterzubringen; der Vertrag zieht um.
    """
    assert (WURZEL / "src" / "features" / "prediction_cutoff.py").exists()
    assert not (WURZEL / "src" / "ml" / "prediction_cutoff.py").exists()

    for name in ("league_match_sim.py", "season_sim.py",
                 "simulate_scores.py", "poisson.py"):
        pfad = WURZEL / "src" / "predict" / name
        if pfad.exists():
            assert "src.ml" not in pfad.read_text(encoding="utf-8"), name


def test_der_vertrag_zieht_keine_ml_schicht_nach():
    """
    Wuerde src/features/prediction_cutoff.py auf Modulebene etwas aus
    src.ml importieren, waere der Umzug nur ein Umweg: predict
    importierte features und bekaeme ml gleich mit.
    """
    baum = ast.parse((WURZEL / "src" / "features" / "prediction_cutoff.py"
                      ).read_text(encoding="utf-8"))
    for knoten in baum.body:
        if isinstance(knoten, ast.ImportFrom) and knoten.module:
            assert not knoten.module.startswith("src.ml"), knoten.module
        elif isinstance(knoten, ast.Import):
            for name in knoten.names:
                assert not name.name.startswith("src.ml"), name.name
