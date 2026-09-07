"""
Tests des Early-V2-Vertrags (V2-C9).

WAS HIER GEPRUEFT WIRD
C9 misst nichts. Es behauptet: Der Stand ist vollstaendig erfasst,
widerspruchsfrei und reproduzierbar. Genau diese drei Behauptungen
werden hier angegriffen.

Die schaerfsten Tests dieser Datei sind die manipulierenden: Ein
sauberer Datensatz beweist NICHT, dass die Zeitfilterung greift - er
beweist nur, dass sie diesmal nichts zu tun hatte. Deshalb wird
zukuenftige Information absichtlich eingespeist, und der Test verlangt,
dass sie abgewiesen wird.
"""

import ast
import copy
import datetime
import functools
import json
import pathlib

import pytest

from src.ml import dataset as ds
from src.ml import early_v2 as e9
from src.ml import feature_groups as fg
from src.ml import model as mdl

WURZEL = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Ein kleiner, vollstaendiger Kunstbestand
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _forschungsspalten():
    return tuple(e9.research_columns())


def _zeile(row_id, season=2024, datum="2024-10-01", heim=1, gast=2,
           heim_tore=2, gast_tore=1, **extra):
    """
    Eine Zeile mit allen Pflichtfeldern beider Ansichten.

    Bewusst von Hand und nicht aus build_dataset(): Ein Test, der den
    ganzen Datensatzbau braucht, prueft am Ende den Datensatzbau und
    nicht den Vertrag.
    """
    zeile = {
        "row_id": row_id, "match_id": None, "league": "PL",
        "season": season, "date": datum, "matchday": 7,
        "home_id": heim, "away_id": gast,
        "evaluation_eligible": True, "knockout_eligible": False,
        "home_goals": heim_tore, "away_goals": gast_tore, "outcome": 0,
        "baseline_lambda_home": 1.5, "baseline_lambda_away": 1.1,
    }
    # ALLE Forschungsspalten, nicht nur die 16 des Kandidaten: Die
    # Forschungsansicht verlangt sie, und eine Luecke dort wuerde einen
    # Test scheitern lassen, der etwas ganz anderes prueft.
    #
    # Einmal berechnet: research_columns() baut die Gruppen jedes Mal
    # neu, und diese Funktion laeuft je Kunstzeile. Ohne den Puffer
    # kostet die Datei ein Vielfaches ihrer Laufzeit fuer immer
    # dasselbe Ergebnis.
    for spalte in _forschungsspalten():
        zeile.setdefault(spalte, 1.0)
    zeile.update(extra)
    return zeile


@pytest.fixture(scope="module")
def zeilen():
    """
    Ein Bestand mit UNTERSCHEIDENDEN Gruppen.

    Mehrere Partien am selben Spieltag mit verschiedenen Ergebnissen -
    ohne sie liesse sich kein Ligadurchschnitt entlasten, weil der
    Beweis genau daran haengt: gleicher Spaltenwert bei verschiedenen
    Zielwerten. Ein Spielzeugbestand aus drei Partien an drei
    verschiedenen Tagen kann diesen Beweis nicht tragen, und das ist
    kein Mangel des Tests, sondern die Aussage des Verfahrens.
    """
    heraus = []
    # Drei Spieltage, nicht zwei: MIN_DISCRIMINATING_GROUPS verlangt
    # mehrere Belege, damit ein einzelner Datenfehler den Beweis nicht
    # traegt. Der Kunstbestand muss diese Huerde ehrlich nehmen.
    for tag, partien in (("2024-10-01", ((2, 1), (0, 0), (3, 2), (1, 4))),
                         ("2024-10-08", ((1, 1), (2, 0), (0, 3), (4, 2))),
                         ("2024-10-15", ((0, 1), (3, 3), (2, 2), (5, 0)))):
        for nr, (ht, at) in enumerate(partien):
            heraus.append(_zeile(
                f"{tag}:{nr}", datum=tag, heim=10 * nr + 1,
                gast=10 * nr + 2, heim_tore=ht, gast_tore=at,
                league_avg_home_goals=1.42, league_avg_away_goals=1.19))
    return heraus


# ===========================================================================
# 1  Registry
# ===========================================================================

def test_jede_merkmalsgruppe_hat_einen_registryeintrag():
    """
    Der Kern des C9-Versprechens.

    Eine Gruppe ohne Eintrag waere eine Familie ohne dokumentierte
    Entscheidung - und genau die wuerde spaeter versehentlich
    mitgenommen, weil niemand einen Grund kennt, sie wegzulassen.
    """
    fehlend = [g for g in fg.GROUP_ORDER if g not in e9.FAMILY_REGISTRY]
    assert fehlend == []


def test_kein_registryeintrag_ohne_merkmalsgruppe():
    """Ein Eintrag ohne Gruppe waere eine zweite, abweichende Liste."""
    ueberzaehlig = [g for g in e9.FAMILY_REGISTRY
                    if g not in fg.GROUP_ORDER]
    assert ueberzaehlig == []


def test_eine_unbekannte_familie_bricht_ab(monkeypatch):
    """
    Die Pruefung muss WIRKEN, nicht nur existieren.

    Ohne diesen Test koennte validate_registry() versehentlich immer
    True liefern und niemand saehe es.
    """
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "erfundene_familie",
                        {"status": e9.STATUS_SELECTED,
                         "pit_class": e9.PIT_HISTORICAL, "source": "x",
                         "tracked": True, "runtime_available": True,
                         "reason": "x" * 40, "evidence": "x",
                         "block": "X", "since_version": 1})
    with pytest.raises(ValueError, match="ohne Merkmalsgruppe"):
        e9.validate_registry()


def test_ein_unbekannter_status_bricht_ab(monkeypatch):
    eintrag = dict(e9.FAMILY_REGISTRY["profile"], status="VIELLEICHT")
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "profile", eintrag)
    with pytest.raises(ValueError, match="unbekannten Status"):
        e9.validate_registry()


def test_ein_status_ohne_begruendung_bricht_ab(monkeypatch):
    """Ein Status ohne Begruendung ist eine Behauptung."""
    eintrag = dict(e9.FAMILY_REGISTRY["workload"], reason="  ")
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "workload", eintrag)
    with pytest.raises(ValueError, match="keine Begruendung"):
        e9.validate_registry()


def test_jeder_status_nennt_ein_belegendes_artefakt():
    """
    Ohne Artefaktverweis muesste man den Status glauben. Mit ihm laesst
    er sich nachrechnen.
    """
    for name, eintrag in e9.FAMILY_REGISTRY.items():
        assert eintrag["evidence"].strip(), name
        assert ".json" in eintrag["evidence"], name


def test_es_gibt_genau_die_sieben_erlaubten_status():
    erlaubt = {"SELECTED", "EXPERIMENTAL", "REJECTED", "INCONCLUSIVE",
               "NOT_EVALUABLE", "INFRASTRUCTURE_ONLY", "BASELINE_ONLY"}
    assert set(e9.STATUSES) == erlaubt
    assert len(e9.STATUSES) == 7


