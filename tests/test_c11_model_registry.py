"""
Tests der Modellregistry (V2-C11).

WORUM ES GEHT
Vor C11 fuehrte der Ladeweg zu einem festen Pfad, und die Freigabestufe
stand IM Bundle. Wer die Datei ersetzte, ersetzte das Modell; das
vorhandene Bundle stand auf "experimental", und experimental deckt den
aktiven Betrieb. Es war eine Umgebungsvariable von der Wirkung
entfernt.

Die schaerfsten Tests hier sind deshalb die ablehnenden. Ein Test, der
zeigt, dass eine Aktivierung funktioniert, beweist wenig. Beweisen muss
man, dass sie in jedem falschen Fall NICHT funktioniert.

KEIN TEST VERAENDERT DEN ECHTEN PROJEKTSTAND. Jeder arbeitet auf
tmp_path oder auf einem Dokument im Speicher.
"""

import json
import os
import pathlib

import pytest

from src.ml import model_registry as mr
from src.ml import runtime as rt

WURZEL = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Ein vollstaendiger Kunsteintrag
# ---------------------------------------------------------------------------

def _bundle(tmp_path, inhalt=None, name="bundle.json"):
    """Eine echte Datei, damit der Hash etwas zu hashen hat."""
    verzeichnis = tmp_path / "data" / "ml" / "models"
    verzeichnis.mkdir(parents=True, exist_ok=True)
    pfad = verzeichnis / name
    pfad.write_text(json.dumps(inhalt or {"model_id": "clm-test",
                                          "models": {"home": {}}},
                               sort_keys=True), encoding="utf-8")
    return pfad


def _eintrag(tmp_path, model_id="clm-test", stage=mr.STAGE_CANDIDATE,
             evaluation="accepted", **extra):
    pfad = _bundle(tmp_path, {"model_id": model_id}, f"{model_id}.json")
    relativ = f"data/ml/models/{model_id}.json"
    eintrag = {
        "model_id": model_id,
        "model_name": "team_profile_cl",
        "model_family": "poisson_offset_correction_linear",
        "bundle_schema_version": 2,
        "stage": stage,
        "bundle_path": relativ,
        "bundle_sha256": mr.bundle_sha256(str(pfad)),
        "feature_schema_fingerprint": "f" * 64,
        "c9_manifest_fingerprint": "9" * 64,
        "c10_contract_fingerprint": "a" * 64,
        "evaluation_artifact": "data/ml/eval.json",
        "evaluation_status": evaluation,
        "state_reason": "Kunsteintrag fuer den Test",
    }
    eintrag.update(extra)
    return eintrag


def _registry(tmp_path, *eintraege):
    doc = mr.empty_registry()
    doc["models"] = list(eintraege)
    return doc


@pytest.fixture
def freigegeben(tmp_path):
    """Ein Modell im Schatten, bereit fuer die Freigabe."""
    eintrag = _eintrag(tmp_path, stage=mr.STAGE_SHADOW)
    doc = _registry(tmp_path, eintrag)
    freigabe = mr.build_approval(eintrag, mr.STAGE_ACTIVE,
                                 "Testfreigabe im isolierten Verzeichnis")
    return doc, freigabe


# ===========================================================================
# 1  Validierung
# ===========================================================================

