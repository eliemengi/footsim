"""
Die Modellregistry (V2-C11).

DIE REGEL
---------
Kein Modell wird produktiv, weil eine Datei entstanden ist. Es wird
produktiv, weil jemand es ausdruecklich freigegeben hat und die
Freigabe zu genau diesem Bundle passt.

WAS VORHER FEHLTE
-----------------
Der Ladeweg endete bei einem festen Pfad:

    inference.DEFAULT_MODEL_PATH
        data/ml/models/cl_correction_model_v1.json

Wer diese Datei ersetzt, ersetzt das Modell. Das Bundle traegt zwar
einen eigenen Integritaetshash, aber der deckt nur den models-Block und
liegt IM Bundle; sein eigener Kommentar sagt es:

    "schuetzt vor Beschaedigung und vertauschten Dateien, nicht gegen
     einen Angreifer mit Schreibrecht"

Dazu kam: STAGES_ALLOWED_ACTIVE enthaelt "experimental", und das
vorhandene Bundle steht auf genau dieser Stufe. Es war eine
Umgebungsvariable von der Wirkung entfernt, ohne dass irgendwo
festgehalten war, DASS es wirken soll.

Die Registry schliesst die Luecke von aussen: Sie nennt den erwarteten
Bundle-Hash, die erwarteten Vertragsfingerabdruecke aus C9 und C10, und
sie verlangt fuer den Schritt nach active eine Freigabe, die an genau
diese Werte gebunden ist.

WAS DIESE DATEI NICHT IST
-------------------------
Keine Zugriffskontrolle. Wer die CLI ausfuehren kann, kann eine
Freigabe erzeugen - das ist Absicht, weil C11 ausdruecklich ohne
Secrets und ohne externe Infrastruktur auskommen soll. Die Freigabe
bindet, sie authentifiziert nicht. Sie verhindert das Versehen (falsches
Bundle, veraendertes Bundle, veralteter Vertrag), nicht den Vorsatz.
Diese Grenze steht auch im Artefakt.

FAIL CLOSED
-----------
Jeder Zweifel endet ohne aktives Modell. Eine fehlende, kaputte oder
widerspruechliche Registry fuehrt nicht zu "dann eben das neueste",
sondern zu keinem Modell - und die Runtime hat dafuer bereits einen
getesteten Baselinepfad.
"""

import hashlib
import json
import os
import tempfile

#: Fassung des Registrydokuments.
REGISTRY_SCHEMA_VERSION = 1

#: Wo die Registry liegt - repo-relativ.
REGISTRY_PATH = "data/ml/model_registry.json"


class RegistryError(RuntimeError):
    """
    Die Registry ist nicht benutzbar.

    Eigene Klasse, damit ein Aufrufer sie von einem gewoehnlichen
    Fehler unterscheiden und gezielt auf die Baseline zurueckfallen
    kann. Sie wird nie stillschweigend behandelt.
    """


# ---------------------------------------------------------------------------
# Zustaende
# ---------------------------------------------------------------------------

#: Registriert, geprueft, ohne jede Wirkung.
STAGE_CANDIDATE = "candidate"

#: Rechnet mit, veraendert aber keine sichtbare Antwort.
STAGE_SHADOW = "shadow"

#: Das eine Modell, das die Nutzerantwort bestimmen darf.
STAGE_ACTIVE = "active"

#: Das zuletzt aktive Modell, aufgehoben als Rueckfallziel.
STAGE_ROLLBACK = "rollback"

STAGES = (STAGE_CANDIDATE, STAGE_SHADOW, STAGE_ACTIVE, STAGE_ROLLBACK)

#: Erlaubte Uebergaenge - ausschliesslich diese.
#:
#: candidate -> active fehlt ABSICHTLICH. Ein Modell, das nie im
#: Schatten gelaufen ist, hat nie gegen die Wirklichkeit gerechnet;
#: seine erste Begegnung mit echten Anfragen waere zugleich seine
#: erste Wirkung auf Nutzer.
ALLOWED_TRANSITIONS = {
    (None, STAGE_CANDIDATE),
    (STAGE_CANDIDATE, STAGE_SHADOW),
    (STAGE_SHADOW, STAGE_ACTIVE),
    (STAGE_SHADOW, STAGE_CANDIDATE),
    (STAGE_ACTIVE, STAGE_ROLLBACK),
    (STAGE_ROLLBACK, STAGE_ACTIVE),
    (STAGE_CANDIDATE, STAGE_CANDIDATE),
    # V2-C12: Ausserbetriebnahme nach abgelehnter Evaluation.
    #
    # rollback waere hier falsch: Es heisst "aufgehoben als
    # Rueckfallziel", also "koennte wieder aktiv werden". Ein Modell,
    # das ein Gate verfehlt hat, soll genau das nicht.
    #
    # shadow waere ebenfalls falsch, wenn der Schattenbetrieb keinen
    # Erkenntniswert mehr hat - dann sammelte man Zahlen zu einer
    # bereits beantworteten Frage.
    (STAGE_ACTIVE, STAGE_CANDIDATE),
    (STAGE_ACTIVE, STAGE_SHADOW),
}

#: Uebergaenge, die ausdruecklich verboten sind - mit Begruendung.
#:
#: Sie stehen benannt da und nicht bloss als "alles Uebrige", damit ein
#: Bericht sagen kann, WAS verhindert wird.
FORBIDDEN_TRANSITIONS = {
    (STAGE_CANDIDATE, STAGE_ACTIVE):
        "ein nie im Schatten gelaufenes Modell wirkt nicht als erstes "
        "auf Nutzer",
    (None, STAGE_ACTIVE):
        "ein frisch registriertes Bundle wird nicht durch Registrierung "
        "aktiv",
    (None, STAGE_SHADOW):
        "auch der Schattenlauf setzt eine vorherige Registrierung voraus",
    (STAGE_ROLLBACK, STAGE_SHADOW):
        "ein Rueckfallziel bleibt aufgehoben, bis es wieder aktiv wird "
        "oder ausdruecklich neu registriert",
}

#: Nur diese Stufen duerfen eine sichtbare Nutzerantwort bestimmen.
STAGES_AFFECTING_OUTPUT = (STAGE_ACTIVE,)