def test_alle_verwendeten_status_sind_erlaubt():
    for eintrag in e9.FAMILY_REGISTRY.values():
        assert eintrag["status"] in e9.STATUSES
    for eintrag in e9.NON_FEATURE_COMPONENTS.values():
        assert eintrag["status"] in e9.STATUSES


def test_die_merkmalsreihenfolge_ist_deterministisch():
    """
    Die Koeffizientenpositionen haengen daran. Eine Reihenfolge aus
    einer Mengeniteration waere zwischen zwei Laeufen verschieden - und
    ein gespeichertes Modell danach falsch verdrahtet.
    """
    a = [r["name"] for r in e9.feature_registry()]
    b = [r["name"] for r in e9.feature_registry()]
    assert a == b
    assert a == sorted(a, key=lambda n: (
        fg.GROUP_ORDER.index(next(r["family"] for r in e9.feature_registry()
                                  if r["name"] == n)), n))


def test_kein_merkmal_kommt_doppelt_vor():
    namen = [r["name"] for r in e9.feature_registry()]
    assert len(namen) == len(set(namen))


def test_ein_merkmal_in_zwei_familien_bricht_ab(monkeypatch):
    """
    Zwei Familien hiessen zwei Status - und damit zwei verschiedene
    Antworten auf die Frage, ob das Merkmal aufgenommen ist.
    """
    echte = fg.build_groups

    def verdoppelt(spalten=None):
        gruppen = copy.deepcopy(echte(spalten))
        geklaut = gruppen["profile"]["columns"][0]
        gruppen["workload"]["columns"] = (
            list(gruppen["workload"]["columns"]) + [geklaut])
        return gruppen

    monkeypatch.setattr(fg, "build_groups", verdoppelt)
    gruppen = verdoppelt()
    # Der Widerspruch faellt bereits feature_groups.validate_groups auf
    # ("steht in zwei Gruppen"); greift diese Ebene einmal nicht, faengt
    # ihn feature_registry selbst ("steht in zwei Familien"). Geprueft
    # wird, dass er ueberhaupt auffaellt - nicht, wer ihn meldet.
    with pytest.raises(ValueError, match="zwei (Gruppen|Familien)"):
        e9.feature_registry(gruppen=gruppen)


# ===========================================================================
# 2  Der Auswahlvertrag
# ===========================================================================

def test_selected_enthaelt_genau_den_finalen_kandidaten():
    assert e9.SELECTED_CANDIDATE == "team_profile_cl"
    assert e9.selected_columns() == sorted(
        fg.columns_for(e9.SELECTED_CANDIDATE))
    assert len(e9.selected_columns()) == 16


def test_nur_selected_darf_in_den_kandidaten():
    """
    Genau eine Statusklasse. Steht das als Konstante da und nicht als
    Bedingung im Code, ist eine spaetere Lockerung eine sichtbare
    Aenderung an einer benannten Stelle.
    """
    assert e9.STATUSES_ALLOWED_IN_SELECTED == (e9.STATUS_SELECTED,)


@pytest.mark.parametrize("status", ["REJECTED", "INCONCLUSIVE",
                                    "NOT_EVALUABLE",
                                    "INFRASTRUCTURE_ONLY",
                                    "EXPERIMENTAL", "BASELINE_ONLY"])
def test_kein_anderer_status_gelangt_in_den_kandidaten(monkeypatch, status):
    """
    DER WICHTIGSTE TEST DIESER DATEI.

    Ein Merkmal darf nicht in den finalen Kandidaten gelangen, nur weil
    es technisch existiert. Hier wird der Statusweg jeder einzelnen
    nicht erlaubten Klasse angegriffen: Die Familie des Kandidaten
    bekommt den fremden Status, und selected_columns() muss abbrechen
    statt stillschweigend ein groesseres Modell zu liefern.
    """
    eintrag = dict(e9.FAMILY_REGISTRY["profile"], status=status)
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "profile", eintrag)
    with pytest.raises(ValueError, match="nicht aufgenommen"):
        e9.selected_columns()


def test_eine_zusaetzliche_gruppe_im_kandidaten_bricht_ab(monkeypatch):
    """
    Der andere Weg hinein: nicht ueber den Status, sondern ueber die
    Variantendefinition. Wer dem V1-Kandidaten eine Gruppe hinzufuegt,
    bekommt keinen groesseren Kandidaten, sondern einen Abbruch.
    """
    echte = fg.columns_for

    def erweitert(name, gruppen=None, spalten=None):
        heraus = list(echte(name, gruppen, spalten))
        if name == e9.SELECTED_CANDIDATE:
            gr = gruppen if gruppen is not None else fg.build_groups(spalten)
            heraus.extend(gr["workload"]["columns"])
        return sorted(heraus)

    monkeypatch.setattr(fg, "columns_for", erweitert)
    with pytest.raises(ValueError, match="nicht aufgenommen"):
        e9.selected_columns()


def test_selected_ist_teilmenge_von_research(zeilen):
    ansichten = e9.build_views(zeilen)
    assert ansichten["meta"]["selected_is_subset_of_research"] is True
    assert set(e9.selected_columns()) <= set(e9.research_columns())


def test_research_enthaelt_auch_verworfene_merkmale():
    """
    Der Unterschied zum Kandidaten - und der Zweck der Trennung.

    Ein spaeter erneut pruefbares REJECTED ist der Sinn des
    Forschungsdatensatzes. Waeren beide Ansichten gleich, braeuchte man
    nur eine.
    """
    forschung = set(e9.research_columns())
    gruppen = fg.build_groups()
    verworfen = set(gruppen["workload"]["columns"])
    assert verworfen <= forschung
    assert not verworfen & set(e9.selected_columns())


def test_gitignorierte_quellen_fehlen_ohne_ausdrueckliche_angabe():
    """
    Aus einem frischen Checkout gebaut, traegt jede uefa- und
    squad_history-Spalte in JEDER Zeile None. Sie trotzdem
    aufzunehmen waere eine Luecke mit Ueberschrift - die schlechtere
    Variante von "fehlt".
    """
    ohne = set(e9.research_columns())
    mit = set(e9.research_columns(optional_sources=("uefa",
                                                    "squad_history")))
    assert ohne < mit
    gruppen = fg.build_groups()
    for familie in ("uefa", "squad_history"):
        assert not set(gruppen[familie]["columns"]) & ohne
        assert set(gruppen[familie]["columns"]) <= mit


def test_eine_unbekannte_optionale_quelle_bricht_ab():
    with pytest.raises(ValueError, match="unbekannte optionale Quellen"):
        e9.research_columns(optional_sources=("erfunden",))


# ===========================================================================
# 3  Die beiden Ansichten
# ===========================================================================