def test_eine_gueltige_registry_hat_keine_befunde(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    assert mr.validate_registry(doc, str(tmp_path)) == []


def test_die_leere_registry_ist_gueltig():
    """
    "Kein Modell registriert" ist ein Zustand, kein Fehler. Sonst
    braeuchte ein frisches Repository erst eine Reparatur.
    """
    assert mr.validate_registry(mr.empty_registry(),
                                pruefe_bundles=False) == []


@pytest.mark.parametrize("feld", mr.REQUIRED_FIELDS)
def test_ein_fehlendes_pflichtfeld_faellt_auf(tmp_path, feld):
    eintrag = _eintrag(tmp_path)
    eintrag[feld] = None
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any(feld in b for b in befunde), befunde


def test_eine_unbekannte_schemafassung_faellt_auf(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    doc["schema_version"] = 99
    befunde = mr.validate_registry(doc, str(tmp_path))
    assert any("Schemafassung" in b for b in befunde)


def test_eine_unbekannte_stufe_faellt_auf(tmp_path):
    eintrag = _eintrag(tmp_path, stage="produktiv")
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("unbekannte Stufe" in b for b in befunde)


def test_eine_doppelte_modell_id_faellt_auf(tmp_path):
    a = _eintrag(tmp_path, model_id="clm-doppelt")
    doc = _registry(tmp_path, a, dict(a))
    befunde = mr.validate_registry(doc, str(tmp_path))
    assert any("doppelte Modell-ID" in b for b in befunde)


def test_zwei_aktive_modelle_fallen_auf(tmp_path, freigegeben):
    doc, freigabe = freigegeben
    aktiv = dict(doc["models"][0], stage=mr.STAGE_ACTIVE,
                 approval=freigabe)
    zweiter = dict(aktiv, model_id="clm-zwei")
    doc2 = _registry(tmp_path, aktiv, zweiter)
    befunde = mr.validate_registry(doc2, str(tmp_path),
                                   pruefe_bundles=False)
    assert any("mehr als ein aktives Modell" in b for b in befunde)


@pytest.mark.parametrize("pfad", [
    "/etc/models/bundle.json",
    "C:\\Users\\elieb\\models\\bundle.json",
    "\\\\server\\share\\bundle.json",
    "data/../../etc/passwd",
])
def test_absolute_und_ausbrechende_pfade_werden_abgelehnt(tmp_path, pfad):
    """
    Ein absoluter Pfad in einem versionierten Dokument ist auf jedem
    anderen Rechner falsch und verraet die lokale Verzeichnisstruktur.
    Beide Schreibweisen werden geprueft: Ein Windowspfad faellt unter
    Linux nicht durch os.path.isabs.
    """
    eintrag = _eintrag(tmp_path)
    eintrag["bundle_path"] = pfad
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("Pfad" in b for b in befunde), befunde


def test_ein_fehlendes_bundle_faellt_auf(tmp_path):
    eintrag = _eintrag(tmp_path)
    eintrag["bundle_path"] = "data/ml/models/gibt-es-nicht.json"
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("Bundle fehlt" in b for b in befunde)


def test_ein_abweichender_bundle_hash_faellt_auf(tmp_path):
    """
    DER KERN DER SACHE.

    Der Hash liegt in der Registry, nicht im Bundle. Wer die Datei
    austauscht, tauscht den bundleeigenen Integritaetshash mit aus;
    diesen hier nicht.
    """
    eintrag = _eintrag(tmp_path)
    eintrag["bundle_sha256"] = "0" * 64
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("Bundle-Hash weicht ab" in b for b in befunde)


def test_ein_veraendertes_bundle_faellt_auf(tmp_path):
    """Dieselbe Regel, aber von der anderen Seite: Die Datei aendert sich."""
    eintrag = _eintrag(tmp_path)
    doc = _registry(tmp_path, eintrag)
    assert mr.validate_registry(doc, str(tmp_path)) == []

    (tmp_path / eintrag["bundle_path"]).write_text(
        '{"model_id": "etwas anderes"}', encoding="utf-8")
    befunde = mr.validate_registry(doc, str(tmp_path))
    assert any("Bundle-Hash weicht ab" in b for b in befunde)


def test_ein_aktives_modell_ohne_freigabe_faellt_auf(tmp_path):
    eintrag = _eintrag(tmp_path, stage=mr.STAGE_ACTIVE)
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("ohne gueltige Freigabe" in b for b in befunde)


@pytest.mark.parametrize("status", mr.EVALUATION_BLOCKING)
def test_ein_aktives_modell_braucht_accepted(tmp_path, status):
    """
    rejected, inconclusive, not_evaluable, infrastructure_only,
    pending und unknown sind kein Beleg, und ein fehlender Beleg
    aktiviert nichts.
    """
    eintrag = _eintrag(tmp_path, stage=mr.STAGE_ACTIVE,
                       evaluation=status)
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("traegt keine Aktivierung" in b for b in befunde), befunde


def test_ein_unbekanntes_rueckfallziel_faellt_auf(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    doc["rollback_target"] = "clm-gibt-es-nicht"
    befunde = mr.validate_registry(doc, str(tmp_path))
    assert any("nicht registriert" in b for b in befunde)


def test_validate_meldet_alle_befunde_nicht_nur_den_ersten(tmp_path):
    """
    Wer eine kaputte Registry repariert, will alle Stellen kennen.
    """
    eintrag = _eintrag(tmp_path, stage="unfug")
    eintrag["bundle_sha256"] = "0" * 64
    eintrag["model_family"] = None
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert len(befunde) >= 3


# ===========================================================================
# 2  Uebergaenge
# ===========================================================================

def test_candidate_zu_shadow_ist_erlaubt(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    neu = mr.set_stage(doc, "clm-test", mr.STAGE_SHADOW)
    assert neu["models"][0]["stage"] == mr.STAGE_SHADOW


def test_candidate_direkt_zu_active_wird_abgelehnt(tmp_path, freigegeben):
    """
    Ein Modell, das nie im Schatten gelaufen ist, hat nie gegen die
    Wirklichkeit gerechnet. Seine erste Begegnung mit echten Anfragen
    waere zugleich seine erste Wirkung auf Nutzer.
    """
    _, freigabe = freigegeben
    doc = _registry(tmp_path, _eintrag(tmp_path))
    with pytest.raises(mr.RegistryError, match="nie im Schatten"):
        mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)


def test_shadow_zu_active_ohne_freigabe_wird_abgelehnt(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path, stage=mr.STAGE_SHADOW))
    with pytest.raises(mr.RegistryError, match="ohne gueltige Freigabe"):
        mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE)


def test_eine_freigabe_fuer_ein_anderes_modell_wird_abgelehnt(
        tmp_path, freigegeben):
    doc, freigabe = freigegeben
    fremd = dict(freigabe, model_id="clm-anderes")
    with pytest.raises(mr.RegistryError, match="gehoert zu"):
        mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, fremd)


def test_eine_freigabe_fuer_einen_anderen_schritt_wird_abgelehnt(
        tmp_path, freigegeben):
    doc, freigabe = freigegeben
    verdreht = dict(freigabe, transition=mr.STAGE_SHADOW)
    with pytest.raises(mr.RegistryError, match="gilt fuer"):
        mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, verdreht)