#: Evaluationsentscheidungen, die eine Aktivierung tragen.
#:
#: Die Liste ist bewusst kurz. accepted heisst: Ein Gate wurde
#: bestanden. Alles andere - rejected, inconclusive, not_evaluable,
#: infrastructure_only - ist kein Beleg, und ein fehlender Beleg
#: aktiviert nichts.
EVALUATION_ACCEPTED = "accepted"
EVALUATION_BLOCKING = ("rejected", "inconclusive", "not_evaluable",
                       "infrastructure_only", "pending", "unknown")

#: Der Bestandsschutz fuer das Modell, das vor C11 bereits lief.
#:
#: WARUM ES DIESEN STATUS GIBT
#: Vor der Registry entschied allein die Freigabestufe im Bundle, und
#: STAGES_ALLOWED_ACTIVE enthaelt "experimental". Das vorhandene Bundle
#: steht auf genau dieser Stufe: Ueber approach=ml wirkte es bereits,
#: bevor C11 existierte.
#:
#: Haette die Registry es beim Einschalten auf candidate gesetzt, waere
#: ein laufendes Feature stillschweigend ausgegangen. Die Oberflaeche
#: haette weiter "ML" angezeigt und die Baseline geliefert - genau der
#: Widerspruch, den V2-C0B beseitigt hat. Ein bestehender Test haelt
#: das fest:
#:
#:     test_cl_custom_api.py::test_die_ui_vorauswahl_wirkt_wirklich
#:     "sonst waere die sichtbare Auswahl eine Behauptung"
#:
#: Die Registry verzeichnet deshalb den Zustand, den sie vorfindet.
#: Sie hat ihn nicht hergestellt und sie behauptet nicht, er sei
#: statistisch belegt - der Name sagt genau das.
#:
#: WAS DIESER STATUS NICHT ERLAUBT
#: Er gilt ausschliesslich fuer einen Eintrag, der zusaetzlich
#: grandfathered=True traegt, und er traegt keine NEUE Aktivierung: Ein
#: Modell, das nach C11 aktiv werden will, braucht "accepted". Ein
#: Bundlewechsel entwertet auch hier die Freigabe.
#:
#: Aufzuloesen ist das in einem eigenen Block: Entweder ein Modell
#: besteht ein Gate und wird regulaer freigegeben, oder das Bundle wird
#: ausser Betrieb genommen. Beides ist eine Produktentscheidung, keine
#: Aufgabe von C11.
EVALUATION_GRANDFATHERED = "grandfathered_pre_c11"

#: Was eine Aktivierung ueberhaupt tragen kann.
EVALUATION_ALLOWING_ACTIVE = (EVALUATION_ACCEPTED,
                              EVALUATION_GRANDFATHERED)


# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------