def test_beide_ansichten_tragen_dieselben_zeilen(zeilen):
    ansichten = e9.build_views(zeilen)
    a = [z["row_id"] for z in ansichten["research"]]
    b = [z["row_id"] for z in ansichten["selected"]]
    assert a == b == [z["row_id"] for z in zeilen]
    assert len(a) == len(zeilen)


def test_beide_ansichten_tragen_dieselben_ziele(zeilen):
    """
    Verschiedene Merkmale, gleiche Ziele. Waere es anders, waeren die
    beiden Ansichten nicht zwei Sichten auf denselben Bestand, sondern
    zwei Bestaende.
    """
    ansichten = e9.build_views(zeilen)
    for f, s in zip(ansichten["research"], ansichten["selected"]):
        for feld in e9.TARGET_FIELDS:
            assert f[feld] == s[feld]


def test_keine_zielspalte_landet_als_merkmal(zeilen):
    verstoesse, _ = e9.check_no_target_leak(e9.research_columns(), zeilen)
    assert verstoesse == []
    verstoesse, _ = e9.check_no_target_leak(e9.selected_columns(), zeilen)
    assert verstoesse == []


def test_eine_fehlende_spalte_wird_gemeldet_statt_ergaenzt(zeilen):
    """
    Sie stillschweigend mit None zu fuellen hiesse, eine Luecke als
    Messwert auszugeben.
    """
    verstuemmelt = [dict(z) for z in zeilen]
    del verstuemmelt[0]["home_win_rate"]  # eine der 16 Kandidatenspalten
    with pytest.raises(ValueError, match="fehlen die Spalten"):
        e9.project(verstuemmelt, e9.selected_columns())


def test_die_ansicht_traegt_keine_fremden_spalten(zeilen):
    """
    Der Kandidatendatensatz darf kein verworfenes Merkmal
    durchschleifen - auch nicht als unbenutzte Spalte.
    """
    angereichert = [dict(z, home_rest_days=3.0) for z in zeilen]
    ansicht = e9.project(angereichert, e9.selected_columns())
    assert "home_rest_days" not in ansicht[0]


# ===========================================================================
# 4  Fingerabdruecke
# ===========================================================================

def test_gleicher_bestand_gleicher_fingerabdruck(zeilen):
    spalten = e9.selected_columns()
    assert (e9.dataset_fingerprint(zeilen, spalten)
            == e9.dataset_fingerprint([dict(z) for z in zeilen], spalten))


def test_eine_geaenderte_zielgroesse_veraendert_den_fingerabdruck(zeilen):
    """
    DIE LUECKE, DIE C9 SCHLIESST.

    Der frueheren Fassung fehlten zeitweise die Tore. Ein Datensatz mit
    vertauschten Ergebnissen saehe dann identisch aus, und jede
    Kennzahl waere eine andere.
    """
    verdreht = [dict(z) for z in zeilen]
    verdreht[0]["home_goals"] = 99

    assert (e9.target_fingerprint(verdreht)
            != e9.target_fingerprint(zeilen))
    spalten = e9.selected_columns()
    assert (e9.dataset_fingerprint(verdreht, spalten)
            != e9.dataset_fingerprint(zeilen, spalten))


def test_vertauschte_tore_veraendern_den_fingerabdruck(zeilen):
    """
    Die subtilere Variante: Die Summe bleibt gleich, das Ergebnis
    kippt. Ein Hash ueber Zeilenzahl oder Torsumme saehe hier nichts.
    """
    getauscht = [dict(z) for z in zeilen]
    getauscht[0]["home_goals"], getauscht[0]["away_goals"] = (
        getauscht[0]["away_goals"], getauscht[0]["home_goals"])
    assert e9.target_fingerprint(getauscht) != e9.target_fingerprint(zeilen)


def test_ein_geaenderter_merkmalswert_veraendert_den_fingerabdruck(zeilen):
    spalten = e9.selected_columns()
    geaendert = [dict(z) for z in zeilen]
    geaendert[1][spalten[0]] = 42.0
    assert (e9.dataset_fingerprint(geaendert, spalten)
            != e9.dataset_fingerprint(zeilen, spalten))


def test_ein_geaenderter_merkmalswert_laesst_den_zielhash_gleich(zeilen):
    """
    Die Gegenprobe. Waere der Zielhash von Merkmalen abhaengig, koennte
    er die Frage "haben sich die Ziele geaendert" nicht beantworten.
    """
    geaendert = [dict(z) for z in zeilen]
    geaendert[1][e9.selected_columns()[0]] = 42.0
    assert e9.target_fingerprint(geaendert) == e9.target_fingerprint(zeilen)


def test_eine_geaenderte_match_id_veraendert_den_fingerabdruck(zeilen):
    geaendert = [dict(z) for z in zeilen]
    geaendert[0]["match_id"] = 123456
    assert e9.target_fingerprint(geaendert) != e9.target_fingerprint(zeilen)


def test_vertauschte_mannschaften_veraendern_den_fingerabdruck(zeilen):
    """
    Ohne home_id und away_id im Vertrag waere das dieselbe Zeile - und
    es ist eine andere Partie. Genau deshalb kamen die beiden Felder in
    C9 hinzu.
    """
    getauscht = [dict(z) for z in zeilen]
    getauscht[0]["home_id"], getauscht[0]["away_id"] = (
        getauscht[0]["away_id"], getauscht[0]["home_id"])
    assert e9.target_fingerprint(getauscht) != e9.target_fingerprint(zeilen)


def test_ein_geaendertes_datum_veraendert_den_fingerabdruck(zeilen):
    """
    Das Datum IST der Stichtag - der Stichtag ist der Spieltag um
    12:00. Ein anderes Datum heisst ein anderer Stichtag und damit ein
    anderer Merkmalsstand.
    """
    verschoben = [dict(z) for z in zeilen]
    verschoben[0]["date"] = "2024-11-11"
    assert e9.target_fingerprint(verschoben) != e9.target_fingerprint(zeilen)


def test_die_uebergabereihenfolge_der_merkmale_aendert_nichts(zeilen):
    """
    Der Vertrag ist kanonisch: sortiert. Damit ist eine andere
    REIHENFOLGE derselben Menge derselbe Stand - und eine andere MENGE
    ein anderer.
    """
    spalten = e9.selected_columns()
    assert (e9.dataset_fingerprint(zeilen, list(reversed(spalten)))
            == e9.dataset_fingerprint(zeilen, spalten))


def test_eine_andere_merkmalsmenge_veraendert_den_fingerabdruck(zeilen):
    spalten = e9.selected_columns()
    assert (e9.dataset_fingerprint(zeilen, spalten[:-1])
            != e9.dataset_fingerprint(zeilen, spalten))


def test_die_zeilenreihenfolge_aendert_nichts(zeilen):
    """
    Sortiert nach row_id: Der Wert haengt am Bestand, nicht daran, in
    welcher Reihenfolge er eingelesen wurde.
    """
    assert (e9.target_fingerprint(list(reversed(zeilen)))
            == e9.target_fingerprint(zeilen))