@pytest.mark.parametrize("feld", [
    "bundle_sha256", "feature_schema_fingerprint",
    "c9_manifest_fingerprint", "c10_contract_fingerprint",
    "evaluation_artifact", "evaluation_status",
])
def test_eine_freigabe_verfaellt_wenn_sich_eine_tatsache_aendert(
        tmp_path, freigegeben, feld):
    """
    DER KERN DES FREIGABEGATES.

    Das Zeichen ist eine Pruefsumme ueber die Tatsachen, unter denen
    freigegeben wurde. Aendert sich eine davon, ergibt dieselbe
    Rechnung ein anderes Zeichen, und die Freigabe verfaellt von
    selbst. Kein Schalter, den man ueberall setzen kann.
    """
    doc, freigabe = freigegeben
    verbogen = json.loads(json.dumps(doc))
    verbogen["models"][0][feld] = "abweichender-wert"

    # Abgelehnt wird in jedem Fall. Bei evaluation_status greift schon
    # der Statusriegel, bevor die Freigabe ueberhaupt geprueft wird -
    # eine zweite Sperre vor derselben Tuer, nicht ein anderes
    # Ergebnis.
    with pytest.raises(mr.RegistryError):
        mr.set_stage(verbogen, "clm-test", mr.STAGE_ACTIVE, freigabe)

    # Die Freigabe selbst passt danach ebenfalls nicht mehr.
    ok, _ = mr.verify_approval(verbogen["models"][0], freigabe,
                               mr.STAGE_ACTIVE)
    assert ok is False


def test_eine_freigabe_ohne_begruendung_entsteht_gar_nicht(
        tmp_path, freigegeben):
    doc, _ = freigegeben
    for leer in ("", "   ", "ok"):
        with pytest.raises(mr.RegistryError, match="Begruendung"):
            mr.build_approval(doc["models"][0], mr.STAGE_ACTIVE, leer)


def test_ein_gueltiger_uebergang_funktioniert(tmp_path, freigegeben):
    """
    Die Gegenprobe. Ohne sie koennte das Gate immer ablehnen und
    saemtliche Ablehnungstests waeren trotzdem gruen.
    """
    doc, freigabe = freigegeben
    neu = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)
    assert neu["models"][0]["stage"] == mr.STAGE_ACTIVE
    assert mr.validate_registry(neu, str(tmp_path)) == []


def test_das_bisherige_active_wird_zum_rueckfallziel(tmp_path,
                                                     freigegeben):
    doc, freigabe = freigegeben
    alt = dict(_eintrag(tmp_path, model_id="clm-alt",
                        stage=mr.STAGE_ACTIVE),
               approval=None)
    doc["models"].append(alt)

    neu = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)
    stufen = {e["model_id"]: e["stage"] for e in neu["models"]}
    assert stufen["clm-test"] == mr.STAGE_ACTIVE
    assert stufen["clm-alt"] == mr.STAGE_ROLLBACK
    assert neu["rollback_target"] == "clm-alt"


def test_nach_einem_wechsel_gibt_es_genau_ein_actives(tmp_path,
                                                      freigegeben):
    doc, freigabe = freigegeben
    doc["models"].append(_eintrag(tmp_path, model_id="clm-alt",
                                  stage=mr.STAGE_ACTIVE))
    neu = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)
    aktive = [e for e in neu["models"] if e["stage"] == mr.STAGE_ACTIVE]
    assert len(aktive) == 1


def test_ein_unbekanntes_modell_laesst_sich_nicht_umstufen(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    with pytest.raises(mr.RegistryError, match="nicht registriert"):
        mr.set_stage(doc, "clm-fremd", mr.STAGE_SHADOW)


def test_eine_doppelte_registrierung_wird_abgelehnt(tmp_path):
    doc = mr.register_candidate(mr.empty_registry(), _eintrag(tmp_path))
    with pytest.raises(mr.RegistryError, match="bereits registriert"):
        mr.register_candidate(doc, _eintrag(tmp_path))


# ===========================================================================
# 3  Rollback
# ===========================================================================

def test_rollback_ohne_ziel_wird_abgelehnt(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    with pytest.raises(mr.RegistryError, match="Kein Rueckfallziel"):
        mr.rollback(doc)


def test_rollback_stellt_das_vorherige_modell_wieder_her(tmp_path,
                                                         freigegeben):
    doc, freigabe = freigegeben

    alt_eintrag = _eintrag(tmp_path, model_id="clm-alt",
                           stage=mr.STAGE_SHADOW)
    alt_freigabe = mr.build_approval(alt_eintrag, mr.STAGE_ACTIVE,
                                     "frueherer Stand, Testfreigabe")
    doc["models"].append(alt_eintrag)
    doc = mr.set_stage(doc, "clm-alt", mr.STAGE_ACTIVE, alt_freigabe)
    doc = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)
    assert doc["rollback_target"] == "clm-alt"

    zurueck = mr.rollback(doc)
    stufen = {e["model_id"]: e["stage"] for e in zurueck["models"]}
    assert stufen["clm-alt"] == mr.STAGE_ACTIVE
    assert stufen["clm-test"] == mr.STAGE_ROLLBACK
    assert mr.validate_registry(zurueck, str(tmp_path)) == []


def test_ein_beschaedigtes_rueckfallziel_wird_nicht_reaktiviert(
        tmp_path, freigegeben):
    """
    Ein Rueckfallziel, dessen Freigabe nicht mehr passt, ist kein
    Rueckfallziel. Es blind zu reaktivieren waere ein Rollback in einen
    ungeprueften Zustand.
    """
    doc, freigabe = freigegeben
    alt_eintrag = _eintrag(tmp_path, model_id="clm-alt",
                           stage=mr.STAGE_SHADOW)
    alt_freigabe = mr.build_approval(alt_eintrag, mr.STAGE_ACTIVE,
                                     "frueherer Stand, Testfreigabe")
    doc["models"].append(alt_eintrag)
    doc = mr.set_stage(doc, "clm-alt", mr.STAGE_ACTIVE, alt_freigabe)
    doc = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)

    for eintrag in doc["models"]:
        if eintrag["model_id"] == "clm-alt":
            eintrag["bundle_sha256"] = "0" * 64

    with pytest.raises(mr.RegistryError, match="keine gueltige Freigabe"):
        mr.rollback(doc)