def bundle_sha256(pfad):
    """
    Der Hash der GESAMTEN Bundledatei.

    Nicht der models-Block, den das Bundle selbst hasht: Der liegt im
    Bundle und wandert mit, wenn jemand die Datei austauscht. Dieser
    Hash liegt in der Registry und beschreibt, welche Datei erwartet
    wird.
    """
    h = hashlib.sha256()
    with open(pfad, "rb") as strom:
        for block in iter(lambda: strom.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _kanonisch(wert):
    """Stabiler Text fuer einen Hash - sortiert, ohne Zufallsordnung."""
    return json.dumps(wert, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=repr)


#: Felder, die eine Messung des Augenblicks sind.
#:
#: Sie gehoeren in die Registry, aber nicht in ihren Fingerabdruck.
#: Sonst waere jede Registry nach jedem Schreiben eine andere, und der
#: Vergleich "unveraendert" liesse sich nicht fuehren.
VOLATILE_FIELDS = ("created_at", "updated_at", "registered_at",
                   "approved_at")


def registry_fingerprint(dokument):
    """Ein Hash ueber alles, was ein zweiter Lauf reproduzieren muss."""
    def _saeubern(wert):
        if isinstance(wert, dict):
            return {k: _saeubern(v) for k, v in sorted(wert.items())
                    if k not in VOLATILE_FIELDS}
        if isinstance(wert, list):
            return [_saeubern(v) for v in wert]
        return wert

    return hashlib.sha256(
        _kanonisch(_saeubern(dokument)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Die Freigabe
# ---------------------------------------------------------------------------

#: Genau diese Werte bindet eine Freigabe.
#:
#: Aendert sich einer davon, passt das Freigabezeichen nicht mehr. Das
#: ist der ganze Mechanismus: kein Passwort, kein Schalter, sondern
#: eine Pruefsumme ueber die Tatsachen, unter denen freigegeben wurde.
APPROVAL_BOUND_FIELDS = ("model_id", "bundle_sha256",
                         "feature_schema_fingerprint",
                         "c9_manifest_fingerprint",
                         "c10_contract_fingerprint",
                         "evaluation_artifact", "evaluation_status",
                         "transition")


def approval_token(fakten):
    """
    Das Freigabezeichen zu einem Satz Tatsachen.

    Wer freigeben will, muss alle gebundenen Werte nennen. Stimmt
    spaeter einer nicht mehr, ergibt dieselbe Rechnung ein anderes
    Zeichen, und die Freigabe verfaellt von selbst.

    Bewusst KEIN Geheimnis: Das Zeichen ist aus oeffentlichen Angaben
    nachrechenbar. Es schuetzt vor dem Versehen - falsches Bundle,
    geaendertes Bundle, veralteter Vertrag - und ausdruecklich nicht
    gegen jemanden mit Schreibrecht. Ein hartkodiertes Passwort im
    Repository waere Sicherheitstheater und nicht mehr wert.
    """
    fehlend = [f for f in APPROVAL_BOUND_FIELDS if not fakten.get(f)]
    if fehlend:
        raise RegistryError(
            f"Freigabe unvollstaendig, es fehlen: {fehlend}. Eine "
            f"Freigabe ohne gebundene Tatsachen bindet nichts.")

    nutzlast = {f: fakten[f] for f in APPROVAL_BOUND_FIELDS}
    nutzlast["schema"] = REGISTRY_SCHEMA_VERSION
    return hashlib.sha256(_kanonisch(nutzlast).encode("utf-8")).hexdigest()


def build_approval(eintrag, transition, reason, approved_at=None):
    """
    Eine Freigabe zu einem Registryeintrag erzeugen.

    reason ist Pflicht und muss lesbar sein: Eine Freigabe ohne
    nachvollziehbaren Grund ist spaeter nicht von einem Versehen zu
    unterscheiden.
    """
    if not (reason or "").strip() or len((reason or "").strip()) < 15:
        raise RegistryError(
            "Eine Freigabe braucht eine nachvollziehbare Begruendung "
            "(mindestens 15 Zeichen).")

    fakten = {f: eintrag.get(f) for f in APPROVAL_BOUND_FIELDS
              if f != "transition"}
    fakten["transition"] = transition

    return {
        "model_id": eintrag.get("model_id"),
        "transition": transition,
        "token": approval_token(fakten),
        "reason": reason.strip(),
        "approved_at": approved_at,
        "bound_fields": list(APPROVAL_BOUND_FIELDS),
    }


def verify_approval(eintrag, approval, transition):
    """
    Passt diese Freigabe zu diesem Eintrag und diesem Schritt?

    Rueckgabe: (ok, grund). grund ist None, wenn alles passt.
    """
    if not approval:
        return False, "keine Freigabe vorgelegt"
    if approval.get("model_id") != eintrag.get("model_id"):
        return False, (f"Freigabe gehoert zu "
                       f"{approval.get('model_id')!r}, nicht zu "
                       f"{eintrag.get('model_id')!r}")
    if approval.get("transition") != transition:
        return False, (f"Freigabe gilt fuer {approval.get('transition')!r}, "
                       f"nicht fuer {transition!r}")
    if not (approval.get("reason") or "").strip():
        return False, "Freigabe ohne Begruendung"

    fakten = {f: eintrag.get(f) for f in APPROVAL_BOUND_FIELDS
              if f != "transition"}
    fakten["transition"] = transition
    try:
        erwartet = approval_token(fakten)
    except RegistryError as fehler:
        return False, str(fehler)

    if approval.get("token") != erwartet:
        return False, ("Freigabezeichen passt nicht zum aktuellen Stand. "
                       "Bundle, Merkmalsschema oder ein Vertrag hat sich "
                       "seit der Freigabe geaendert.")
    return True, None


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

#: Pflichtfelder je Eintrag.
REQUIRED_FIELDS = ("model_id", "model_name", "model_family",
                   "bundle_schema_version", "stage", "bundle_path",
                   "bundle_sha256", "feature_schema_fingerprint",
                   "c9_manifest_fingerprint", "c10_contract_fingerprint",
                   "evaluation_status", "state_reason")


def _pruefe_relativ(pfad):
    """
    Ein Bundlepfad muss repo-relativ sein.

    Ein absoluter Pfad in einem versionierten Dokument ist auf jedem
    anderen Rechner falsch und verraet nebenbei die lokale
    Verzeichnisstruktur. Geprueft werden BEIDE Schreibweisen: Ein
    Windowspfad faellt unter Linux nicht durch os.path.isabs.
    """
    if not pfad or not isinstance(pfad, str):
        return "Bundlepfad fehlt"
    if pfad.startswith("/") or pfad.startswith("\\"):
        return f"absoluter Pfad: {pfad!r}"
    if len(pfad) > 1 and pfad[1] == ":":
        return f"absoluter Windows-Pfad: {pfad!r}"
    if ".." in pfad.replace("\\", "/").split("/"):
        return f"Pfad verlaesst das Repository: {pfad!r}"
    return None


def validate_registry(dokument, repo_root=None, pruefe_bundles=True):
    """
    Die Registry vollstaendig pruefen - fail closed.

    Rueckgabe: Liste der Befunde (leer heisst gueltig). Es wird NICHT
    beim ersten Fehler abgebrochen: Wer eine kaputte Registry
    repariert, will alle Stellen kennen, nicht die erste.
    """
    befunde = []

    if not isinstance(dokument, dict):
        return ["Registry ist kein Objekt"]

    version = dokument.get("schema_version")
    if version != REGISTRY_SCHEMA_VERSION:
        befunde.append(
            f"unbekannte Schemafassung {version!r}, erwartet "
            f"{REGISTRY_SCHEMA_VERSION}")

    eintraege = dokument.get("models")
    if not isinstance(eintraege, list):
        return befunde + ["models fehlt oder ist keine Liste"]

    gesehen = set()
    aktive = []
    for i, eintrag in enumerate(eintraege):
        if not isinstance(eintrag, dict):
            befunde.append(f"Eintrag {i} ist kein Objekt")
            continue

        kennung = eintrag.get("model_id")
        for feld in REQUIRED_FIELDS:
            if eintrag.get(feld) in (None, ""):
                befunde.append(f"{kennung!r}: Pflichtfeld {feld} fehlt")

        if kennung in gesehen:
            befunde.append(f"doppelte Modell-ID: {kennung!r}")
        gesehen.add(kennung)

        stufe = eintrag.get("stage")
        if stufe not in STAGES:
            befunde.append(f"{kennung!r}: unbekannte Stufe {stufe!r}")
        if stufe == STAGE_ACTIVE:
            aktive.append(kennung)

        fehler = _pruefe_relativ(eintrag.get("bundle_path"))
        if fehler:
            befunde.append(f"{kennung!r}: {fehler}")

        if pruefe_bundles and not fehler:
            wurzel = repo_root or "."
            voll = os.path.join(wurzel, eintrag["bundle_path"])
            if not os.path.isfile(voll):
                befunde.append(f"{kennung!r}: Bundle fehlt ({voll})")
            else:
                tatsaechlich = bundle_sha256(voll)
                if tatsaechlich != eintrag.get("bundle_sha256"):
                    befunde.append(
                        f"{kennung!r}: Bundle-Hash weicht ab "
                        f"(Datei {tatsaechlich[:16]}..., Registry "
                        f"{str(eintrag.get('bundle_sha256'))[:16]}...)")

        if stufe == STAGE_ACTIVE:
            status = eintrag.get("evaluation_status")
            if status not in EVALUATION_ALLOWING_ACTIVE:
                befunde.append(
                    f"{kennung!r}: Evaluationsstatus {status!r} traegt "
                    f"keine Aktivierung, nur "
                    f"{list(EVALUATION_ALLOWING_ACTIVE)}")
            elif status == EVALUATION_GRANDFATHERED:
                # Der Bestandsschutz gilt nur mit ausdruecklicher
                # Kennzeichnung und Begruendung. Ohne sie waere er ein
                # bequemer Weg an jedem Gate vorbei.
                if eintrag.get("grandfathered") is not True:
                    befunde.append(
                        f"{kennung!r}: Status "
                        f"{EVALUATION_GRANDFATHERED!r} ohne "
                        f"grandfathered=True")
                if len((eintrag.get("grandfathered_reason") or "").strip()) < 30:
                    befunde.append(
                        f"{kennung!r}: Bestandsschutz ohne "
                        f"nachvollziehbare Begruendung")
            if (not eintrag.get("evaluation_artifact")
                    and status != EVALUATION_GRANDFATHERED):
                befunde.append(
                    f"{kennung!r}: aktiv ohne Evaluationsartefakt")
            ok, grund = verify_approval(eintrag, eintrag.get("approval"),
                                        STAGE_ACTIVE)
            if not ok:
                befunde.append(f"{kennung!r}: aktiv ohne gueltige "
                               f"Freigabe ({grund})")

    if len(aktive) > 1:
        befunde.append(f"mehr als ein aktives Modell: {sorted(aktive)}")

    ziel = dokument.get("rollback_target")
    if ziel is not None and ziel not in gesehen:
        befunde.append(f"Rollbackziel {ziel!r} ist nicht registriert")

    return befunde


def assert_valid(dokument, repo_root=None, pruefe_bundles=True):
    """Wie validate_registry, aber wirft. Fuer Schreibwege."""
    befunde = validate_registry(dokument, repo_root, pruefe_bundles)
    if befunde:
        raise RegistryError(
            "Registry ungueltig:\n  " + "\n  ".join(befunde))
    return True


# ---------------------------------------------------------------------------
# Lesen und atomar schreiben
# ---------------------------------------------------------------------------

def empty_registry():
    """Eine gueltige, leere Registry."""
    return {"schema_version": REGISTRY_SCHEMA_VERSION,
            "models": [], "rollback_target": None,
            "note": ("Die eine Wahrheitsquelle darueber, welches Modell "
                     "wirken darf. Nicht von Hand bearbeiten - die "
                     "Freigabezeichen haengen an den Werten.")}


def load_registry(pfad=None, repo_root=None):
    """
    Die Registry lesen - fail closed.

    Eine fehlende Datei ist KEIN Fehler: Sie bedeutet "kein Modell
    registriert", und das ist ein gueltiger Zustand. Eine vorhandene,
    aber kaputte Datei ist sehr wohl einer.
    """
    wurzel = repo_root or "."
    voll = pfad or os.path.join(wurzel, REGISTRY_PATH)
    if not os.path.isfile(voll):
        return empty_registry()
    try:
        with open(voll, encoding="utf-8") as datei:
            dokument = json.load(datei)
    except (OSError, ValueError) as fehler:
        raise RegistryError(
            f"Registry {voll} ist nicht lesbar: {fehler}. Es wird kein "
            f"Modell geladen; die Runtime faellt auf die Baseline "
            f"zurueck.") from fehler
    return dokument


def write_registry(dokument, pfad=None, repo_root=None,
                   pruefe_bundles=True):
    """
    Die Registry atomar ersetzen.

    Ablauf, und die Reihenfolge ist der ganze Schutz:

      1. Erst vollstaendig validieren. Eine ungueltige Registry wird
         gar nicht geschrieben.
      2. In eine temporaere Datei IM SELBEN Verzeichnis schreiben -
         os.replace ist nur innerhalb eines Dateisystems atomar.
      3. flush und fsync, damit der Inhalt wirklich auf dem Datentraeger
         steht, bevor der Name umgehaengt wird.
      4. os.replace. Auf POSIX und auf Windows ersetzt es eine
         vorhandene Datei in einem Schritt; ein Leser sieht die alte
         oder die neue, nie eine halbe.

    Schlaegt Schritt 1 oder 2 fehl, bleibt die vorherige Registry
    unberuehrt liegen.
    """
    assert_valid(dokument, repo_root, pruefe_bundles)

    wurzel = repo_root or "."
    voll = pfad or os.path.join(wurzel, REGISTRY_PATH)
    verzeichnis = os.path.dirname(os.path.abspath(voll))
    os.makedirs(verzeichnis, exist_ok=True)

    griff, temporaer = tempfile.mkstemp(
        dir=verzeichnis, prefix=".registry-", suffix=".tmp")
    try:
        with os.fdopen(griff, "w", encoding="utf-8") as datei:
            json.dump(dokument, datei, indent=2, ensure_ascii=False,
                      sort_keys=True)
            datei.write("\n")
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temporaer, voll)
    except Exception:
        # Die halbe Datei darf nicht liegenbleiben - sie traegt die
        # Endung .tmp und wuerde nie als Registry gelesen, waere aber
        # Muell im Datenverzeichnis.
        if os.path.exists(temporaer):
            try:
                os.unlink(temporaer)
            except OSError:                              # pragma: no cover
                pass
        raise
    return voll


# ---------------------------------------------------------------------------
# Uebergaenge
# ---------------------------------------------------------------------------

def _finde(dokument, model_id):
    for eintrag in dokument.get("models") or []:
        if eintrag.get("model_id") == model_id:
            return eintrag
    return None


def check_transition(von, nach):
    """
    Darf dieser Schritt gegangen werden?

    Rueckgabe: (ok, grund).
    """
    if nach not in STAGES:
        return False, f"unbekannte Zielstufe {nach!r}"
    if (von, nach) in FORBIDDEN_TRANSITIONS:
        return False, FORBIDDEN_TRANSITIONS[(von, nach)]
    if (von, nach) not in ALLOWED_TRANSITIONS:
        return False, (f"Uebergang {von!r} -> {nach!r} ist nicht "
                       f"vorgesehen")
    return True, None


def register_candidate(dokument, eintrag):
    """
    Ein neues Bundle als Kandidat aufnehmen.

    Registrierung ist die harmloseste Handlung der Registry und
    trotzdem die wichtigste: Nur was hier steht, kann spaeter ueberhaupt
    etwas werden.
    """
    neu = json.loads(json.dumps(dokument))
    if _finde(neu, eintrag.get("model_id")):
        raise RegistryError(
            f"{eintrag.get('model_id')!r} ist bereits registriert.")

    ok, grund = check_transition(None, STAGE_CANDIDATE)
    if not ok:                                           # pragma: no cover
        raise RegistryError(grund)

    kandidat = dict(eintrag, stage=STAGE_CANDIDATE)
    kandidat.setdefault("state_reason",
                        "registriert, ohne Wirkung auf die Runtime")
    neu.setdefault("models", []).append(kandidat)
    return neu


def set_stage(dokument, model_id, nach, approval=None, reason=None):
    """
    Einen Eintrag auf eine andere Stufe setzen.

    Der Schritt nach active traegt zusaetzlich zwei Pflichten: eine
    gueltige Freigabe und das Umhaengen des bisherigen aktiven Modells
    auf rollback. Beides geschieht in DIESER Funktion, damit es nicht
    zwei Wege gibt, von denen einer die Haelfte vergisst.
    """
    neu = json.loads(json.dumps(dokument))
    eintrag = _finde(neu, model_id)
    if eintrag is None:
        raise RegistryError(f"{model_id!r} ist nicht registriert.")

    von = eintrag.get("stage")
    ok, grund = check_transition(von, nach)
    if not ok:
        raise RegistryError(
            f"{model_id!r}: {von!r} -> {nach!r} abgelehnt. {grund}")

    if nach == STAGE_ACTIVE:
        # Der Bestandsschutz traegt KEINE neue Aktivierung. Er
        # beschreibt einen Zustand, der vor der Registry entstanden
        # ist; wer nach C11 aktiv werden will, braucht "accepted".
        if eintrag.get("evaluation_status") != EVALUATION_ACCEPTED:
            raise RegistryError(
                f"{model_id!r}: Evaluationsstatus "
                f"{eintrag.get('evaluation_status')!r} traegt keine "
                f"Aktivierung. Nur {EVALUATION_ACCEPTED!r}. "
                f"{EVALUATION_GRANDFATHERED!r} gilt ausschliesslich "
                f"fuer den vor C11 bereits laufenden Stand und wird "
                f"nicht ueber set_stage vergeben.")
        gueltig, warum = verify_approval(eintrag, approval, STAGE_ACTIVE)
        if not gueltig:
            raise RegistryError(
                f"{model_id!r}: Aktivierung ohne gueltige Freigabe. "
                f"{warum}")

        for anderer in neu.get("models") or []:
            if (anderer.get("model_id") != model_id
                    and anderer.get("stage") == STAGE_ACTIVE):
                anderer["stage"] = STAGE_ROLLBACK
                anderer["state_reason"] = (
                    f"abgeloest von {model_id!r}, aufgehoben als "
                    f"Rueckfallziel")
                neu["rollback_target"] = anderer.get("model_id")

        eintrag["approval"] = approval

    eintrag["stage"] = nach
    eintrag["state_reason"] = (
        reason or f"Uebergang {von!r} -> {nach!r}")
    return neu


def rollback(dokument, reason=None):
    """
    Auf das aufgehobene Rueckfallziel zurueckgehen.

    Es wird KEINE neue Freigabe verlangt: Das Rueckfallziel war
    bereits einmal freigegeben, und sein Eintrag traegt diese Freigabe
    noch. Geprueft wird sie trotzdem erneut - ein beschaedigtes
    Rueckfallziel ist kein Rueckfallziel.
    """
    neu = json.loads(json.dumps(dokument))
    ziel = neu.get("rollback_target")
    if not ziel:
        raise RegistryError("Kein Rueckfallziel hinterlegt.")

    eintrag = _finde(neu, ziel)
    if eintrag is None:
        raise RegistryError(f"Rueckfallziel {ziel!r} ist nicht registriert.")
    if eintrag.get("stage") != STAGE_ROLLBACK:
        raise RegistryError(
            f"Rueckfallziel {ziel!r} steht auf "
            f"{eintrag.get('stage')!r}, nicht auf {STAGE_ROLLBACK!r}.")

    gueltig, warum = verify_approval(eintrag, eintrag.get("approval"),
                                     STAGE_ACTIVE)
    if not gueltig:
        raise RegistryError(
            f"Rueckfallziel {ziel!r} traegt keine gueltige Freigabe "
            f"mehr: {warum}")

    for anderer in neu.get("models") or []:
        if anderer.get("stage") == STAGE_ACTIVE:
            anderer["stage"] = STAGE_ROLLBACK
            anderer["state_reason"] = (
                f"durch Rollback auf {ziel!r} abgeloest")
            neu["rollback_target"] = anderer.get("model_id")

    eintrag["stage"] = STAGE_ACTIVE
    eintrag["state_reason"] = reason or "durch Rollback reaktiviert"
    return neu


def retire(dokument, model_id, evaluation_status, evaluation_artifact,
           reason, nach=STAGE_CANDIDATE):
    """
    Ein Modell nach abgelehnter oder unklarer Evaluation aus dem
    aktiven Betrieb nehmen (V2-C12).

    Der Gegenweg zu set_stage(..., STAGE_ACTIVE): Dort verlangt jede
    Aktivierung eine Freigabe, hier verlangt jede Ausserbetriebnahme
    ein Ergebnis. Ein Modell verliert seine Wirkung nicht durch einen
    Handgriff, sondern weil eine Messung es sagt.

    Die Freigabe wird ENTFERNT. Sie galt fuer einen Zustand, den es
    nicht mehr gibt; sie stehen zu lassen hiesse, eine gueltige
    Freigabe fuer ein abgelehntes Modell aufzubewahren.

    nach: candidate, wenn das Modell keine Wirkung mehr haben soll;
    shadow, wenn ein weiterer Schattenbetrieb Erkenntniswert hat.
    """
    if nach not in (STAGE_CANDIDATE, STAGE_SHADOW):
        raise RegistryError(
            f"Ausserbetriebnahme geht nach {STAGE_CANDIDATE!r} oder "
            f"{STAGE_SHADOW!r}, nicht nach {nach!r}.")
    if evaluation_status == EVALUATION_ACCEPTED:
        raise RegistryError(
            "retire() ist fuer abgelehnte oder unklare Ergebnisse. Ein "
            "angenommenes Modell wird nicht ausser Betrieb genommen.")
    if not evaluation_artifact:
        raise RegistryError(
            "Eine Ausserbetriebnahme braucht das Artefakt, das sie "
            "traegt. Ohne Beleg waere sie so unbelegt wie die "
            "Aktivierung, die sie beendet.")
    if len((reason or "").strip()) < 30:
        raise RegistryError(
            "Eine Ausserbetriebnahme braucht eine nachvollziehbare "
            "Begruendung (mindestens 30 Zeichen).")

    neu_doc = json.loads(json.dumps(dokument))
    eintrag = _finde(neu_doc, model_id)
    if eintrag is None:
        raise RegistryError(f"{model_id!r} ist nicht registriert.")

    von = eintrag.get("stage")
    ok, warum = check_transition(von, nach)
    if not ok:
        raise RegistryError(f"{model_id!r}: {von!r} -> {nach!r}. {warum}")

    eintrag["stage"] = nach
    eintrag["evaluation_status"] = evaluation_status
    eintrag["evaluation_artifact"] = evaluation_artifact
    eintrag["state_reason"] = reason.strip()
    eintrag.pop("approval", None)
    eintrag.pop("grandfathered", None)
    eintrag.pop("grandfathered_reason", None)

    # Ein ausser Betrieb genommenes Modell ist kein Rueckfallziel.
    if neu_doc.get("rollback_target") == model_id:
        neu_doc["rollback_target"] = None

    return neu_doc


# ---------------------------------------------------------------------------
# Auswahl fuer die Runtime
# ---------------------------------------------------------------------------

def active_entry(dokument=None, repo_root=None, pruefe_bundles=True):
    """
    Das eine Modell, das wirken darf - oder None.

    Rueckgabe: (eintrag_oder_None, grund). grund nennt bei None immer,
    WARUM es keines gibt; die Runtime schreibt ihn in ihre Diagnose,
    statt einfach nichts zu tun.

    Diese Funktion ist der einzige Weg, auf dem ein Modell in die
    Nutzerantwort gelangt. Sie raet nichts, sie sucht keine Datei und
    sie nimmt nicht das neueste.
    """
    try:
        dokument = (dokument if dokument is not None
                    else load_registry(repo_root=repo_root))
    except RegistryError as fehler:
        return None, f"registry_unreadable: {fehler}"

    befunde = validate_registry(dokument, repo_root, pruefe_bundles)
    if befunde:
        return None, "registry_invalid: " + "; ".join(befunde[:3])

    aktive = [e for e in dokument.get("models") or []
              if e.get("stage") == STAGE_ACTIVE]
    if not aktive:
        return None, "no_active_model"
    if len(aktive) > 1:                                  # pragma: no cover
        return None, "multiple_active_models"

    return aktive[0], None


def shadow_entries(dokument=None, repo_root=None):
    """
    Die Modelle im Schattenlauf.

    Sie duerfen rechnen und protokollieren. Was sie NICHT duerfen,
    steht in der Runtime, nicht hier: Diese Funktion liefert nur die
    Liste.
    """
    try:
        dokument = (dokument if dokument is not None
                    else load_registry(repo_root=repo_root))
    except RegistryError:
        return []
    return [e for e in dokument.get("models") or []
            if e.get("stage") == STAGE_SHADOW]


def contract():
    """Der Registryvertrag in Textform - fuer Artefakt und Bericht."""
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_path": REGISTRY_PATH,
        "stages": list(STAGES),
        "stages_affecting_output": list(STAGES_AFFECTING_OUTPUT),
        "allowed_transitions": sorted(
            [list(t) for t in ALLOWED_TRANSITIONS],
            key=lambda p: (str(p[0]), str(p[1]))),
        "forbidden_transitions": {
            f"{a} -> {b}": grund
            for (a, b), grund in sorted(
                FORBIDDEN_TRANSITIONS.items(),
                key=lambda kv: (str(kv[0][0]), str(kv[0][1])))},
        "approval_binds": list(APPROVAL_BOUND_FIELDS),
        "approval_is_not_authentication": (
            "Das Freigabezeichen ist eine Pruefsumme ueber die "
            "Tatsachen, unter denen freigegeben wurde. Es verhindert "
            "das Versehen - falsches Bundle, veraendertes Bundle, "
            "veralteter Vertrag - und ausdruecklich nicht den Vorsatz. "
            "Wer die CLI ausfuehren kann, kann ein Zeichen erzeugen."),
        "evaluation_accepted": EVALUATION_ACCEPTED,
        "evaluation_blocking": list(EVALUATION_BLOCKING),
        "evaluation_allowing_active": list(EVALUATION_ALLOWING_ACTIVE),
        "grandfathering": (
            f"{EVALUATION_GRANDFATHERED!r} verzeichnet den Stand, der "
            f"vor der Registry bereits lief - das Bundle stand auf "
            f"'experimental', und experimental deckt den aktiven "
            f"Betrieb. Die Registry hat diesen Zustand nicht "
            f"hergestellt und behauptet nicht, er sei statistisch "
            f"belegt. Er traegt keine NEUE Aktivierung: set_stage "
            f"verlangt dafuer 'accepted'."),
        "atomic_write": (
            "validieren, in eine temporaere Datei im selben Verzeichnis "
            "schreiben, flush und fsync, dann os.replace. Ein Leser "
            "sieht die alte oder die neue Registry, nie eine halbe."),
        "retirement": (
            "retire() nimmt ein Modell nach abgelehnter oder unklarer "
            "Evaluation aus dem aktiven Betrieb. Es verlangt das "
            "belegende Artefakt und eine Begruendung und entfernt die "
            "Freigabe - sie galt fuer einen Zustand, den es nicht mehr "
            "gibt."),
        "fail_closed": (
            "Jeder Zweifel endet ohne aktives Modell. Es gibt keinen "
            "Rueckfall auf das neueste Bundle."),
    }


# ---------------------------------------------------------------------------
# Das C11-Artefakt
# ---------------------------------------------------------------------------

#: Wohin der Registrynachweis gehoert.
ARTIFACT_PATH = "data/ml/c11_registry_release_gate_contract.json"

#: Die Fail-closed-Faelle, die geprueft sind.
#:
#: Jeder Eintrag nennt den Fall und was passiert. Keiner endet mit
#: einem aktiven Modell - das ist die ganze Aussage der Tabelle.
FAIL_CLOSED_CASES = (
    {"case": "Registry fehlt",
     "behaviour": "gueltiger Leerzustand, kein aktives Modell"},
    {"case": "Registry ist beschaedigt oder kein gueltiges JSON",
     "behaviour": "RegistryError, Runtime faellt auf die Baseline"},
    {"case": "unbekannte Schemafassung",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "unbekannte Stufe",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "doppelte Modell-ID",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "zwei Modelle als aktiv markiert",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "kein Modell als aktiv markiert",
     "behaviour": "no_active_model, Baseline"},
    {"case": "Bundle fehlt",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "Bundle-Hash weicht ab",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "absoluter Pfad in der Registry",
     "behaviour": "Befund, kein aktives Modell"},
    {"case": "Freigabe fehlt",
     "behaviour": "Aktivierung abgelehnt"},
    {"case": "Freigabe gehoert zu einem anderen Bundle",
     "behaviour": "Aktivierung abgelehnt"},
    {"case": "Freigabe nach Bundleaenderung",
     "behaviour": "Zeichen passt nicht mehr, Aktivierung abgelehnt"},
    {"case": "Evaluationsstatus traegt keine Aktivierung",
     "behaviour": "Aktivierung abgelehnt"},
    {"case": "Rueckfallziel beschaedigt oder ohne gueltige Freigabe",
     "behaviour": "Rollback abgelehnt, bisheriger Stand bleibt"},
    {"case": "Schattenmodell schlaegt fehl",
     "behaviour": "aktive Berechnung laeuft unveraendert weiter"},
)


def _c11_git():
    import subprocess

    try:
        fertig = subprocess.run(["git", "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=30)
    except Exception:                                    # pragma: no cover
        return None
    return fertig.stdout.strip() if fertig.returncode == 0 else None


def build_artifact(dokument=None, repo_root=None):
    """
    Der C11-Registrynachweis - deterministisch und ohne Geheimnisse.

    Er belegt, WAS die Registry verhindert, und er sagt ausdruecklich,
    dass sie nichts aktiviert hat. Ein Artefakt, das eine Freigabe
    andeutet, die es nicht gibt, waere schlimmer als keines.
    """
    import datetime as _dt
    import hashlib as _h
    import json as _j
    import os as _os

    dokument = (dokument if dokument is not None
                else load_registry(repo_root=repo_root))

    befunde = validate_registry(dokument, repo_root)
    eintrag, grund = active_entry(dokument, repo_root)

    nach_stufe = {}
    for modell in dokument.get("models") or []:
        nach_stufe.setdefault(modell.get("stage"), []).append(
            modell.get("model_id"))

    # Vertragsfingerabdruecke aus den Nachbarbloecken - gelesen, nicht
    # behauptet.
    def _lies(pfad, feld):
        voll = _os.path.join(repo_root or ".", pfad)
        if not _os.path.isfile(voll):
            return None
        with open(voll, encoding="utf-8") as datei:
            return _j.load(datei).get(feld)

    c9 = _lies("data/ml/c9_early_v2_manifest_2023-2025.json",
               "manifest_fingerprint")
    c10 = _lies("data/ml/c10_prediction_cutoff_contract_2023-2025.json",
                "contract_fingerprint")

    from src.ml import early_v2 as e9
    from src.ml import runtime as rt

    artefakt = {
        "artifact": "v2-c11 model registry and release gate",
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "created_at": _dt.datetime.now(
            _dt.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _c11_git(),

        "contract": contract(),
        "registry_fingerprint": registry_fingerprint(dokument),
        "registry_valid": not befunde,
        "registry_findings": befunde,

        "models_by_stage": {k: sorted(v) for k, v
                            in sorted(nach_stufe.items())},
        "active_model_id": (eintrag or {}).get("model_id"),
        "active_reason_if_none": grund,
        "candidate_model_ids": sorted(
            nach_stufe.get(STAGE_CANDIDATE, [])),
        "grandfathered_model_ids": sorted(
            m.get("model_id") for m in dokument.get("models") or []
            if m.get("evaluation_status") == EVALUATION_GRANDFATHERED),
        "shadow_model_ids": sorted(nach_stufe.get(STAGE_SHADOW, [])),
        "rollback_target": dokument.get("rollback_target"),

        "bound_fingerprints": {
            "c9_manifest": c9,
            "c10_contract": c10,
            "feature_schema": e9.schema_fingerprint(),
        },
        "bundle_hashes": {
            m.get("model_id"): m.get("bundle_sha256")
            for m in sorted(dokument.get("models") or [],
                            key=lambda e: str(e.get("model_id")))},

        "release_gate": {
            "status": "implemented_not_exercised",
            "meaning": ("Der Weg zur Aktivierung ist gebaut und "
                        "getestet. C11 hat kein Modell freigegeben und "
                        "keines neu aktiviert. Das aktive Modell lief "
                        "bereits vor C11 und steht unter "
                        "Bestandsschutz."),
            "binds": list(APPROVAL_BOUND_FIELDS),
            "is_not_authentication": contract()[
                "approval_is_not_authentication"],
        },

        "runtime_selection": {
            "single_source": ("model_registry.active_entry - der "
                              "einzige Weg, auf dem ein Modell in die "
                              "Nutzerantwort gelangt"),
            "gate_reason_not_registered": rt.REASON_NOT_ACTIVE_IN_REGISTRY,
            "gate_reason_registry_unusable": rt.REASON_REGISTRY_UNUSABLE,
            "additive_only": ("Die Registrypruefung steht NACH der "
                              "bestehenden Stufenpruefung und kann nur "
                              "ablehnen. Sie macht nichts moeglich, was "
                              "vorher unmoeglich war."),
            "default_mode": rt.DEFAULT_MODE,
            "cutoff_untouched": ("Die Registry waehlt das Modell, nicht "
                                 "den Zeitpunkt. Der prediction_cutoff "
                                 "aus V2-C10 wird weder neu berechnet "
                                 "noch ueberschrieben."),
        },

        "shadow_isolation": {
            "may": ["dieselben PIT-sicheren Eingaben erhalten",
                    "intern rechnen",
                    "getrennt protokolliert werden"],
            "may_not": ["die sichtbare Nutzerantwort veraendern",
                        "mit dem aktiven Ergebnis vermischt werden",
                        "die Zufallsfolge des aktiven Modells beruehren",
                        "bei einem Fehler die Simulation blockieren"],
            "enforced_by": ("runtime._aufloesen kehrt im Schattenmodus "
                            "mit der Baseline zurueck; der Schattenwert "
                            "steht ausschliesslich in der Diagnose"),
        },

        "mode_separation": {
            "ml_mode": "ausschliesslich das freigegebene ML-Modell",
            "individual_mode": ("ausschliesslich manuelle Einstellungen, "
                                "kein Modell, kein ml_weight"),
            "registry_touches_only_ml": ("Die Registry wird nur im "
                                         "ML-Zweig gelesen. Ein "
                                         "Registryfehler laesst den "
                                         "individuellen Modus "
                                         "unberuehrt."),
        },

        "fail_closed_cases": [dict(f) for f in FAIL_CLOSED_CASES],
        "atomic_write": contract()["atomic_write"],

        "known_limits": [
            "Das Freigabezeichen bindet, es authentifiziert nicht. Wer "
            "die CLI ausfuehren kann, kann ein Zeichen erzeugen. Es "
            "verhindert das Versehen, nicht den Vorsatz.",

            "Der Bundle-Hash deckt die Datei zum Zeitpunkt der "
            "Registrierung. Er erkennt eine spaetere Aenderung, "
            "verhindert sie aber nicht.",

            "Es ist kein V2-Modell REGULAER freigegeben. Das aktive "
            "Bundle steht unter Bestandsschutz "
            f"({EVALUATION_GRANDFATHERED}): Es lief vor C11 bereits "
            "ueber approach=ml, weil seine Freigabestufe 'experimental' "
            "den aktiven Betrieb deckt. Die Registry verzeichnet diesen "
            "Zustand, statt ein laufendes Feature stillschweigend "
            "abzuschalten. Der Status ist kein statistischer Beleg: C9 "
            "hat keinen angenommenen Kandidaten gefunden.",

            "Der Bestandsschutz ist in einem eigenen Block aufzuloesen, "
            "entweder durch regulaere Freigabe nach bestandenem Gate "
            "oder durch Ausserbetriebnahme des Bundles. Beides ist eine "
            "Produktentscheidung.",

            "Es gibt weiterhin keinen unangetasteten Holdout. Die "
            "Saisons 2023 bis 2025 haben alle bisherigen Entscheidungen "
            "getragen.",

            "C11 baut den Weg. Ob je ein V2-Modell diesen Weg geht, "
            "entscheidet eine Messung, die es bisher nicht gibt.",
        ],

        "activated_anything": False,
        "overwrote_bundle": False,
        "status": "COMPLETE",
    }

    # -- Vertrag und Zustand getrennt (repariert in V2-C15) ------------
    #
    # DER FEHLER, DER HIER LAG
    # Der Vertragsfingerabdruck wurde ueber das GESAMTE Artefakt
    # gebildet, also einschliesslich models_by_stage, active_model_id,
    # registry_fingerprint und der Befundliste. Jede Registrierung
    # eines Modells veraenderte ihn damit, und man konnte nicht mehr
    # unterscheiden, ob sich die REGEL geaendert hatte oder nur die
    # Belegung. Genau dieselbe Verwechslung hat V2-C13 fuer sein
    # eigenes Artefakt vermieden.
    #
    # Ab jetzt deckt contract_fingerprint ausschliesslich die
    # unveraenderlichen Bloecke. Der Zustand bekommt einen eigenen
    # Wert.
    VERTRAGSBLOECKE = ("schema_version", "contract", "release_gate",
                       "runtime_selection", "shadow_isolation",
                       "mode_separation", "fail_closed_cases",
                       "atomic_write", "known_limits")
    ZUSTANDSBLOECKE = ("active_model_id", "active_reason_if_none",
                       "models_by_stage", "candidate_model_ids",
                       "shadow_model_ids", "grandfathered_model_ids",
                       "bundle_hashes", "registry_findings",
                       "registry_fingerprint", "registry_valid",
                       "rollback_target", "bound_fingerprints",
                       "activated_anything", "overwrote_bundle",
                       "status")

    vertrag_teil = {k: artefakt[k] for k in VERTRAGSBLOECKE
                    if k in artefakt}
    zustand_teil = {k: artefakt[k] for k in ZUSTANDSBLOECKE
                    if k in artefakt}

    artefakt["contract_fingerprint"] = _h.sha256(
        _kanonisch(vertrag_teil).encode("utf-8")).hexdigest()
    artefakt["state_fingerprint"] = _h.sha256(
        _kanonisch(zustand_teil).encode("utf-8")).hexdigest()
    artefakt["fingerprint_separation"] = (
        "contract_fingerprint deckt ausschliesslich die "
        "unveraenderlichen Bloecke. Eine Modellregistrierung, ein "
        "Stufenwechsel oder ein Rollback bewegen ihn NICHT - sie "
        "bewegen state_fingerprint. Vor V2-C15 steckte beides in "
        "einem Wert.")
    artefakt["fingerprint_excludes"] = ["created_at", "git_commit"]
    artefakt["contract_fingerprint_covers"] = list(VERTRAGSBLOECKE)
    artefakt["state_fingerprint_covers"] = list(ZUSTANDSBLOECKE)
    return artefakt