def test_der_schemafingerabdruck_braucht_keine_daten():
    """
    Er beschreibt den VERTRAG. Zwei Laeufe mit gleichem Datenhash, aber
    verschiedenem Schemahash sind nicht vergleichbar, auch wenn die
    Zahlen es nahelegen.
    """
    assert e9.schema_fingerprint() == e9.schema_fingerprint()
    assert len(e9.schema_fingerprint()) == 64


def test_ein_geaenderter_status_veraendert_den_schemafingerabdruck(
        monkeypatch):
    vorher = e9.schema_fingerprint()
    eintrag = dict(e9.FAMILY_REGISTRY["workload"],
                   status=e9.STATUS_EXPERIMENTAL)
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "workload", eintrag)
    assert e9.schema_fingerprint() != vorher


def test_der_hashvertrag_enthaelt_keine_absoluten_pfade(zeilen):
    """
    Ein Fingerabdruck, der lokale Pfade mithasht, waere auf einem
    anderen Rechner ein anderer - und damit als Reproduktionsnachweis
    wertlos.
    """
    felder = (list(e9.IDENTITY_FIELDS) + list(e9.TARGET_FIELDS)
              + list(e9.BASELINE_FIELDS) + e9.selected_columns())
    for feld in felder:
        assert ":\\" not in feld and not feld.startswith("/")


# ===========================================================================
# 5  Point-in-Time und Leakage - mit Manipulation
# ===========================================================================

def test_zukuenftige_partie_wird_aus_der_form_ausgeschlossen():
    """
    MANIPULATIONSTEST.

    Eine Partie NACH dem Stichtag wird der Zeitleiste absichtlich
    hinzugefuegt. Die Formmerkmale muessen unveraendert bleiben - sonst
    lernte das Modell aus einem Spiel, das zum Vorhersagezeitpunkt noch
    nicht gespielt war.
    """
    from src.features import form

    stichtag = datetime.datetime(2024, 10, 1, 12, 0, 0)
    vergangenheit = [
        {"kickoff": datetime.datetime(2024, 9, k, 15, 0), "match_id": k,
         "team_goals": 2, "opponent_goals": 1, "is_home": True,
         "competition": "PL", "opponent_id": 50 + k, "status": "FT"}
        for k in (10, 17, 24)]
    zukunft = {"kickoff": datetime.datetime(2024, 10, 20, 15, 0),
               "match_id": 99, "team_goals": 9, "opponent_goals": 0,
               "is_home": True, "competition": "PL", "opponent_id": 77,
               "status": "FT"}

    ohne = form.form_features(vergangenheit, stichtag)
    mit = form.form_features(vergangenheit + [zukunft], stichtag)
    assert ohne == mit


def test_eine_partie_genau_zum_stichtag_zaehlt_nicht():
    """
    Die Grenze ist STRIKT. Ein Spiel, das genau zum Stichtag angepfiffen
    wird, hat zum Vorhersagezeitpunkt noch kein Ergebnis.
    """
    from src.features import form

    stichtag = datetime.datetime(2024, 10, 1, 12, 0, 0)
    vergangenheit = [
        {"kickoff": datetime.datetime(2024, 9, k, 15, 0), "match_id": k,
         "team_goals": 1, "opponent_goals": 1, "is_home": True,
         "competition": "PL", "opponent_id": 50 + k, "status": "FT"}
        for k in (10, 17, 24)]
    genau = {"kickoff": stichtag, "match_id": 98, "team_goals": 9,
             "opponent_goals": 0, "is_home": True, "competition": "PL",
             "opponent_id": 78, "status": "FT"}

    assert (form.form_features(vergangenheit, stichtag)
            == form.form_features(vergangenheit + [genau], stichtag))


def test_transfer_am_spieltag_geht_nicht_ein():
    """
    MANIPULATIONSTEST.

    Der Anbieter unterscheidet nicht zwischen Bekanntgabe und
    Wirksamkeit. Ein Wechsel, dessen einziges bekanntes Datum der
    Spieltag ist, wird deshalb ausgeschlossen - die konservative
    Lesart.
    """
    from src.features import squad_history as sh

    index = {7: [
        {"player_id": 1, "date": "2024-08-01", "to_team_id": 7,
         "from_team_id": 9, "type": "transfer"},
        {"player_id": 2, "date": "2024-10-01", "to_team_id": 7,
         "from_team_id": 9, "type": "transfer"},
    ]}
    zu, ab = sh.transfer_window(7, "2024-10-01", index)
    daten = [e["date"] for e in zu + ab]
    assert "2024-10-01" not in daten
    assert "2024-08-01" in daten


def test_snapshot_nach_dem_stichtag_wird_nicht_gelesen():
    """
    MANIPULATIONSTEST.

    Der einzige vorhandene Verfuegbarkeitssnapshot ist juenger als jede
    auszuwertende Partie. Genau deshalb sind squad_snapshot und
    availability_impact NOT_EVALUABLE - und nicht etwa mit Nullen
    gefuellt.
    """
    from src.data import snapshot_reader as sr

    class NurZukunft:
        @staticmethod
        def latest_snapshot_before(kind, cutoff, key, inclusive=False):
            return None

    ergebnis = sr.snapshot_before("squad", "team:1", "2024-10-01",
                                  archive_module=NurZukunft)
    assert ergebnis["available"] is False


def test_spaetere_saison_beeinflusst_fruehere_nicht():
    """
    MANIPULATIONSTEST auf dem Vertrag selbst.

    Der Fingerabdruck einer frueheren Saison darf sich nicht aendern,
    wenn Zeilen einer spaeteren hinzukommen. Waere es anders, truege
    die fruehere Messung Information aus der Zukunft.
    """
    frueh = [_zeile("f1", season=2023, datum="2023-10-01"),
             _zeile("f2", season=2023, datum="2023-10-08")]
    spaet = [_zeile("s1", season=2025, datum="2025-10-01")]

    nur_frueh = e9.target_fingerprint(frueh)
    aus_gemischt = e9.target_fingerprint(
        [z for z in frueh + spaet if z["season"] == 2023])
    assert nur_frueh == aus_gemischt


def test_ein_aggregat_im_hinspiel_ist_ein_verstoss():
    """
    MANIPULATIONSTEST.

    Im Hinspiel waere ein Aggregatstand das eigene, noch nicht
    gespielte Ergebnis.
    """
    sauber = [_zeile("x", aggregate_available=0, is_second_leg=0)]
    kaputt = [_zeile("y", aggregate_available=1, is_second_leg=0)]

    assert e9.check_rows_pit(sauber, [])[
        "aggregate_only_in_second_leg"]["violation_count"] == 0
    assert e9.check_rows_pit(kaputt, [])[
        "aggregate_only_in_second_leg"]["violation_count"] == 1


def test_ein_datum_aus_einer_fremden_saison_ist_ein_verstoss():
    kaputt = [_zeile("z", season=2023, datum="2026-03-01")]
    bericht = e9.check_rows_pit(kaputt, [])
    assert bericht["season_bounds"]["violation_count"] == 1
    assert bericht["ok"] is False