# ===========================================================================
# 4  Atomares Schreiben
# ===========================================================================

def test_eine_ungueltige_registry_wird_gar_nicht_geschrieben(tmp_path):
    """
    Erst validieren, dann schreiben. Andersherum laege eine ungueltige
    Registry auf der Platte und die Runtime saehe sie.
    """
    ziel = tmp_path / "data" / "ml" / "model_registry.json"
    gut = _registry(tmp_path, _eintrag(tmp_path))
    mr.write_registry(gut, str(ziel), str(tmp_path))
    vorher = ziel.read_text(encoding="utf-8")

    kaputt = _registry(tmp_path, _eintrag(tmp_path, stage="unfug"))
    with pytest.raises(mr.RegistryError):
        mr.write_registry(kaputt, str(ziel), str(tmp_path))

    assert ziel.read_text(encoding="utf-8") == vorher


def test_ein_fehler_beim_schreiben_laesst_die_alte_registry_stehen(
        tmp_path, monkeypatch):
    ziel = tmp_path / "data" / "ml" / "model_registry.json"
    gut = _registry(tmp_path, _eintrag(tmp_path))
    mr.write_registry(gut, str(ziel), str(tmp_path))
    vorher = ziel.read_text(encoding="utf-8")

    def _bricht(*args, **kwargs):
        raise OSError("Datentraeger voll")

    monkeypatch.setattr(os, "replace", _bricht)
    with pytest.raises(OSError):
        mr.write_registry(gut, str(ziel), str(tmp_path))

    assert ziel.read_text(encoding="utf-8") == vorher


def test_eine_abgebrochene_schreibung_laesst_keine_reste(tmp_path,
                                                         monkeypatch):
    """
    Die temporaere Datei traegt .tmp und wuerde nie als Registry
    gelesen. Liegenbleiben soll sie trotzdem nicht.
    """
    ziel = tmp_path / "data" / "ml" / "model_registry.json"
    gut = _registry(tmp_path, _eintrag(tmp_path))

    monkeypatch.setattr(os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError("abgebrochen")))
    with pytest.raises(OSError):
        mr.write_registry(gut, str(ziel), str(tmp_path))

    reste = list((tmp_path / "data" / "ml").glob(".registry-*.tmp"))
    assert reste == []


def test_die_temporaere_datei_wird_nicht_als_registry_gelesen(tmp_path):
    verzeichnis = tmp_path / "data" / "ml"
    verzeichnis.mkdir(parents=True)
    (verzeichnis / ".registry-xyz.tmp").write_text("{kaputt",
                                                   encoding="utf-8")
    doc = mr.load_registry(repo_root=str(tmp_path))
    assert doc == mr.empty_registry()


def test_ein_leser_sieht_immer_einen_vollstaendigen_zustand(tmp_path):
    """
    os.replace haengt den Namen in einem Schritt um. Nach jedem
    Schreiben ist die Datei vollstaendig lesbar - nie halb.
    """
    ziel = tmp_path / "data" / "ml" / "model_registry.json"
    for i in range(8):
        doc = _registry(tmp_path, _eintrag(tmp_path,
                                           model_id=f"clm-{i}"))
        mr.write_registry(doc, str(ziel), str(tmp_path))
        gelesen = json.loads(ziel.read_text(encoding="utf-8"))
        assert gelesen["models"][0]["model_id"] == f"clm-{i}"
        assert mr.validate_registry(gelesen, str(tmp_path)) == []


def test_zwei_schreibvorgaenge_hinterlassen_keinen_mischzustand(tmp_path):
    """
    Jeder Schreibvorgang benutzt eine eigene temporaere Datei
    (tempfile.mkstemp) und ersetzt danach atomar. Zwei Laeufe koennen
    einander ueberholen, aber nicht vermischen: Am Ende steht genau
    einer der beiden Staende.
    """
    ziel = tmp_path / "data" / "ml" / "model_registry.json"
    a = _registry(tmp_path, _eintrag(tmp_path, model_id="clm-a"))
    b = _registry(tmp_path, _eintrag(tmp_path, model_id="clm-b"))

    mr.write_registry(a, str(ziel), str(tmp_path))
    mr.write_registry(b, str(ziel), str(tmp_path))

    gelesen = json.loads(ziel.read_text(encoding="utf-8"))
    assert len(gelesen["models"]) == 1
    assert gelesen["models"][0]["model_id"] in ("clm-a", "clm-b")


def test_eine_kaputte_registry_wirft_statt_zu_raten(tmp_path):
    verzeichnis = tmp_path / "data" / "ml"
    verzeichnis.mkdir(parents=True)
    (verzeichnis / "model_registry.json").write_text("{nicht json",
                                                     encoding="utf-8")
    with pytest.raises(mr.RegistryError, match="nicht lesbar"):
        mr.load_registry(repo_root=str(tmp_path))


def test_eine_fehlende_registry_ist_kein_fehler(tmp_path):
    assert mr.load_registry(repo_root=str(tmp_path)) == mr.empty_registry()


# ===========================================================================
# 5  Auswahl fuer die Runtime
# ===========================================================================

def test_ohne_aktives_modell_gibt_es_keines(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    eintrag, grund = mr.active_entry(doc, str(tmp_path))
    assert eintrag is None
    assert grund == "no_active_model"


def test_ein_candidate_wird_nicht_als_active_geliefert(tmp_path):
    for stufe in (mr.STAGE_CANDIDATE, mr.STAGE_SHADOW,
                  mr.STAGE_ROLLBACK):
        doc = _registry(tmp_path, _eintrag(tmp_path, stage=stufe))
        eintrag, _ = mr.active_entry(doc, str(tmp_path))
        assert eintrag is None, stufe


def test_eine_ungueltige_registry_liefert_kein_modell(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path, stage=mr.STAGE_ACTIVE))
    eintrag, grund = mr.active_entry(doc, str(tmp_path))
    assert eintrag is None
    assert grund.startswith("registry_invalid")


