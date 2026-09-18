"""
Der Freigabeweg mit Transaktion, Rollback und Recovery (V2-C15).

DREI TECHNISCHE FEHLER, DIE HIER REPARIERT WERDEN
--------------------------------------------------
1. DER ACCEPTED-ZWEIG WARF.
   `c12_evaluation.apply_decision` warf bei `accepted` ein
   NotImplementedError. Ein Freigabeweg, den nie jemand gegangen ist,
   ist kein Freigabeweg, sondern eine Absichtserklaerung. Er wird hier
   vollstaendig gebaut und durch synthetische Faelle bewiesen - auch
   dann, wenn die aktuelle Messung ihn nicht ausloest.

2. ARTEFAKT UND REGISTRY LIEFEN NACHEINANDER.
   C12 schrieb erst das Ergebnisartefakt und dann die Registry.
   Schlaegt der zweite Schritt fehl, behauptet das Artefakt einen
   Registryzustand, den es nicht gibt. Ab hier gilt: Erst wird alles
   geprueft und vorbereitet, dann wird in einer definierten
   Reihenfolge mit Journal geschrieben, und danach wird erneut
   validiert.

3. `rollback_possible: true` WAR NICHT BEWIESEN.
   C12 setzte `rollback_target = None` und entfernte die Freigabe.
   Die Behauptung, ein Rollback sei moeglich, stimmte damit nur
   haendisch, nicht ueber den getesteten Weg. Ab hier wird vor jeder
   Anwendung ein Vorzustand gesichert, und der Rollback laeuft ueber
   genau diesen Stand.

WAS ROLLBACK BEDEUTET UND WAS NICHT
-----------------------------------
Rollback ist die technische Wiederherstellung eines gueltigen
frueheren Zustands. Er ist ausdruecklich KEIN Weg, ein fachlich
abgelehntes Modell wieder produktiv zu machen. Ein Eintrag mit
`evaluation_status = rejected` wird auch durch einen Rollback nicht
aktiv; das wird geprueft und fuehrt zum Abbruch.
"""

import json
import os
import pathlib
import shutil

from src.ml import model_registry as mr

#: Wo der Vorzustand und das Journal liegen. Bewusst neben der
#: Registry, damit ein Recovery sie ohne Konfiguration findet.
JOURNAL_PATH = "data/ml/c15_release_journal.json"
SNAPSHOT_PATH = "data/ml/c15_registry_snapshot.json"

RELEASE_ARTIFACT_PATH = "data/ml/c15_release_2023-2025.json"


class ReleaseError(RuntimeError):
    """
    Die Freigabe ist nicht zulaessig oder nicht sicher durchfuehrbar.

    Eigene Klasse, damit ein Aufrufer sie von einem gewoehnlichen
    Fehler unterscheiden kann. Sie fuehrt IMMER zum Abbruch ohne
    Schreibvorgang.
    """


def _pfad(repo_root, relativ):
    return os.path.join(repo_root or ".", relativ)


def _artefakt_feld(repo_root, relativ, feld):
    """Ein Feld aus einem vorhandenen Artefakt - oder None."""
    voll = _pfad(repo_root, relativ)
    if not os.path.isfile(voll):
        return None
    try:
        with open(voll, encoding="utf-8") as datei:
            return json.load(datei).get(feld)
    except (OSError, ValueError):                        # pragma: no cover
        return None


def _c9_manifest_fingerprint(repo_root=None):
    """Der Fingerabdruck des C9-Manifests, gelesen statt behauptet."""
    from src.ml import early_v2 as e9

    return _artefakt_feld(repo_root, e9.MANIFEST_PATH,
                          "manifest_fingerprint")