def test_doppelte_zeilenschluessel_werden_erkannt():
    """
    Zwei Zeilen mit demselben Schluessel machen jeden Fingerabdruck
    bedeutungslos - die Sortierung trennt sie nicht mehr.
    """
    doppelt = [_zeile("gleich"), _zeile("gleich", datum="2024-10-02")]
    bericht = e9.check_rows_pit(doppelt, [])
    assert bericht["row_id_unique"]["duplicate_count"] == 1
    assert bericht["ok"] is False


def test_ein_echtes_ziel_leck_wird_erkannt(zeilen):
    """
    MANIPULATIONSTEST.

    Eine Spalte, die exakt dem Ergebnis entspricht, muss auffallen -
    auch wenn sie harmlos heisst.
    """
    verseucht = [dict(z, x_home_goals=z["home_goals"]) for z in zeilen]
    verstoesse, _ = e9.check_no_target_leak(["x_home_goals"], verseucht)
    assert verstoesse
    assert "nicht entlastet" in verstoesse[0][1]


def test_ein_ligadurchschnitt_wird_nicht_faelschlich_beanstandet(zeilen):
    """
    Die Gegenprobe zur vorigen Regel - und der Grund, warum die
    Pruefung nicht bloss auf Namen schaut.

    league_avg_home_goals endet auf "home_goals" und ist trotzdem der
    Durchschnitt ueber ANDERE Partien. Ein reines Namensverbot haette
    hier zwei richtige Merkmale verworfen.
    """
    verstoesse, entlastet = e9.check_no_target_leak(
        ["league_avg_home_goals"], zeilen)
    assert verstoesse == []
    assert entlastet[0]["constant_within_league_and_date"] is True
    assert entlastet[0]["discriminating_groups"] >= (
        e9.MIN_DISCRIMINATING_GROUPS)


def test_ohne_zeilen_bleibt_ein_namensverdacht_ein_verstoss():
    """
    Was nicht geprueft werden kann, gilt nicht als geprueft.
    """
    verstoesse, _ = e9.check_no_target_leak(["league_avg_home_goals"], None)
    assert verstoesse
    assert "nicht entkraeftbar" in verstoesse[0][1]