def test_ein_beschaedigtes_bundle_wird_nicht_geliefert(tmp_path,
                                                       freigegeben):
    doc, freigabe = freigegeben
    doc = mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)
    assert mr.active_entry(doc, str(tmp_path))[0] is not None

    (tmp_path / doc["models"][0]["bundle_path"]).write_text(
        '{"anderes": true}', encoding="utf-8")
    eintrag, grund = mr.active_entry(doc, str(tmp_path))
    assert eintrag is None
    assert "Bundle-Hash" in grund


def test_shadow_entries_liefert_nur_schattenmodelle(tmp_path):
    doc = _registry(tmp_path,
                    _eintrag(tmp_path, model_id="clm-c"),
                    _eintrag(tmp_path, model_id="clm-s",
                             stage=mr.STAGE_SHADOW))
    schatten = mr.shadow_entries(doc)
    assert [e["model_id"] for e in schatten] == ["clm-s"]


# ===========================================================================
# 6  Runtime-Anbindung
# ===========================================================================

def test_die_runtime_verlangt_einen_registryeintrag():
    """
    Ohne aktives Modell in der Registry wirkt auch ein geladenes
    Bundle nicht. Das ist der Fall des heutigen Projektstands.
    """
    ok, grund = rt._registry_erlaubt("clm-irgendwas")
    assert ok is False
    assert grund == rt.REASON_NOT_ACTIVE_IN_REGISTRY


def test_ein_fremdes_modell_wird_abgelehnt(monkeypatch):
    """
    Das geladene Bundle muss GENAU das registrierte sein. Ein anderes
    Modell mit gueltiger Registry reicht nicht.
    """
    from src.ml import model_registry as mreg

    monkeypatch.setattr(mreg, "active_entry",
                        lambda *a, **k: ({"model_id": "clm-aktiv"}, None))
    ok, grund = rt._registry_erlaubt("clm-anderes")
    assert ok is False
    assert grund == rt.REASON_NOT_ACTIVE_IN_REGISTRY

    ok, grund = rt._registry_erlaubt("clm-aktiv")
    assert ok is True and grund is None


def test_eine_unbrauchbare_registry_fuehrt_zur_baseline(monkeypatch):
    from src.ml import model_registry as mreg

    monkeypatch.setattr(
        mreg, "active_entry",
        lambda *a, **k: (None, "registry_invalid: irgendetwas"))
    ok, grund = rt._registry_erlaubt("clm-egal")
    assert ok is False
    assert grund == rt.REASON_REGISTRY_UNUSABLE


def test_die_neuen_gruende_sind_registriert():
    assert rt.REASON_NOT_ACTIVE_IN_REGISTRY in rt.RUNTIME_REASONS
    assert rt.REASON_REGISTRY_UNUSABLE in rt.RUNTIME_REASONS


def test_die_registrypruefung_steht_nach_der_stufenpruefung():
    """
    Die Reihenfolge ist wichtig: Die Registrypruefung kann nur
    ablehnen. Stuende sie vor der Stufenpruefung, verdeckte sie den
    spezifischeren Grund.
    """
    import inspect

    quelle = inspect.getsource(rt.resolve_simulation_lambdas)
    i_stufe = quelle.index("stufe not in erlaubte_stufen")
    i_registry = quelle.index("_registry_erlaubt(model_id)")
    assert i_stufe < i_registry


def test_der_standardmodus_bleibt_off():
    """
    C11 aktiviert nichts. Der Standardweg der Runtime rechnet weiterhin
    ohne ML.
    """
    assert rt.DEFAULT_MODE == rt.MODE_OFF


# ===========================================================================
# 7  Schattenisolation
# ===========================================================================

def test_nur_active_darf_die_ausgabe_bestimmen():
    assert mr.STAGES_AFFECTING_OUTPUT == (mr.STAGE_ACTIVE,)
    for stufe in (mr.STAGE_CANDIDATE, mr.STAGE_SHADOW,
                  mr.STAGE_ROLLBACK):
        assert stufe not in mr.STAGES_AFFECTING_OUTPUT


def test_der_schattenmodus_liefert_die_baseline(tmp_path, monkeypatch):
    """
    Im Schattenmodus wird gerechnet und berichtet, aber die Antwort
    bleibt die Baseline. Das ist bestehendes Verhalten; der Test haelt
    es fest, weil die Registry daran nichts aendern darf.
    """
    from src.ml import runtime as runtime_modul

    assert runtime_modul.REASON_SHADOW_ONLY == "shadow_mode"
    assert runtime_modul.MODE_SHADOW in runtime_modul.MODES


def test_ein_schattenfehler_blockiert_die_simulation_nicht():
    """
    Der breite Ausnahmefaenger im ML-Zweig ist Absicht: Ein
    Programmierfehler in der ML-Kette darf einem Nutzer nicht die
    Prognose zerstoeren.
    """
    import inspect

    quelle = inspect.getsource(rt)
    assert "except Exception:" in quelle
    assert "REASON_UNEXPECTED_ERROR" in quelle


# ===========================================================================
# 8  Modustrennung
# ===========================================================================