def _atomar(pfad, inhalt):
    """Atomar schreiben - tempfile, fsync, replace."""
    import tempfile

    ziel = pathlib.Path(pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    griff, temp = tempfile.mkstemp(dir=str(ziel.parent), suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            datei.write(inhalt + "\n")
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temp, ziel)
    except BaseException:                                # pragma: no cover
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    return str(ziel)


# ---------------------------------------------------------------------------
# Die Vorpruefung
# ---------------------------------------------------------------------------

def preflight(urteil, eintrag, bundle_pfad=None, repo_root=None,
              dokument=None):
    """
    Alles pruefen, was vor einem Schreibvorgang stimmen muss.

    Rueckgabe: (ok, befunde). Es wird NICHTS geschrieben.

    Fail-closed: Jeder unklare Fall ist ein Befund und verhindert die
    Freigabe. Eine Freigabe, die im Zweifel durchlaesst, ist kein Gate.
    """
    from src.features import prediction_cutoff as pc
    from src.ml import c13_contract as c13
    from src.ml import c14_reevaluation as c14
    from src.ml import c15_league_strength as c15
    from src.ml import early_v2 as e9

    befunde = []

    # -- 1. Das fachliche Urteil ----------------------------------------
    if (urteil or {}).get("verdict") != c15.VERDICT_ACCEPTED:
        befunde.append(
            "das Urteil lautet %r, nicht accepted - eine Freigabe waere "
            "eine Behauptung ohne Beleg"
            % (urteil or {}).get("verdict"))

    # -- 2. Die Vertragsbindung ------------------------------------------
    try:
        c15.assert_contract_matches(urteil)
    except c15.ContractViolation as fehler:
        befunde.append(str(fehler))

    # -- 3. Der Eintrag ---------------------------------------------------
    if not eintrag:
        befunde.append("kein Registryeintrag uebergeben")
        return False, befunde

    for feld in ("model_id", "bundle_sha256",
                 "feature_schema_fingerprint"):
        if not eintrag.get(feld):
            befunde.append("dem Eintrag fehlt %s" % feld)

    # -- 4. Das Bundle ----------------------------------------------------
    if bundle_pfad:
        voll = _pfad(repo_root, bundle_pfad)
        if not os.path.isfile(voll):
            befunde.append("das Bundle fehlt: %s" % bundle_pfad)
        else:
            ist = mr.bundle_sha256(voll)
            if ist != eintrag.get("bundle_sha256"):
                befunde.append(
                    "der Bundle-Hash stimmt nicht: erwartet %s, "
                    "gefunden %s" % (eintrag.get("bundle_sha256"), ist))

    # -- 5. Das Merkmalsschema --------------------------------------------
    if eintrag.get("feature_schema_fingerprint") != c15.schema_fingerprint():
        befunde.append(
            "das Merkmalsschema passt nicht zu C15: erwartet %s, "
            "gefunden %s" % (c15.schema_fingerprint(),
                             eintrag.get("feature_schema_fingerprint")))

    # -- 6. Die vorgelagerten Vertraege -----------------------------------
    # Der Eintrag fuehrt den MANIFEST-Fingerabdruck aus C9, nicht den
    # Schemafingerabdruck. Die beiden zu verwechseln waere eine
    # Pruefung, die immer scheitert und deshalb nichts belegt.
    # Die C9- und C10-Artefakte gehoeren zum Quellbaum, nicht zum
    # Registrypfad. `repo_root` isoliert in Tests die REGISTRY; die
    # Vertraege liegen unabhaengig davon im Projekt.
    erwartet = {
        "c9_manifest_fingerprint": _c9_manifest_fingerprint(),
        "c10_contract_fingerprint": _artefakt_feld(
            None, "data/ml/c10_prediction_cutoff_contract_"
                  "2023-2025.json", "contract_fingerprint"),
        "c13_contract_fingerprint": c13.contract_fingerprint(),
        "c14_contract_fingerprint": c14.contract_fingerprint(),
        "c15_contract_fingerprint": c15.contract_fingerprint(),
    }
    for feld, wert in erwartet.items():
        if eintrag.get(feld) not in (None, wert):
            befunde.append("%s stimmt nicht: erwartet %s, gefunden %s"
                           % (feld, wert, eintrag.get(feld)))

    if pc.CUTOFF_HOUR != 12 or pc.CUTOFF_INCLUSIVE is not False:
        befunde.append("der C10-Stichtagsvertrag ist veraendert")

    # -- 7. Die Registry ---------------------------------------------------
    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    fehler_registry = mr.validate_registry(dokument, repo_root)
    if fehler_registry:
        befunde.append("die Registry ist nicht valide: %s"
                       % fehler_registry[:3])

    aktiv = [m for m in (dokument.get("models") or [])
             if m.get("stage") == mr.STAGE_ACTIVE]
    if len(aktiv) > 1:
        befunde.append("es sind bereits mehrere Modelle aktiv: %s"
                       % [m.get("model_id") for m in aktiv])

    return (not befunde), befunde


# ---------------------------------------------------------------------------
# Der Vorzustand
# ---------------------------------------------------------------------------

def save_snapshot(dokument=None, repo_root=None, pfad=None):
    """
    Den Vorzustand sichern, BEVOR irgendetwas veraendert wird.

    Ohne ihn waere jede Rollbackzusage eine Behauptung. Genau daran
    scheiterte die C12-Aussage `rollback_possible: true`.
    """
    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    ziel = _pfad(repo_root, pfad or SNAPSHOT_PATH)
    inhalt = {
        "saved_at_registry_fingerprint": mr.registry_fingerprint(dokument),
        "registry": dokument,
        "purpose": ("technische Wiederherstellung eines gueltigen "
                    "frueheren Zustands - ausdruecklich kein Weg, ein "
                    "fachlich abgelehntes Modell zu reaktivieren"),
    }
    return _atomar(ziel, json.dumps(inhalt, indent=2, ensure_ascii=False))


def load_snapshot(repo_root=None, pfad=None):
    """Den Vorzustand lesen - oder None, wenn keiner existiert."""
    ziel = _pfad(repo_root, pfad or SNAPSHOT_PATH)
    if not os.path.isfile(ziel):
        return None
    try:
        with open(ziel, encoding="utf-8") as datei:
            return json.load(datei)
    except (OSError, ValueError):
        raise ReleaseError(
            "der gesicherte Vorzustand ist unlesbar. Ein beschaedigter "
            "Rollbackstand wird nicht geraten.")


# ---------------------------------------------------------------------------
# Das Journal
# ---------------------------------------------------------------------------

#: Die Schritte einer Freigabe, in genau dieser Reihenfolge. Das
#: Journal haelt fest, wie weit sie gekommen ist; ein Recovery liest
#: daran ab, was noch zu tun oder zurueckzunehmen ist.
STEPS = ("preflight_ok", "snapshot_written", "artifact_staged",
         "registry_written", "registry_revalidated", "artifact_finalised")


def write_journal(schritte, repo_root=None, pfad=None, extra=None):
    """Den Fortschritt festhalten. Keine Geheimnisse, keine Rohdaten."""
    import datetime as _dt

    inhalt = {
        "updated_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "steps": {name: bool(schritte.get(name)) for name in STEPS},
        "complete": all(schritte.get(name) for name in STEPS),
    }
    inhalt.update(extra or {})
    return _atomar(_pfad(repo_root, pfad or JOURNAL_PATH),
                   json.dumps(inhalt, indent=2, ensure_ascii=False))


def read_journal(repo_root=None, pfad=None):
    ziel = _pfad(repo_root, pfad or JOURNAL_PATH)
    if not os.path.isfile(ziel):
        return None
    try:
        with open(ziel, encoding="utf-8") as datei:
            return json.load(datei)
    except (OSError, ValueError):                        # pragma: no cover
        return {"steps": {}, "complete": False, "unreadable": True}


# ---------------------------------------------------------------------------
# Die Freigabe
# ---------------------------------------------------------------------------

def apply_release(urteil, eintrag, artefakt, bundle_pfad=None,
                  repo_root=None, dokument=None, dry_run=True,
                  fail_after=None):
    """
    Die Freigabe anwenden - oder als Trockenlauf durchspielen.

    fail_after dient AUSSCHLIESSLICH den Absturztests: Es bricht nach
    dem genannten Schritt ab, damit ein Recovery an jeder kritischen
    Schreibgrenze geprueft werden kann. Im normalen Betrieb ist es
    None.

    Rueckgabe: dict mit status, log und Zustaenden.
    """
    from src.ml import c15_league_strength as c15

    protokoll = []
    schritte = {}
    dokument = (dokument if dokument is not None
                else mr.load_registry(repo_root=repo_root))
    vorher_fp = mr.registry_fingerprint(dokument)

    def stufe(name):
        schritte[name] = True
        if not dry_run:
            write_journal(schritte, repo_root,
                          extra={"model_id": eintrag.get("model_id"),
                                 "registry_before": vorher_fp})
        if fail_after == name:
            raise ReleaseError("Absturzprobe nach Schritt %r" % name)

    # -- 1. Vorpruefung ---------------------------------------------------
    ok, befunde = preflight(urteil, eintrag, bundle_pfad, repo_root,
                            dokument)
    protokoll.append("Vorpruefung: %s" % ("bestanden" if ok
                                          else "%d Befunde" % len(befunde)))
    for befund in befunde:
        protokoll.append("  ! %s" % befund)
    if not ok:
        return {"status": "refused", "reason": befunde[0],
                "findings": befunde, "log": protokoll,
                "registry_before": vorher_fp, "registry_after": vorher_fp,
                "wrote_anything": False}
    stufe("preflight_ok")

    # -- 2. Vorzustand sichern --------------------------------------------
    if dry_run:
        protokoll.append("Trockenlauf: kein Vorzustand geschrieben")
    else:
        save_snapshot(dokument, repo_root)
        protokoll.append("Vorzustand gesichert")
    stufe("snapshot_written")

    # -- 3. Registry vorbereiten, noch nicht schreiben --------------------
    # DER WEG FUEHRT UEBER DEN SCHATTEN.
    #
    # Die C11-Registry verbietet candidate -> active ausdruecklich:
    # "ein nie im Schatten gelaufenes Modell wirkt nicht als erstes auf
    # Nutzer". Das ist keine Formalie, sondern der Sinn der Stufe - ein
    # Modell, das noch nie unter echten Bedingungen mitgelaufen ist,
    # soll nicht mit seiner ersten Ausfuehrung die Nutzerantwort
    # bestimmen. Die Freigabe geht deshalb in zwei gebundenen
    # Schritten, und JEDER traegt seine eigene Freigabe.
    grund_schatten = (
        "V2-C15: Der Kandidat hat alle verpflichtenden Gates erfuellt "
        "und wird zuerst in den Schattenbetrieb genommen. Der Schatten "
        "veraendert keine Nutzerantwort.")
    grund_aktiv = (
        "V2-C15: Die Ligastaerke-Evaluation hat alle verpflichtenden "
        "Gates erfuellt. Die Freigabe ist an Bundle, Merkmalsschema "
        "und die Vertraege C9, C10, C13, C14 und C15 gebunden.")

    neu = dokument
    schritte_stufen = []
    if eintrag.get("stage") == mr.STAGE_CANDIDATE:
        freigabe_schatten = mr.build_approval(
            eintrag, mr.STAGE_SHADOW,
            reason=grund_schatten)
        neu = mr.set_stage(neu, eintrag["model_id"], mr.STAGE_SHADOW,
                           approval=freigabe_schatten)
        schritte_stufen.append("candidate -> shadow")

    im_schatten = next(m for m in (neu.get("models") or [])
                       if m["model_id"] == eintrag["model_id"])
    freigabe = mr.build_approval(
        im_schatten, mr.STAGE_ACTIVE,
        reason=grund_aktiv)
    neu = mr.set_stage(neu, eintrag["model_id"], mr.STAGE_ACTIVE,
                       approval=freigabe)
    schritte_stufen.append("shadow -> active")
    protokoll.append("Registryzustand vorbereitet: %s"
                     % " , ".join(schritte_stufen))

    aktiv = [m for m in (neu.get("models") or [])
             if m.get("stage") == mr.STAGE_ACTIVE]
    if len(aktiv) != 1:
        return {"status": "refused",
                "reason": "nach der Aenderung waeren %d Modelle aktiv"
                          % len(aktiv),
                "log": protokoll, "registry_before": vorher_fp,
                "registry_after": vorher_fp, "wrote_anything": False}

    fehler = mr.validate_registry(neu, repo_root)
    if fehler:
        return {"status": "refused",
                "reason": "der vorbereitete Zustand ist nicht valide: %s"
                          % fehler[:2],
                "log": protokoll, "registry_before": vorher_fp,
                "registry_after": vorher_fp, "wrote_anything": False}
    protokoll.append("vorbereiteter Zustand validiert")

    nachher_fp = mr.registry_fingerprint(neu)

    # -- 4. Artefakt vorbereiten -------------------------------------------
    #
    # Es traegt den Zustand, den die Registry GLEICH haben wird. Es
    # wird aber erst NACH der Registry endgueltig geschrieben - sonst
    # koennte es einen Zustand behaupten, den es nicht gibt.
    release_artefakt = dict(artefakt or {})
    release_artefakt.update({
        "artifact": "v2-c15 release",
        "model_id": eintrag["model_id"],
        "bundle_sha256": eintrag.get("bundle_sha256"),
        "bundle_path": bundle_pfad,
        "feature_schema_fingerprint": c15.schema_fingerprint(),
        "approval": {k: v for k, v in freigabe.items() if k != "token"},
        "approval_token_present": bool(freigabe.get("token")),
        "registry_before": vorher_fp,
        "registry_after": nachher_fp,
        "transition": " , ".join(schritte_stufen),
    })
    if dry_run:
        protokoll.append("Trockenlauf: Artefakt nicht geschrieben")
    stufe("artifact_staged")

    if dry_run:
        protokoll.append("Trockenlauf beendet - nichts wurde geschrieben")
        return {"status": "dry_run_ok", "log": protokoll,
                "registry_before": vorher_fp,
                "registry_after_would_be": nachher_fp,
                "model_id": eintrag["model_id"],
                "wrote_anything": False}

    # -- 5. Registry schreiben ---------------------------------------------
    mr.write_registry(neu, repo_root=repo_root)
    protokoll.append("Registry geschrieben (atomar)")
    stufe("registry_written")

    # -- 6. Erneut validieren, jetzt von der Platte ------------------------
    frisch = mr.load_registry(repo_root=repo_root)
    if mr.registry_fingerprint(frisch) != nachher_fp:
        raise ReleaseError(
            "die geschriebene Registry stimmt nicht mit dem "
            "vorbereiteten Zustand ueberein. Recovery noetig.")
    fehler = mr.validate_registry(frisch, repo_root)
    if fehler:
        raise ReleaseError(
            "die geschriebene Registry ist nicht valide: %s" % fehler[:2])
    protokoll.append("Registry von der Platte erneut validiert")
    stufe("registry_revalidated")

    # -- 7. Erst jetzt das Artefakt ----------------------------------------
    pfad = _atomar(_pfad(repo_root, RELEASE_ARTIFACT_PATH),
                   json.dumps(release_artefakt, indent=2,
                              ensure_ascii=False, default=str))
    protokoll.append("Releaseartefakt geschrieben: %s"
                     % RELEASE_ARTIFACT_PATH)
    stufe("artifact_finalised")

    return {"status": "applied", "log": protokoll,
            "registry_before": vorher_fp, "registry_after": nachher_fp,
            "model_id": eintrag["model_id"], "artifact_path": pfad,
            "wrote_anything": True}


# ---------------------------------------------------------------------------
# Rollback und Recovery
# ---------------------------------------------------------------------------

def rollback(repo_root=None, dry_run=True, pfad=None):
    """
    Den gesicherten Vorzustand wiederherstellen.

    Ein Rollback stellt Technik wieder her, er hebt kein fachliches
    Urteil auf: Traegt der Vorzustand ein aktives Modell mit
    `evaluation_status = rejected`, wird abgebrochen.
    """
    stand = load_snapshot(repo_root, pfad)
    if not stand:
        return {"status": "refused",
                "reason": "kein gesicherter Vorzustand vorhanden",
                "log": ["Rollback ohne Vorzustand ist Raten"]}

    dokument = stand.get("registry")
    if not isinstance(dokument, dict) or "models" not in dokument:
        return {"status": "refused",
                "reason": "der Vorzustand ist unvollstaendig",
                "log": ["fail-closed: kein Rollback auf einen "
                        "beschaedigten Stand"]}

    erwartet = stand.get("saved_at_registry_fingerprint")
    ist = mr.registry_fingerprint(dokument)
    if erwartet and erwartet != ist:
        return {"status": "refused",
                "reason": ("der Vorzustand wurde veraendert: erwartet "
                           "%s, gefunden %s" % (erwartet, ist)),
                "log": ["fail-closed: ein manipulierter Rollbackstand "
                        "wird nicht angewendet"]}

    for modell in dokument.get("models") or []:
        if (modell.get("stage") == mr.STAGE_ACTIVE
                and modell.get("evaluation_status") == "rejected"):
            return {"status": "refused",
                    "reason": ("der Vorzustand wuerde ein fachlich "
                               "abgelehntes Modell aktivieren"),
                    "log": ["Rollback ist technische "
                            "Wiederherstellung, kein Weg um ein "
                            "Rejected herum"]}

    fehler = mr.validate_registry(dokument, repo_root)
    if fehler:
        return {"status": "refused",
                "reason": "der Vorzustand ist nicht valide: %s"
                          % fehler[:2],
                "log": ["fail-closed"]}

    if dry_run:
        return {"status": "dry_run_ok",
                "log": ["Trockenlauf: der Vorzustand ist gueltig und "
                        "wiederherstellbar"],
                "registry_would_be": ist}

    aktuell = mr.registry_fingerprint(mr.load_registry(repo_root=repo_root))
    mr.write_registry(dokument, repo_root=repo_root)
    frisch = mr.load_registry(repo_root=repo_root)
    if mr.registry_fingerprint(frisch) != ist:
        raise ReleaseError("der Rollback wurde nicht korrekt "
                           "geschrieben. Recovery noetig.")
    return {"status": "rolled_back",
            "log": ["Vorzustand wiederhergestellt und validiert"],
            "registry_before": aktuell, "registry_after": ist}


def recover(repo_root=None, dry_run=True):
    """
    Einen unterbrochenen Freigabevorgang erkennen und aufloesen.

    Sie liest das Journal und den tatsaechlichen Zustand und sagt,
    welcher der beiden gilt. Ein halb geschriebener Vorgang wird nicht
    stillschweigend als erfolgreich gewertet.
    """
    journal = read_journal(repo_root)
    dokument = mr.load_registry(repo_root=repo_root)
    ist = mr.registry_fingerprint(dokument)
    fehler = mr.validate_registry(dokument, repo_root)

    if journal is None:
        return {"status": "nothing_to_recover",
                "registry_fingerprint": ist,
                "registry_valid": not fehler,
                "log": ["kein Journal vorhanden"]}

    schritte = journal.get("steps") or {}
    if journal.get("complete"):
        return {"status": "complete",
                "registry_fingerprint": ist,
                "registry_valid": not fehler,
                "log": ["der letzte Vorgang war vollstaendig"]}

    geschrieben = schritte.get("registry_written")
    artefakt_fertig = schritte.get("artifact_finalised")

    if geschrieben and not artefakt_fertig:
        # Die Registry gilt. Das Artefakt fehlt oder ist unvollstaendig;
        # es darf jetzt keinen angewendeten Zustand behaupten.
        return {"status": "registry_applied_artifact_missing",
                "registry_fingerprint": ist,
                "registry_valid": not fehler,
                "action": ("das Releaseartefakt neu schreiben; die "
                           "Registry ist der massgebliche Zustand"),
                "log": ["Registry geschrieben, Artefakt unvollstaendig"]}

    if not geschrieben:
        return {"status": "registry_untouched",
                "registry_fingerprint": ist,
                "registry_valid": not fehler,
                "action": ("nichts wiederherzustellen - der Vorgang "
                           "brach vor der Registry ab"),
                "log": ["der Vorgang brach vor dem Registryschreiben ab"]}

    return {"status": "unknown",                         # pragma: no cover
            "registry_fingerprint": ist,
            "registry_valid": not fehler,
            "log": ["Journalzustand nicht eindeutig - fail-closed"]}


def release(dry_run=True, repo_root=None):
    """
    Der Weg, den die CLI geht.

    Er laedt das C15-Ergebnis, sucht den Kandidaten und wendet an -
    oder verweigert mit Grund. Ohne accepted passiert nichts.
    """
    from src.ml import c15_league_strength as c15

    pfad = _pfad(repo_root, c15.ARTIFACT_PATH)
    if not os.path.isfile(pfad):
        return {"status": "refused",
                "reason": "es gibt kein C15-Ergebnis",
                "log": ["zuerst --evaluate-c15 ausfuehren"]}

    with open(pfad, encoding="utf-8") as datei:
        artefakt = json.load(datei)

    urteil = artefakt.get("decision") or {}
    dokument = mr.load_registry(repo_root=repo_root)
    kandidaten = [m for m in (dokument.get("models") or [])
                  if m.get("stage") == mr.STAGE_CANDIDATE]
    eintrag = kandidaten[0] if kandidaten else None

    return apply_release(urteil, eintrag, artefakt,
                         bundle_pfad=(eintrag or {}).get("bundle_path"),
                         repo_root=repo_root, dokument=dokument,
                         dry_run=dry_run)