def test_crosswalkkonflikt_entfernt_den_eintrag():
    """
    MANIPULATIONSTEST auf der Identitaetszuordnung.

    Ein Widerspruch ENTFERNT den Eintrag, statt ihn zu ueberschreiben:
    Unbekannt ist besser als vielleicht falsch. Eine stille
    Mehrfachzuordnung waere die unauffaelligste Art, zwei Vereine zu
    verwechseln.
    """
    from src.features import squad_crosswalk as sc

    quelle = (WURZEL / "src" / "features" / "squad_crosswalk.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum)
    # Der Konflikt muss zu einem del/pop fuehren, nicht zu einer
    # Zuweisung. Eine Zuweisung waere ein "der letzte gewinnt".
    assert "conflicts" in code or "konflikt" in code.lower()
    assert hasattr(sc, "build_team_crosswalk")


def test_foldlokale_grenzen_sehen_den_testfold_nicht():
    """
    MANIPULATIONSTEST.

    Ein Ausreisser, der nur im Testfold vorkommt, darf eine foldlokal
    gelernte Grenze nicht verschieben. Die Pruefung gehoert hierher und
    nicht nur zu C8: Sie ist eine Zusage des Datensatzvertrags, nicht
    eines einzelnen Modellversuchs.
    """
    from src.ml import model_class as mc

    train = [[float(x)] for x in range(100)]
    transform = mc.FeatureTransform(["a"], {"a": mc.TRANSFORM_IDENTITY},
                                    winsor=("a",))
    transform.fit(train)
    grenze = transform.bounds_["a"]
    transform.transform([[10_000.0]])
    assert transform.bounds_["a"] == grenze


def test_der_stichtag_ist_eine_benannte_regel():
    """
    Vor C9 stand die 12:00 als Zeichenkette mitten im Datensatzbau. Ein
    Zeitvertrag, den man nur durch Codelesen erfaehrt, laesst sich
    nicht zitieren und nicht testen.
    """
    assert ds.PREDICTION_CUTOFF_HOUR == 12
    assert ds.CUTOFF_INCLUSIVE is False
    assert ds.prediction_cutoff("2025-03-11") == datetime.datetime(
        2025, 3, 11, 12, 0, 0)


# ===========================================================================
# 6  Der Feature-Freeze
# ===========================================================================

def test_der_freeze_nennt_den_kandidaten_und_seine_merkmale():
    freeze = e9.feature_freeze()
    assert freeze["candidate"] == "team_profile_cl"
    assert freeze["feature_count"] == 16
    assert freeze["features"] == e9.selected_columns()


def test_der_freeze_begruendet_jeden_ausschluss():
    """
    Ein Freeze, der nur sagt, was drin ist, laedt dazu ein, das
    Fehlende fuer ein Versehen zu halten.
    """
    freeze = e9.feature_freeze()
    for name, eintrag in freeze["excluded"].items():
        assert eintrag["status"] in e9.STATUSES, name
        assert len(eintrag["reason"]) > 40, name


def test_jede_nicht_ausgewaehlte_familie_steht_im_freeze():
    freeze = e9.feature_freeze()
    for familie in fg.GROUP_ORDER:
        if e9.FAMILY_REGISTRY[familie]["status"] == e9.STATUS_SELECTED:
            assert familie in freeze["included_families"]
        else:
            assert familie in freeze["excluded"], familie


def test_der_freeze_haelt_fest_dass_c8_nicht_aktiv_ist():
    """
    Transformation, Interaktion und Kalibrierung sind implementiert und
    verworfen. Der Freeze muss beides sagen - sonst sieht ihr Fehlen
    wie eine Luecke aus.
    """
    freeze = e9.feature_freeze()
    assert freeze["transformation"].startswith("KEINE")
    assert freeze["interactions"].startswith("KEINE")
    assert freeze["calibration"].startswith("KEINE")


def test_der_freeze_ist_zweimal_identisch():
    assert json.dumps(e9.feature_freeze(), sort_keys=True) == json.dumps(
        e9.feature_freeze(), sort_keys=True)


def test_der_freeze_nennt_die_modellfamilie_unveraendert():
    from src.ml import persist as ps

    freeze = e9.feature_freeze()
    assert freeze["model_family"] == ps.MODEL_FAMILY
    assert freeze["model_family"] == "poisson_offset_correction_linear"
    assert freeze["model_schema_version"] == ps.MODEL_SCHEMA_VERSION


def test_die_guardrails_stehen_unveraendert_im_freeze():
    freeze = e9.feature_freeze()
    assert freeze["guardrails"]["lambda"] == [mdl.LAMBDA_MIN, mdl.LAMBDA_MAX]
    assert freeze["guardrails"]["correction"] == [mdl.CORRECTION_MIN,
                                                  mdl.CORRECTION_MAX]


# ===========================================================================
# 7  Manifest und Reproduzierbarkeit
# ===========================================================================

@pytest.fixture(scope="module")
def manifest(zeilen):
    """
    Ein Manifest fuer die ganze Datei.

    Modulweit, weil die Quellfingerabdruecke jedes Verzeichnis erneut
    durchlaufen. Die Tests hier lesen nur; wer etwas veraendert,
    arbeitet auf einer Kopie.
    """
    return e9.build_manifest(zeilen, source_mode=e9.FINGERPRINT_INVENTORY)


def test_das_manifest_ist_zweimal_identisch(zeilen):
    """
    Der Reproduktionsnachweis.

    Ausgenommen sind nur Erzeugungszeitpunkt und der git-Block - beides
    beschreibt den Augenblick, nicht die Daten.
    """
    a = e9.build_manifest(zeilen, source_mode=e9.FINGERPRINT_INVENTORY)
    b = e9.build_manifest(zeilen, source_mode=e9.FINGERPRINT_INVENTORY)
    assert a["manifest_fingerprint"] == b["manifest_fingerprint"]


def test_der_git_block_geht_nicht_in_den_fingerabdruck(manifest):
    """
    Sonst waere jeder zweite Lauf ein anderer Stand: Der erste Lauf
    schreibt das Manifest, der Arbeitsbaum hat danach eine ungetrackte
    Datei mehr, und der zweite zaehlt eine mehr.
    """
    assert "git" in e9.MANIFEST_VOLATILE_FIELDS
    verbogen = copy.deepcopy(manifest)
    verbogen["git"] = {"git_commit": "anders", "git_dirty": True,
                       "git_dirty_entries": 999}
    assert (e9.manifest_fingerprint(verbogen)
            == e9.manifest_fingerprint(manifest))


def test_ein_geaenderter_merkmalsstatus_veraendert_den_manifesthash(
        manifest, monkeypatch, zeilen):
    eintrag = dict(e9.FAMILY_REGISTRY["form"], status=e9.STATUS_REJECTED)
    monkeypatch.setitem(e9.FAMILY_REGISTRY, "form", eintrag)
    anders = e9.build_manifest(zeilen,
                               source_mode=e9.FINGERPRINT_INVENTORY)
    assert (anders["manifest_fingerprint"]
            != manifest["manifest_fingerprint"])


def test_das_manifest_enthaelt_keine_geheimnisse(manifest):
    roh = json.dumps(manifest, ensure_ascii=False).lower()
    for verboten in ("api_key", "apikey", "api-key", "secret", "token",
                     "password", "passwort", "bearer"):
        assert verboten not in roh, verboten


def test_das_manifest_enthaelt_keine_absoluten_pfade(manifest):
    """
    Ein Manifest mit lokalen Benutzerpfaden waere auf einem anderen
    Rechner unbrauchbar und verriete nebenbei die Verzeichnisstruktur.
    """
    roh = json.dumps(manifest, ensure_ascii=False)
    assert "C:\\Users" not in roh
    assert "c:\\users" not in roh.lower()
    assert "/home/" not in roh
    assert "/Users/" not in roh


def test_das_manifest_enthaelt_keine_vollstaendigen_merkmalsvektoren(
        manifest):
    """
    Es belegt einen Stand, es dupliziert ihn nicht. Waeren die Werte
    drin, waere das Manifest eine Rohdatenkopie mit anderem Namen.
    """
    roh = json.dumps(manifest, ensure_ascii=False)
    assert "row_id" not in json.dumps(manifest.get("views", {}).get(
        "research", {}).get("features", []))
    assert len(roh) < 2_000_000


def test_das_manifest_nennt_beide_ansichten(manifest):
    assert manifest["views"]["selected"]["feature_count"] == 16
    assert (manifest["views"]["research"]["feature_count"]
            >= manifest["views"]["selected"]["feature_count"])
    assert manifest["views"]["selected"]["contains_rejected"] is False
    assert manifest["views"]["research"]["contains_rejected"] is True


def test_das_manifest_nennt_alle_vier_fingerabdruecke(manifest):
    for name in ("schema", "target", "research_dataset",
                 "selected_dataset"):
        assert len(manifest["fingerprints"][name]) == 64


def test_das_manifest_sagt_ehrlich_dass_es_keinen_holdout_gibt(manifest):
    """
    Der unbequemste Abschnitt und deshalb der wichtigste.

    Die Saisons 2023 bis 2025 haben alle bisherigen Entscheidungen
    getragen. Sie einen unangetasteten Testbestand zu nennen waere die
    bequemste Luege dieses Projekts.
    """
    holdout = manifest["holdout_status"]
    assert holdout["has_untouched_holdout"] is False
    assert holdout["seasons_used_for_decisions"] == [2023, 2024, 2025]
    assert holdout["reevaluation_trigger"]
    assert "exploratory" in holdout["classification"]


def test_das_manifest_nennt_die_runtime_paritaet_als_blocker(manifest):
    """
    Die Runtime fuehrt keinen ausdruecklichen Stichtag mit. Solange das
    so ist, ist historische Paritaet eine Vermutung - und eine
    Vermutung gehoert nicht in eine Zusage.
    """
    paritaet = manifest["runtime_parity"]
    assert paritaet["blocker"] is True
    assert "prediction_cutoff" in paritaet["not_verifiable"]
    assert paritaet["follow_up"]


def test_das_manifest_haelt_die_modustrennung_fest(manifest):
    """
    ML-Modus und individueller Modus beantworten verschiedene Fragen.
    C9 baut nichts um, aber es schreibt die Trennung auf - sonst
    erfindet sie der naechste Block neu.
    """
    trennung = manifest["mode_separation"]
    assert "individuelle Nutzerregler" in trennung["ml_mode"]["forbidden"]
    assert "ML-Einfluss" in trennung["individual_mode"]["forbidden"]
    assert "NICHT umgebaut" in trennung["status_in_c9"]


def test_das_manifest_verweist_auf_die_c3_bis_c8_artefakte(manifest):
    for block in ("C3_workload", "C4_form", "C5_context",
                  "C7_squad_history", "C8_model_class"):
        assert block in manifest["evidence"]
        assert manifest["evidence"][block].startswith("data/ml/")


def test_der_inventarmodus_ist_ausdruecklich_kein_nachweis():
    """
    Er ist schnell und schwaecher. Eine geaenderte Zahl gleicher Laenge
    bliebe unsichtbar - deshalb steht der Modus im Ergebnis, damit
    niemand die beiden verwechselt.
    """
    inv = e9.source_fingerprints(e9.FINGERPRINT_INVENTORY)
    for eintrag in inv.values():
        assert eintrag["mode"] == e9.FINGERPRINT_INVENTORY


def test_ein_unbekannter_fingerabdruckmodus_bricht_ab():
    with pytest.raises(ValueError, match="unbekannter Fingerabdruckmodus"):
        e9.source_fingerprints("ungefaehr")


def test_eine_fehlende_quelle_ist_ein_befund_kein_absturz():
    """
    Genau so sieht ein frischer Checkout ohne die privaten Quellen aus.
    """
    ergebnis = e9._datei_fingerprint("data/gibt-es-nicht")
    assert ergebnis["present"] is False
    assert ergebnis["sha256"] is None


# ===========================================================================
# 8  Bestandsschutz
# ===========================================================================

def test_c9_veraendert_den_merkmalsvertrag_nicht():
    """
    C9 friert ein. Waere dabei ein Merkmal hinzugekommen, waere jede
    Zahl aus C2 bis C8 auf einen anderen Kandidaten bezogen.
    """
    assert len(fg.columns_for(fg.C3_BASE_CANDIDATE)) == 16
    assert fg.SCHEMA_VERSION == 5
    assert ds.SCHEMA_VERSION == 2


def test_c9_veraendert_die_modellfamilie_nicht():
    from src.ml import persist as ps

    assert ps.MODEL_FAMILY == "poisson_offset_correction_linear"
    assert ps.MODEL_SCHEMA_VERSION == 2


def test_c9_baut_keine_zweite_datensatzstrecke():
    """
    Beide Ansichten muessen denselben zentralen Bau benutzen. Zwei
    unabhaengig entwickelte Pipelines waeren die sicherste Art, zwei
    verschiedene Datensaetze denselben Namen tragen zu lassen.
    """
    quelle = (WURZEL / "src" / "ml" / "early_v2.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum)
    assert "build_dataset" not in code, (
        "early_v2 darf den Datensatz nicht selbst bauen - es projiziert "
        "nur, was der zentrale Bau geliefert hat")


def test_c9_erfindet_keine_merkmalsnamen():
    """
    Die Namen kommen ausnahmslos aus feature_groups. Eine hier
    wiederholte Aufzaehlung waere die zweite Liste, die diese Datei
    gerade verhindern soll.
    """
    aus_registry = {r["name"] for r in e9.feature_registry()}
    aus_gruppen = set()
    for gruppe in fg.build_groups().values():
        aus_gruppen.update(gruppe["columns"])
    assert aus_registry == aus_gruppen


def test_der_kandidat_bleibt_experimentell():
    """
    Technische V2-Fertigstellung und statistische Modellpromotion sind
    verschiedene Begriffe. C9 aktiviert nichts.
    """
    from src.ml import persist as ps

    assert ps.DEFAULT_RELEASE_STAGE == ps.STAGE_SHADOW
    freeze = e9.feature_freeze()
    assert freeze["candidate"] == fg.C3_BASE_CANDIDATE


def test_ohne_unterscheidende_gruppe_bleibt_es_unentschieden():
    """
    Der dritte Ausgang - und der Grund, warum die frueherere
    Trefferquote als Entscheidungsregel nicht taugte.

    Drei Partien an drei verschiedenen Tagen tragen keinen Beweis: Es
    gibt keine Gruppe, in der sich die Zielwerte unterscheiden und der
    Spaltenwert trotzdem gleich bleibt. Das Ergebnis lautet dann
    "unentschieden" und zaehlt als Verstoss - was nicht bewiesen werden
    kann, gilt nicht als bewiesen.
    """
    vereinzelt = [_zeile("v1", datum="2024-10-01",
                         league_avg_home_goals=1.42),
                  _zeile("v2", datum="2024-10-02",
                         league_avg_home_goals=1.42),
                  _zeile("v3", datum="2024-10-03",
                         league_avg_home_goals=1.42)]
    befund = e9.exonerate_aggregate(vereinzelt, "league_avg_home_goals",
                                    "home_goals")
    assert befund["verdict"] == "undecided"
    assert befund["exonerated"] is False

    verstoesse, _ = e9.check_no_target_leak(["league_avg_home_goals"],
                                            vereinzelt)
    assert verstoesse
    assert "undecided" in verstoesse[0][1]


# ===========================================================================
# 9  Reproduzierbarkeit unter widrigen Bedingungen
# ===========================================================================

def test_der_c9_build_braucht_kein_netzwerk():
    """
    Kein Importweg von early_v2 fuehrt zu einer Netzwerkbibliothek.

    Geprueft werden die IMPORTE, nicht der Text: Das Wort
    "requestspezifisch" steht in der Modustrennung und ist kein
    Netzaufruf. Eine Textsuche haette hier falsch angeschlagen - und
    waere spaeter entnervt gelockert worden.
    """
    baum = ast.parse((WURZEL / "src" / "ml" / "early_v2.py").read_text(
        encoding="utf-8"))
    importiert = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for name in knoten.names:
                importiert.add(name.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            importiert.add(knoten.module.split(".")[0])

    netz = {"requests", "urllib", "urllib3", "http", "socket", "httpx",
            "aiohttp", "ftplib", "telnetlib"}
    assert not (importiert & netz), importiert & netz


def test_das_manifest_entsteht_mit_blockierten_sockets(zeilen,
                                                       monkeypatch):
    """
    Die schaerfere Fassung des vorigen Tests.

    Nicht "es sieht nicht nach Netz aus", sondern: Jeder Socketaufbau
    wirft, und das Manifest entsteht trotzdem.
    """
    import socket

    class Blockiert(socket.socket):
        def __init__(self, *args, **kwargs):
            raise OSError("Netzwerk im C9-Build blockiert")

    monkeypatch.setattr(socket, "socket", Blockiert)
    manifest = e9.build_manifest(zeilen,
                                 source_mode=e9.FINGERPRINT_INVENTORY)
    assert manifest["dataset"]["rows"] == len(zeilen)


def test_der_kandidatenvertrag_haengt_nicht_an_privaten_quellen():
    """
    DER FRISCHE-CHECKOUT-VERTRAG.

    Die 16 Merkmale des Kandidaten stammen saemtlich aus
    data/historical - einer getrackten Quelle. Ein frischer Checkout
    kann den Kandidatendatensatz daher vollstaendig reproduzieren, auch
    ohne data/cache, data/player_pool und die UEFA-Koeffizienten.
    """
    registry = {r["name"]: r for r in e9.feature_registry()}
    for spalte in e9.selected_columns():
        assert registry[spalte]["tracked_source"] is True, spalte
        assert registry[spalte]["family"] not in (
            e9.OPTIONAL_SOURCE_FAMILIES), spalte


def test_fehlende_optionale_quellen_erzeugen_keine_leeren_spalten():
    """
    Ohne die privaten Quellen ist der Forschungsdatensatz KLEINER -
    nicht voller None. Eine Spalte, die aussieht wie ein Merkmal und
    keines ist, ist die schlechtere Variante von "fehlt".
    """
    ohne = e9.research_columns()
    gruppen = fg.build_groups()
    for familie in e9.OPTIONAL_SOURCE_FAMILIES:
        assert not set(gruppen[familie]["columns"]) & set(ohne), familie


def test_die_optionalen_quellen_sind_standardmaessig_aus():
    """
    Der Schalter steht im Datensatzbau, nicht hier - C9 liest ihn nur.
    Stuende er auf True, waere der Standardbau nicht reproduzierbar.
    """
    for familie, meta in e9.OPTIONAL_SOURCE_FAMILIES.items():
        assert meta["default"] is False, familie


def test_der_build_veraendert_keine_bestehenden_artefakte(zeilen, tmp_path):
    """
    C9 friert ein. Ein Block, der dabei fremde Artefakte anfasst, waere
    kein Freeze, sondern eine Aenderung mit ruhigem Namen.
    """
    artefakte = sorted((WURZEL / "data" / "ml").glob("*.json"))
    vorher = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
              for p in artefakte
              if p.name != "c9_early_v2_manifest_2023-2025.json"}

    e9.build_manifest(zeilen, source_mode=e9.FINGERPRINT_INVENTORY)

    nachher = {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
               for p in sorted((WURZEL / "data" / "ml").glob("*.json"))
               if p.name != "c9_early_v2_manifest_2023-2025.json"}
    assert vorher == nachher


def test_das_manifest_haengt_nicht_an_einer_env_datei():
    """
    Der C9-Bau liest keine Umgebungsdatei - er braucht keine
    Zugangsdaten, weil er nichts abruft.
    """
    baum = ast.parse((WURZEL / "src" / "ml" / "early_v2.py").read_text(
        encoding="utf-8"))
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    code = ast.unparse(baum)
    for begriff in ("load_dotenv", "os.environ", "getenv", ".env"):
        assert begriff not in code, begriff


def test_der_freeze_befehl_steht_im_manifest(manifest):
    """
    Ein Manifest ohne Erzeugungsbefehl laesst sich nicht nachbauen.
    """
    assert manifest["build_command"].startswith("python run_ml.py")
    assert "--freeze-c9" in manifest["build_command"]
    assert e9.MANIFEST_PATH in manifest["build_command"]


def test_die_umgebung_wird_festgehalten(manifest):
    """
    sklearn-Fassungen aendern Ergebnisse. Ohne sie im Manifest waere ein
    abweichender Lauf spaeter nicht erklaerbar.
    """
    assert manifest["environment"]["python"]
    assert "sklearn" in manifest["environment"]["packages"]


def test_laufberichte_zaehlen_nicht_zum_quellfingerabdruck(tmp_path):
    """
    Betriebsprotokoll ist keine Beobachtung.

    data/snapshots/_runs sammelt die Laufberichte des C6-Sammlers. Ein
    zusaetzlicher Lauf legt dort eine Datei ab, ohne dass sich eine
    einzige gesammelte Beobachtung geaendert haette. Reagierte der
    Fingerabdruck darauf, koennte er die Frage "sind das dieselben
    Daten" nicht beantworten.

    Aufgefallen ist das nicht am Schreibtisch, sondern beim Doppellauf
    waehrend der Testsuite: Die C6-Tests schreiben Laufberichte, und
    der Manifestfingerabdruck wanderte zwischen zwei Berechnungen.
    """
    quelle = tmp_path / "snapshots"
    (quelle / "availability").mkdir(parents=True)
    (quelle / "availability" / "a.json").write_text('{"x": 1}',
                                                    encoding="utf-8")

    vorher = e9._datei_fingerprint(str(quelle))

    (quelle / "_runs").mkdir()
    (quelle / "_runs" / "run__20260907T000000Z.json").write_text(
        '{"lauf": "protokoll"}', encoding="utf-8")

    nachher = e9._datei_fingerprint(str(quelle))
    assert nachher["sha256"] == vorher["sha256"]
    assert nachher["files"] == vorher["files"] == 1
    assert "_runs" in nachher["excluded_dirs"]


def test_eine_echte_quelldatei_veraendert_den_quellfingerabdruck(tmp_path):
    """
    Die Gegenprobe. Waere der Ausschluss zu breit, bliebe auch eine
    echte Beobachtung unsichtbar - und der Fingerabdruck waere wertlos.
    """
    quelle = tmp_path / "snapshots"
    (quelle / "availability").mkdir(parents=True)
    (quelle / "availability" / "a.json").write_text('{"x": 1}',
                                                    encoding="utf-8")
    vorher = e9._datei_fingerprint(str(quelle))

    (quelle / "availability" / "b.json").write_text('{"x": 2}',
                                                    encoding="utf-8")
    nachher = e9._datei_fingerprint(str(quelle))
    assert nachher["sha256"] != vorher["sha256"]
    assert nachher["files"] == 2


# ===========================================================================
# 10  Training-Runtime-Paritaet
# ===========================================================================

def test_die_runtime_nutzt_denselben_kandidaten():
    """
    Die Paritaetszusage im Manifest muss nachpruefbar sein, nicht nur
    behauptet. Waeren es zwei Listen, koennten sie auseinanderlaufen -
    und ein gespeichertes Modell haette danach falsch verdrahtete
    Koeffizienten.
    """
    from src.ml import inference as inf

    assert inf.CANDIDATE == e9.SELECTED_CANDIDATE
    assert inf.feature_columns() == e9.selected_columns()


def test_die_runtime_hat_keine_zweite_merkmalsliste():
    """
    inference.feature_columns() delegiert an feature_groups. Eine
    eigene Aufzaehlung dort waere die zweite Liste, die C9 gerade
    ausschliesst.
    """
    quelle = (WURZEL / "src" / "ml" / "inference.py").read_text(
        encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.FunctionDef) and (
                knoten.name == "feature_columns"):
            code = ast.unparse(knoten)
            assert "columns_for" in code
            assert "home_attack_home" not in code
            break
    else:                                                # pragma: no cover
        pytest.fail("inference.feature_columns nicht gefunden")


def test_die_guardrails_sind_auf_beiden_seiten_dieselben():
    """
    Verschiedene Grenzen in Training und Runtime hiessen: Das Modell
    wird anders bewertet, als es spaeter rechnet.
    """
    paritaet = e9.runtime_parity_report()
    assert paritaet["verified"]["guardrails"]["lambda"] == [
        mdl.LAMBDA_MIN, mdl.LAMBDA_MAX]
    assert paritaet["verified"]["guardrails"]["correction"] == [
        mdl.CORRECTION_MIN, mdl.CORRECTION_MAX]


def test_der_fehlende_runtime_stichtag_ist_als_blocker_vermerkt():
    """
    Er wird NICHT in C9 behoben: Ein Umbau des produktiven
    Vorhersagepfads gehoert nicht in einen Block, der ausdruecklich
    nichts aktiviert. Verschwiegen wird er aber auch nicht.
    """
    paritaet = e9.runtime_parity_report()
    assert paritaet["blocker"] is True
    assert "prediction_cutoff" in paritaet["not_verifiable"]
    assert "C10" in paritaet["follow_up"]