def test_die_ligasimulation_kennt_die_registry_nicht():
    """
    Die Registry gehoert zum ML-Zweig. Der individuelle Modus darf sie
    nicht einmal importieren, sonst koppelten beide Pfade ueber einen
    Registryfehler.
    """
    for name in ("league_match_sim.py", "season_sim.py",
                 "simulate_scores.py", "poisson.py"):
        pfad = WURZEL / "src" / "predict" / name
        if pfad.exists():
            text = pfad.read_text(encoding="utf-8")
            assert "model_registry" not in text, name
            assert "src.ml" not in text, name


def test_die_registry_wird_nur_im_ml_zweig_gelesen():
    """
    Ein Registryfehler darf den individuellen Modus nicht beruehren.
    Der Import steht deshalb in der Funktion, nicht am Modulkopf.
    """
    import inspect

    quelle = inspect.getsource(rt._registry_erlaubt)
    assert "from src.ml import model_registry" in quelle


def test_die_registry_kennt_kein_ml_gewicht():
    """
    ml_weight mischt Baseline und Modell. Das ist eine Frage der
    Betriebsart, nicht der Modellauswahl - die Registry hat damit
    nichts zu tun.
    """
    import ast

    baum = ast.parse((WURZEL / "src" / "ml" / "model_registry.py"
                      ).read_text(encoding="utf-8"))
    # Docstrings und Zeichenketten entfernen: Das Wort darf in der
    # Beschreibung der Modustrennung vorkommen - dort steht gerade,
    # dass die Registry es NICHT kennt. Es darf nur nicht im Code
    # stehen.
    for knoten in ast.walk(baum):
        if (isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and ast.get_docstring(knoten)):
            knoten.body = knoten.body[1:]
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Constant) and isinstance(knoten.value,
                                                           str):
            knoten.value = ""
    assert "ml_weight" not in ast.unparse(baum)


# ===========================================================================
# 9  Determinismus und Artefakt
# ===========================================================================

def test_der_registryfingerabdruck_ist_stabil(tmp_path):
    doc = _registry(tmp_path, _eintrag(tmp_path))
    assert mr.registry_fingerprint(doc) == mr.registry_fingerprint(doc)


def test_der_fingerabdruck_ignoriert_zeitstempel(tmp_path):
    a = _registry(tmp_path, _eintrag(tmp_path))
    b = json.loads(json.dumps(a))
    b["models"][0]["registered_at"] = "2026-01-01T00:00:00Z"
    b["updated_at"] = "2026-01-01T00:00:00Z"
    assert mr.registry_fingerprint(a) == mr.registry_fingerprint(b)


def test_der_fingerabdruck_bemerkt_eine_stufenaenderung(tmp_path):
    a = _registry(tmp_path, _eintrag(tmp_path))
    b = _registry(tmp_path, _eintrag(tmp_path, stage=mr.STAGE_SHADOW))
    assert mr.registry_fingerprint(a) != mr.registry_fingerprint(b)


def test_das_artefakt_ist_zweimal_identisch():
    a = mr.build_artifact()
    b = mr.build_artifact()
    assert a["contract_fingerprint"] == b["contract_fingerprint"]
    assert a["fingerprint_excludes"] == ["created_at", "git_commit"]


def test_das_artefakt_sagt_dass_c11_nichts_neu_aktiviert_hat():
    """
    C11 hat kein Modell freigegeben und keines neu aktiviert.

    Der Bestandsschutz, den C11 verzeichnet hatte, wurde von V2-C12
    aufgeloest - das war seine Aufgabe. Diese Aussage haengt deshalb
    nicht mehr am Registryzustand, sondern an dem, was C11 getan hat:
    nichts freigegeben.
    """
    a = mr.build_artifact()
    assert a["activated_anything"] is False
    assert a["overwrote_bundle"] is False
    assert a["release_gate"]["status"] == "implemented_not_exercised"


def test_genau_ein_modell_traegt_eine_regulaere_freigabe():
    """
    GEAENDERT IN V2-C17, und die Aenderung ist das Ergebnis.

    Bis C16 hatte kein Modell je ein Gate bestanden, und dieser Test
    hielt genau das fest. Seit C17 ist das freigegebene C16-Modell
    aktiv. Die Zusicherung wandert deshalb dorthin, wo sie jetzt
    scharf ist: GENAU EINES traegt eine Freigabe, und zwar das aktive,
    und jede Freigabe ist an ihren Eintrag gebunden.

    Ein zweites freigegebenes Modell waere der gefaehrliche Fall.

    GEAENDERT IN V2-C22: Seit der zweiten regulaeren Freigabe gibt es
    zwei Modellgenerationen. Der Freigabeweg setzt das bisher aktive
    Modell auf `rollback` und traegt es als Rueckfallziel ein; es behaelt
    seine Freigabe, weil ein Rollback genau dieses Modell wieder aktiv
    setzen muss. Die Stufe `rollback` bestimmt keine Nutzerantwort
    (STAGES_AFFECTING_OUTPUT). Die scharfe Zusicherung lautet deshalb:
    GENAU EIN aktives Modell mit gueltiger Freigabe, und jede weitere
    Freigabe gehoert ausschliesslich dem eingetragenen Rueckfallziel.
    """
    from tests import live_registry_state as live

    doc = mr.load_registry()
    modelle = doc.get("models") or []
    aktiv = [e for e in modelle if e["stage"] == mr.STAGE_ACTIVE]
    assert len(aktiv) == 1, [e["model_id"] for e in aktiv]
    freigegeben = aktiv[0]
    assert freigegeben["model_id"] == live.ACTIVE_ID
    assert freigegeben["evaluation_status"] == mr.EVALUATION_ACCEPTED

    gueltig, warum = mr.verify_approval(freigegeben,
                                        freigegeben["approval"],
                                        mr.STAGE_ACTIVE)
    assert gueltig, warum
    assert mr.STAGES_AFFECTING_OUTPUT == (mr.STAGE_ACTIVE,)

    for eintrag in modelle:
        if eintrag["model_id"] == freigegeben["model_id"]:
            continue
        if eintrag.get("approval"):
            # Nur das Rueckfallziel, und seine Freigabe muss tragen.
            assert eintrag["stage"] == mr.STAGE_ROLLBACK
            assert eintrag["model_id"] == doc.get("rollback_target")
            assert eintrag["evaluation_status"] == mr.EVALUATION_ACCEPTED
            ok, grund = mr.verify_approval(eintrag, eintrag["approval"],
                                           mr.STAGE_ACTIVE)
            assert ok, grund
        else:
            assert eintrag.get("evaluation_status") != (
                mr.EVALUATION_ACCEPTED)


def test_das_artefakt_nennt_die_grenze_des_freigabezeichens():
    """
    Ein Artefakt, das eine Sicherheit andeutet, die es nicht gibt,
    waere schlimmer als keines.
    """
    a = mr.build_artifact()
    text = a["release_gate"]["is_not_authentication"].lower()
    assert "versehen" in text
    assert "vorsatz" in text


def test_das_artefakt_enthaelt_keine_geheimnisse_und_keine_pfade():
    roh = json.dumps(mr.build_artifact(), ensure_ascii=False)
    tief = roh.lower()
    for verboten in ("api_key", "apikey", "secret", "token", "password",
                     "bearer"):
        assert verboten not in tief, verboten
    assert "c:\\users" not in tief
    assert "/home/" not in roh


def test_das_artefakt_zaehlt_die_fail_closed_faelle():
    a = mr.build_artifact()
    assert len(a["fail_closed_cases"]) >= 12
    for fall in a["fail_closed_cases"]:
        assert fall["case"] and fall["behaviour"]


def test_die_registry_braucht_kein_netz_und_keine_env():
    import ast

    baum = ast.parse((WURZEL / "src" / "ml" / "model_registry.py"
                      ).read_text(encoding="utf-8"))
    importiert = set()
    for knoten in baum.body:
        if isinstance(knoten, ast.Import):
            for name in knoten.names:
                importiert.add(name.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom) and knoten.module:
            importiert.add(knoten.module.split(".")[0])
    assert not (importiert & {"requests", "urllib", "socket", "httpx",
                              "dotenv"})


# ===========================================================================
# 10  Der echte Projektstand bleibt unberuehrt
# ===========================================================================

def test_c11_hat_kein_modell_neu_freigegeben():
    """
    DIE WICHTIGSTE ZUSICHERUNG DIESES BLOCKS.

    C11 baut den Weg zur Aktivierung. Gegangen wurde er nicht: C9 hat
    keinen angenommenen Kandidaten gefunden, und ohne 'accepted' traegt
    set_stage keine Aktivierung.

    C11 hatte den vorgefundenen Zustand als Bestandsschutz verzeichnet,
    damit kein laufendes Feature stillschweigend ausgeht. V2-C12 hat
    ihn dann objektiv aufgeloest; welcher Zustand daraus wurde, prueft
    test_c12_final_evaluation.py.

    Hier bleibt zu pruefen, dass die Aktivierung weiterhin 'accepted'
    verlangt und dass der Bestandsschutz nicht wieder auftaucht.
    """
    assert mr.EVALUATION_GRANDFATHERED not in mr.EVALUATION_ALLOWING_ACTIVE[:1]
    assert mr.EVALUATION_ACCEPTED in mr.EVALUATION_ALLOWING_ACTIVE

    for eintrag in mr.load_registry().get("models") or []:
        assert (eintrag.get("evaluation_status")
                != mr.EVALUATION_GRANDFATHERED), (
            "Der Bestandsschutz war ein Uebergang, kein Dauerzustand")


def test_der_bestandsschutz_traegt_keine_neue_aktivierung(tmp_path):
    """
    Er beschreibt einen vorgefundenen Zustand. Ein Modell, das NACH
    C11 aktiv werden will, braucht 'accepted' - set_stage vergibt den
    Bestandsschutz nicht.
    """
    eintrag = _eintrag(tmp_path, stage=mr.STAGE_SHADOW,
                       evaluation=mr.EVALUATION_GRANDFATHERED,
                       grandfathered=True,
                       grandfathered_reason="x" * 40)
    doc = _registry(tmp_path, eintrag)
    freigabe = mr.build_approval(eintrag, mr.STAGE_ACTIVE,
                                 "Versuch, den Bestandsschutz zu nutzen")
    with pytest.raises(mr.RegistryError, match="ausschliesslich"):
        mr.set_stage(doc, "clm-test", mr.STAGE_ACTIVE, freigabe)


def test_bestandsschutz_ohne_kennzeichnung_wird_abgelehnt(tmp_path):
    """
    Ohne grandfathered=True und ohne Begruendung waere der Status ein
    bequemer Weg an jedem Gate vorbei.
    """
    eintrag = _eintrag(tmp_path, stage=mr.STAGE_ACTIVE,
                       evaluation=mr.EVALUATION_GRANDFATHERED)
    freigabe = mr.build_approval(eintrag, mr.STAGE_ACTIVE,
                                 "Testfreigabe fuer den Bestandsschutz")
    eintrag["approval"] = freigabe
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("grandfathered=True" in b for b in befunde), befunde

    eintrag["grandfathered"] = True
    eintrag["grandfathered_reason"] = "zu kurz"
    befunde = mr.validate_registry(_registry(tmp_path, eintrag),
                                   str(tmp_path))
    assert any("nachvollziehbare Begruendung" in b for b in befunde)


def test_die_echte_registry_ist_gueltig():
    doc = mr.load_registry()
    assert mr.validate_registry(doc) == []


def test_nur_das_aktive_modell_traegt_den_status_accepted():
    """
    GEAENDERT IN V2-C17.

    'accepted' heisst: alle Gates wurden bestanden. Genau ein Modell
    hat das geschafft, und nur dieses darf den Status tragen. Ein
    abgelehntes Modell behaelt sein Urteil - es wird nicht
    nachtraeglich umetikettiert.

    GEAENDERT IN V2-C22: Zwei Modelle haben ihre Gates bestanden. Den
    Status tragen das aktive Modell und das eingetragene Rueckfallziel,
    kein drittes; das Rueckfallziel steht auf `rollback` und bestimmt
    keine Nutzerantwort.
    """
    doc = mr.load_registry()
    modelle = doc.get("models") or []
    assert modelle, "das echte Bundle sollte registriert sein"

    akzeptiert = [e for e in modelle
                  if e["evaluation_status"] == mr.EVALUATION_ACCEPTED]
    aktiv = [e for e in akzeptiert if e["stage"] == mr.STAGE_ACTIVE]
    assert len(aktiv) == 1
    rest = [e for e in akzeptiert if e["stage"] != mr.STAGE_ACTIVE]
    assert len(rest) <= 1
    for eintrag in rest:
        assert eintrag["stage"] == mr.STAGE_ROLLBACK
        assert eintrag["model_id"] == doc.get("rollback_target")

    abgelehnt = [e for e in modelle
                 if e["evaluation_status"] == "rejected"]
    for eintrag in abgelehnt:
        assert eintrag["stage"] != mr.STAGE_ACTIVE, (
            "ein abgelehntes Modell darf nie aktiv sein")


def test_das_aktive_modell_wurde_nicht_veraendert():
    """
    C11 hat das Bundle nicht angefasst. Der Hash in der Registry ist
    der der vorgefundenen Datei.
    """
    doc = mr.load_registry()
    for eintrag in doc.get("models") or []:
        pfad = WURZEL / eintrag["bundle_path"]
        assert pfad.is_file()
        assert mr.bundle_sha256(str(pfad)) == eintrag["bundle_sha256"]


def test_die_echte_registry_bindet_c9_und_c10():
    doc = mr.load_registry()
    c9 = json.loads((WURZEL / "data" / "ml"
                     / "c9_early_v2_manifest_2023-2025.json"
                     ).read_text(encoding="utf-8"))
    c10 = json.loads((WURZEL / "data" / "ml"
                      / "c10_prediction_cutoff_contract_2023-2025.json"
                      ).read_text(encoding="utf-8"))
    for eintrag in doc.get("models") or []:
        assert (eintrag["c9_manifest_fingerprint"]
                == c9["manifest_fingerprint"])
        assert (eintrag["c10_contract_fingerprint"]
                == c10["contract_fingerprint"])


def test_die_echte_registry_traegt_keine_absoluten_pfade():
    roh = (WURZEL / "data" / "ml" / "model_registry.json").read_text(
        encoding="utf-8")
    assert "C:\\" not in roh and "c:\\" not in roh
    assert "/home/" not in roh and "/Users/" not in roh


def test_kein_trainingspfad_beruehrt_die_registry():
    """
    Ein normaler Trainingslauf darf die Registry niemals nebenbei
    umschalten. Sie liegt deshalb auf einem eigenen, ausdruecklichen
    CLI-Weg und wird von keinem Trainings- oder Auswertungsmodul
    importiert.
    """
    for name in ("persist.py", "cl_evaluate.py", "evaluate.py",
                 "model.py", "dataset.py", "cl_dataset.py",
                 "cl_ablation.py", "c8_ablation.py"):
        pfad = WURZEL / "src" / "ml" / name
        if pfad.exists():
            assert "model_registry" not in pfad.read_text(
                encoding="utf-8"), name


def test_nur_der_registry_befehl_schreibt():
    """
    write_registry wird ausschliesslich aus dem --registry-Zweig
    gerufen. Ein zweiter Schreibweg waere eine zweite Wahrheitsquelle.
    """
    import ast

    quelle = (WURZEL / "run_ml.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    rufer = []
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.FunctionDef):
            continue
        if "write_registry" in ast.unparse(knoten):
            rufer.append(knoten.name)

    # Genau zwei ausdrueckliche Wege duerfen schreiben: die
    # Registry-CLI und die C12-Entscheidung. Beide verlangen --apply,
    # beide sind eigene Aufgaben. Ein dritter Rufer waere ein
    # zusaetzlicher Schreibweg und damit eine zweite Wahrheitsquelle.
    assert sorted(rufer) == ["_evaluate_c12", "_registry_cli"], rufer


def test_die_veraendernden_aktionen_verlangen_apply():
    """
    Ohne --apply bleibt es beim Trockenlauf. Eine gefaehrliche Aktion
    soll ein zusaetzliches, ausdrueckliches Argument kosten.
    """
    import ast

    baum = ast.parse((WURZEL / "run_ml.py").read_text(encoding="utf-8"))
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.FunctionDef)
                and knoten.name == "_registry_cli"):
            code = ast.unparse(knoten)
            assert "if not args.apply:" in code
            assert "TROCKENLAUF" in code
            # write_registry steht NACH der apply-Pruefung.
            assert code.index("if not args.apply:") < code.index(
                "mreg.write_registry")
            break
    else:                                                # pragma: no cover
        pytest.fail("_registry_cli nicht gefunden")
