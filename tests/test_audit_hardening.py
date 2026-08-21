"""
Absicherung der Befunde aus dem externen Security-Audit (20.08.2026).

B1  Rate-Limiter-Storage und irrefuehrende nginx-Referenz
B2  Klartext-Datenbankzugangsdaten in docker-compose.yml
B3  Timing-Seitenkanal und User Enumeration beim Mailversand
B4  Unbegrenzter Ressourcenverbrauch im PDF-Merger (Seitenzahl)

Die Tests laufen ohne Netzwerk und ohne echten Mailversand.
"""

import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import app as main_app

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# B1 - Rate Limiting
# ---------------------------------------------------------------------------

def test_limiter_storage_is_configurable():
    """
    memory:// bleibt der Standard (kein Redis-Zwang), muss sich aber
    ohne Codeaenderung umstellen lassen.
    """
    from src.models.extensions import RATELIMIT_STORAGE_URI
    assert RATELIMIT_STORAGE_URI == "memory://"

    source = (PROJECT_ROOT / "src" / "models" / "extensions.py").read_text(encoding="utf-8")
    assert "FOOTSIM_RATELIMIT_STORAGE_URI" in source
    # Nicht mehr fest verdrahtet.
    assert 'storage_uri="memory://"' not in source


def test_nginx_reference_documents_active_rate_limiting():
    """
    Der externe Audit bemaengelte zu Recht, dass in der Referenzdatei
    alle limit_req-Direktiven auskommentiert waren - das las sich wie
    ein ungenutzter Schutz. In Produktion sind die Zonen aktiv; die
    Referenz muss das zeigen, sonst ist sie irrefuehrende Doku.
    """
    reference = (PROJECT_ROOT / "ops" / "nginx-footsim.conf.reference").read_text(encoding="utf-8")

    active = [
        line for line in reference.splitlines()
        if re.match(r"^\s*limit_req(_zone)?\s", line)
    ]
    assert active, "Referenz zeigt keine aktiven limit_req-Direktiven"

    # Die tatsaechlich deployten Zonennamen muessen auftauchen.
    assert "footsim_auth" in reference
    assert "footsim_pdf" in reference
    # Der Schluessel ist die echte TCP-Adresse, kein faelschbarer Header.
    assert "$binary_remote_addr" in reference


# ---------------------------------------------------------------------------
# B2 - Datenbankzugangsdaten
# ---------------------------------------------------------------------------
#
# WARUM HIER KEINE ECHTEN WERTE STEHEN
# Eine fruehere Fassung dieser Tests pruefte woertlich, dass der echte
# lokale Datenbankbenutzer bzw. das echte lokale Passwort NICHT in
# docker-compose.yml oder .env.example auftaucht. Dadurch standen genau
# diese beiden Werte als Literale in einer GETRACKTEN Datei - der Test
# hat das Leck konserviert, das er verhindern sollte, und mit dem Commit
# in die veroeffentlichte Historie getragen.
#
# Die Pruefungen sind deshalb auf STRUKTUR umgestellt. Gefragt wird nicht
# mehr "steht dieser eine bekannte Wert drin?", sondern "kann hier
# ueberhaupt ein Klartextwert stehen?". Das ist zugleich strenger, weil
# es jeden Klartextwert faengt, auch einen kuenftigen, den niemand kennt.
#
# Die Tests lesen bewusst NIE die echte .env, um Werte abzugleichen: eine
# fehlschlagende Assertion wuerde den Wert in die Testausgabe schreiben
# und das Leck damit erneut erzeugen - dann in Logs und CI-Ausgaben.

# Offensichtlich kuenstlich. Taucht dieser Wert je in einer echten Datei
# auf, ist etwas grundlegend schiefgelaufen.
SENTINEL_SECRET = "SENTINEL-NIEMALS-EIN-ECHTER-WERT"

# 'KEY: wert' innerhalb eines compose-environment-Blocks.
_COMPOSE_ENTRY = re.compile(r"^\s{2,}([A-Z][A-Z0-9_]*)\s*:\s*(\S.*?)\s*$")

# Vollstaendiger Verweis OHNE Klartext-Fallback: ${VAR:?meldung}.
# '${VAR}' und '${VAR:-standard}' erfuellen das absichtlich nicht -
# letzteres waere wieder ein Wert im Repository.
_ENV_REFERENCE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*):\?[^}]*\}$")

# Zugangsdaten in einer Verbindungszeichenfolge, also die Form
# schema://<benutzer>:<passwort>@host. Die Platzhalter in dieser
# Beschreibung sind Absicht: der repositoryweite Test unten liest auch
# diese Datei, und ein Beispiel mit Klartextnamen wuerde sich selbst
# melden.
_INLINE_DSN = re.compile(r"[a-z][a-z0-9+.\-]*://([^/\s:@]+):([^/\s:@]+)@")

# Ein Platzhalter steht vollstaendig in spitzen Klammern.
_PLACEHOLDER = re.compile(r"^<[^<>]+>$")


def _compose_environment_entries(text):
    """Liefert die (Schluessel, Wert)-Paare aller environment-Bloecke."""
    entries = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "environment:":
            inside = True
            continue
        if inside:
            match = _COMPOSE_ENTRY.match(line)
            if match:
                entries.append((match.group(1), match.group(2)))
            else:
                inside = False
    return entries


def test_docker_compose_environment_uses_only_env_references():
    """
    Kein einziger environment-Wert darf ein Literal sein.

    Das ersetzt die alte Suche nach einem bekannten Passwort: hier faellt
    JEDER Klartextwert auf.
    """
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    entries = _compose_environment_entries(compose)

    assert entries, "kein environment-Block gefunden - Parser oder Datei geaendert"

    for key, value in entries:
        match = _ENV_REFERENCE.match(value)
        assert match, (
            f"{key} ist kein reiner Umgebungsverweis der Form "
            f"${{{key}:?meldung}} - moeglicher Klartextwert im Repository"
        )
        # Der Verweis muss auf den gleichnamigen Schluessel zeigen, sonst
        # traegt die Datei stillschweigend einen anderen Wert ein.
        assert match.group(1) == key, f"{key} verweist auf {match.group(1)}"

    keys = {key for key, _ in entries}
    assert {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"} <= keys


def test_compose_check_rejects_literal_and_fallback():
    """
    Gegenprobe mit Sentinel-Werten: die Pruefung oben muss ein Literal
    und einen ':-'-Fallback wirklich bemerken. Ohne diesen Test koennte
    der Parser stillschweigend nichts finden und trotzdem gruen sein.
    """
    good = ("services:\n  db:\n    environment:\n"
            "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?fehlt}\n")
    literal = ("services:\n  db:\n    environment:\n"
               f"      POSTGRES_PASSWORD: {SENTINEL_SECRET}\n")
    fallback = ("services:\n  db:\n    environment:\n"
                f"      POSTGRES_PASSWORD: ${{POSTGRES_PASSWORD:-{SENTINEL_SECRET}}}\n")

    assert all(_ENV_REFERENCE.match(v)
               for _, v in _compose_environment_entries(good))
    assert not any(_ENV_REFERENCE.match(v)
                   for _, v in _compose_environment_entries(literal))
    assert not any(_ENV_REFERENCE.match(v)
                   for _, v in _compose_environment_entries(fallback))


def _env_example_assignments():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        assignments.append((key.strip(), value.strip()))
    return assignments


# Werte, die bewusst im Klartext stehen duerfen: Schalter und lokale
# Adressen, keine Zugangsdaten. Jeder andere Schluessel braucht einen
# Platzhalter.
_ENV_EXAMPLE_NON_SECRET = {
    "FOOTSIM_ENV",
    "FOOTSIM_TRUSTED_PROXY_HOPS",
    "FOOTSIM_RATELIMIT_STORAGE_URI",
    "MAIL_MOCK",
    "BASE_URL",
    "MAIL_DEFAULT_SENDER",
}


def test_env_example_secrets_are_placeholders_only():
    """
    Jeder sicherheitsrelevante Schluessel traegt einen Platzhalter in
    spitzen Klammern - nie einen benutzbaren Wert.
    """
    assignments = _env_example_assignments()
    assert assignments, ".env.example enthaelt keine Zuweisungen"

    for key, value in assignments:
        if key in _ENV_EXAMPLE_NON_SECRET or key == "DATABASE_URL":
            continue  # DATABASE_URL ist zusammengesetzt, eigener Test unten
        assert _PLACEHOLDER.match(value), (
            f"{key} in .env.example ist kein Platzhalter der Form <...> - "
            f"moeglicher echter Wert im Repository"
        )

    keys = {key for key, _ in assignments}
    assert {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
            "SECRET_KEY", "FOOTSIM_ENV", "FOOTSIM_TRUSTED_PROXY_HOPS"} <= keys


def test_env_example_dsn_has_placeholder_credentials():
    """Auch in der Verbindungszeichenfolge darf kein echter Teil stehen."""
    assignments = dict(_env_example_assignments())
    dsn = assignments["DATABASE_URL"]

    match = _INLINE_DSN.search(dsn)
    assert match, "DATABASE_URL enthaelt kein benutzer:passwort-Paar - Format geaendert?"

    assert _PLACEHOLDER.match(match.group(1)), "Benutzer in DATABASE_URL ist kein Platzhalter"
    assert _PLACEHOLDER.match(match.group(2)), "Passwort in DATABASE_URL ist kein Platzhalter"


def test_no_tracked_file_contains_inline_dsn_credentials():
    """
    Repositoryweite Sperre gegen genau die Regressionsklasse, um die es
    hier geht: eine Verbindungszeichenfolge MIT Zugangsdaten in einer
    getrackten Datei.

    Geprueft wird der getrackte Stand, nicht das Arbeitsverzeichnis -
    ignorierte Dateien wie .env sind damit ausgenommen, ohne dass der
    Test sie je oeffnet. Gemeldet wird nur der Fundort, nie der Wert.
    """
    import subprocess

    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    tracked = [name for name in listing.split("\0") if name]
    assert tracked, "git ls-files lieferte nichts"

    offenders = []
    for name in tracked:
        try:
            text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # Binaerdateien und Nicht-UTF-8 ueberspringen
        for match in _INLINE_DSN.finditer(text):
            if _PLACEHOLDER.match(match.group(1)) and _PLACEHOLDER.match(match.group(2)):
                continue  # Platzhalter sind in Ordnung
            offenders.append(name)
            break

    assert not offenders, (
        "Verbindungszeichenfolge mit Zugangsdaten in getrackten Dateien: "
        + ", ".join(sorted(set(offenders)))
    )


def test_env_is_ignored_by_git():
    """Ignoriert zu sein ist die Voraussetzung dafuer, ungetrackt zu bleiben."""
    import subprocess
    result = subprocess.run(
        ["git", "check-ignore", ".env"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, ".env steht nicht in .gitignore"


def test_real_env_is_not_tracked():
    """Die echte .env darf nie im Repository landen."""
    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    ).stdout.strip()
    assert tracked == "", ".env ist getrackt"


# ---------------------------------------------------------------------------
# B3 - Timing-Seitenkanal
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(postgres_db):
    main_app.app.config["TESTING"] = True
    main_app.app.config["WTF_CSRF_ENABLED"] = False
    with main_app.app.test_client() as client:
        yield client


def _make_user(email):
    from src.models import db, User
    with main_app.app.app_context():
        existing = db.session.execute(
            db.select(User).filter_by(email=email)
        ).scalar_one_or_none()
        if existing is None:
            user = User(email=email, first_name="Timing", last_name="Test")
            user.set_password("secure_password123")
            db.session.add(user)
            db.session.commit()


def test_mail_is_sent_outside_the_request_path():
    """
    Der Versand darf den Request nicht mehr blockieren - sonst verraet
    die Antwortzeit, ob das Konto existiert.
    """
    auth_source = (PROJECT_ROOT / "src" / "api" / "auth.py").read_text(encoding="utf-8")
    assert "send_in_background(send_password_reset_email" in auth_source
    assert "send_in_background(send_verification_email" in auth_source

    mail_source = (PROJECT_ROOT / "src" / "utils" / "mail.py").read_text(encoding="utf-8")
    assert "def send_in_background(" in mail_source
    assert "threading.Thread" in mail_source


def test_forgot_password_response_is_identical_for_known_and_unknown(client):
    _make_user("timing_known@example.com")

    known = client.post("/api/auth/forgot-password",
                        json={"email": "timing_known@example.com"})
    unknown = client.post("/api/auth/forgot-password",
                          json={"email": "timing_unknown@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()


def test_forgot_password_timing_does_not_reveal_existence(client):
    """
    Der eigentliche Regressionstest fuer B3.

    Der Versand wird durch eine SPUERBARE Verzoegerung ersetzt. Liefe er
    weiterhin synchron, waere der Request fuer das existierende Konto um
    diese Verzoegerung langsamer. Laeuft er im Hintergrund, sind beide
    Antwortzeiten praktisch gleich.
    """
    _make_user("timing_measured@example.com")

    delay = 0.4

    def _slow_send(*args, **kwargs):
        time.sleep(delay)
        return True

    with patch("src.api.auth.send_password_reset_email", side_effect=_slow_send):
        start = time.perf_counter()
        client.post("/api/auth/forgot-password",
                    json={"email": "timing_measured@example.com"})
        known_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        client.post("/api/auth/forgot-password",
                    json={"email": "timing_absent@example.com"})
        unknown_elapsed = time.perf_counter() - start

    # Grosszuegige Schwelle: es geht um "blockiert der Versand den
    # Request?", nicht um Mikrosekunden. Synchron waere die Differenz
    # >= delay; im Hintergrund liegt sie weit darunter.
    assert known_elapsed - unknown_elapsed < delay / 2, (
        f"Antwortzeit verraet Kontoexistenz: bekannt {known_elapsed:.3f}s "
        f"vs unbekannt {unknown_elapsed:.3f}s"
    )


def test_resend_verification_does_not_leak_via_status_code(client):
    _make_user("timing_resend@example.com")

    known = client.post("/api/auth/resend-verification",
                        json={"email": "timing_resend@example.com"})
    unknown = client.post("/api/auth/resend-verification",
                          json={"email": "timing_nobody@example.com"})

    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()


# ---------------------------------------------------------------------------
# B4 - PDF-Ressourcen
# ---------------------------------------------------------------------------

def test_pdf_page_budget_is_defined_and_enforced():
    assert main_app.PDF_MAX_TOTAL_PAGES == 1500

    source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    # Die Pruefung muss VOR dem teuren append stehen.
    assert "len(writer.pages) + len(reader.pages) > PDF_MAX_TOTAL_PAGES" in code

    check_at = code.index("PDF_MAX_TOTAL_PAGES:") if "PDF_MAX_TOTAL_PAGES:" in code else -1
    guard_at = code.index("len(writer.pages) + len(reader.pages)")
    append_at = code.index("writer.append(reader)")
    assert guard_at < append_at, "Seitenpruefung erfolgt erst nach dem Anhaengen"


def test_pdf_merge_still_has_its_other_limits():
    """Die bestehenden Grenzen duerfen durch B4 nicht verlorengehen."""
    assert main_app.PDF_MAX_FILES == 40
    assert main_app.PDF_MAX_IMAGE_PIXELS == 50_000_000
    assert main_app.app.config["MAX_CONTENT_LENGTH"] == 50 * 1024 * 1024

    from PIL import Image
    assert Image.MAX_IMAGE_PIXELS == main_app.PDF_MAX_IMAGE_PIXELS


# ---------------------------------------------------------------------------
# B5 - Pillow-Decoder-Angriffsflaeche
# ---------------------------------------------------------------------------

def _minimal_fits_bytes():
    """
    Kleinste gueltige FITS-Datei.

    FITS ist eines der Formate, dessen Pillow-Decoder eine offene
    Dekompressionsbomben-Schwachstelle hat (behoben erst ab Pillow 12.x,
    das Python >= 3.10 verlangt). FootSim bietet FITS nirgends an - der
    Decoder ist trotzdem erreichbar, solange Image.open() das Format am
    Inhalt bestimmen darf.
    """
    cards = [
        b"SIMPLE  =                    T",
        b"BITPIX  =                    8",
        b"NAXIS   =                    2",
        b"NAXIS1  =                   10",
        b"NAXIS2  =                   10",
        b"END",
    ]
    header = b"".join(card.ljust(80) for card in cards).ljust(2880)
    return header + b"\x00" * 2880


def test_pillow_would_open_foreign_format_without_the_restriction():
    """
    Zeigt, dass die Gefahr echt ist und nicht theoretisch: ohne
    formats= oeffnet Pillow die FITS-Datei anstandslos - die Endung
    .png haette daran nichts geaendert.
    """
    import io
    from PIL import Image

    image = Image.open(io.BytesIO(_minimal_fits_bytes()))
    assert image.format == "FITS"


def test_pdf_convert_image_only_allows_jpeg_and_png(tmp_path):
    assert main_app.PDF_ALLOWED_IMAGE_FORMATS == ["JPEG", "PNG"]

    # Als .png getarnte FITS-Datei - genau der Weg an der
    # Endungs-Allowlist vorbei.
    disguised = tmp_path / "urlaub.png"
    disguised.write_bytes(_minimal_fits_bytes())

    with pytest.raises(Exception) as excinfo:
        main_app.pdf_convert_image(str(disguised), str(tmp_path / "out.pdf"))
    assert "UnidentifiedImageError" in type(excinfo.value).__name__


def test_pdf_merge_rejects_disguised_image_over_http(client, tmp_path):
    """Der Schutz muss auch auf dem echten Weg durch die Route greifen."""
    import io

    response = client.post(
        "/tools/pdf/merge",
        data={"files": (io.BytesIO(_minimal_fits_bytes()), "urlaub.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "urlaub.png" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# B7 - CSRF beim PDF-Upload
# ---------------------------------------------------------------------------
#
# /tools/pdf/merge ist ein mutierender POST und wird von CSRFProtect
# geschuetzt. Das Frontend schickte jedoch KEIN Token mit - der Server
# antwortete deshalb mit 400 und das Werkzeug war unbenutzbar. Die
# uebrigen Tests liefen mit WTF_CSRF_ENABLED=False und konnten das nicht
# bemerken.
#
# Diese Tests laufen deshalb bewusst MIT eingeschalteter CSRF-Pruefung.
# Die Loesung war, das Token mitzuschicken - nicht, die Route
# auszunehmen. Beide Richtungen werden hier festgehalten.

@pytest.fixture(scope="function")
def csrf_client():
    """Testclient mit CSRF-Pruefung wie in Produktion."""
    original_testing = main_app.app.config.get("TESTING")
    original_csrf = main_app.app.config.get("WTF_CSRF_ENABLED")
    main_app.app.config["TESTING"] = False
    main_app.app.config["WTF_CSRF_ENABLED"] = True
    try:
        with main_app.app.test_client() as client:
            yield client
    finally:
        main_app.app.config["TESTING"] = original_testing
        main_app.app.config["WTF_CSRF_ENABLED"] = original_csrf


def _png_bytes():
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (12, 34, 56)).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def test_pdf_page_exposes_a_csrf_token(csrf_client):
    page = csrf_client.get("/tools/pdf")
    assert page.status_code == 200
    assert 'name="csrf-token"' in page.get_data(as_text=True), (
        "Ohne dieses Meta-Tag kann das Frontend kein Token mitschicken"
    )


def test_pdf_merge_succeeds_with_csrf_token(csrf_client):
    """Der eigentliche Regressionstest: das Werkzeug muss benutzbar sein."""
    page = csrf_client.get("/tools/pdf")
    match = re.search(r'name="csrf-token" content="([^"]+)"',
                      page.get_data(as_text=True))
    assert match, "kein CSRF-Token in der Seite"

    response = csrf_client.post(
        "/tools/pdf/merge",
        data={"files": (_png_bytes(), "echt.png")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": match.group(1)},
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    assert response.headers["Content-Type"] == "application/pdf"


def test_pdf_merge_still_rejects_requests_without_csrf_token(csrf_client):
    """Der Schutz darf durch die Korrektur nicht verlorengehen."""
    csrf_client.get("/tools/pdf")
    response = csrf_client.post(
        "/tools/pdf/merge",
        data={"files": (_png_bytes(), "echt.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_no_auth_or_upload_route_is_csrf_exempt():
    """
    Die Korrektur haette auch per csrf.exempt erfolgen koennen - das
    waere die falsche Richtung gewesen und wird hier ausgeschlossen.
    """
    for name in ("app.py", "src/api/auth.py"):
        source = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        assert "csrf.exempt" not in code, f"CSRF-Exemption in {name}"


def test_genuine_png_still_merges(client, tmp_path):
    """Gegenprobe: echte Bilder duerfen nicht mit abgewiesen werden."""
    import io
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (12, 34, 56)).save(buffer, format="PNG")
    buffer.seek(0)

    response = client.post(
        "/tools/pdf/merge",
        data={"files": (buffer, "echt.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:300]


# ---------------------------------------------------------------------------
# B8 - Service Worker: keine sensiblen Antworten im Cache
# ---------------------------------------------------------------------------

def _sw_source():
    return (PROJECT_ROOT / "static" / "sw.js").read_text(encoding="utf-8")


def test_service_worker_does_not_precache_the_csrf_bearing_index():
    """
    templates/index.html traegt <meta name="csrf-token">. Stand die
    Startseite in STATIC_ASSETS, landete dieses sessiongebundene Token
    dauerhaft im Cache Storage - einem Speicher, der pro Herkunft geteilt
    wird, nicht pro Benutzer.
    """
    source = _sw_source()
    start = source.index("const STATIC_ASSETS")
    assets_block = source[start:source.index("]", start)]

    assert '"/?lang=de"' not in assets_block
    assert '"/?lang=en"' not in assets_block
    # Die Offline-Seite traegt kein Token und bleibt vorgecacht.
    assert '"/offline?lang=de"' in assets_block


def test_index_template_is_the_reason_and_still_carries_the_token():
    """
    Haelt die Begruendung des Tests oben an die Wirklichkeit gebunden:
    verschwindet das Token je aus index.html, ist der Grund entfallen.
    """
    index = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'name="csrf-token"' in index


def test_service_worker_never_caches_html():
    """
    HTML dieser Herkunft traegt entweder ein CSRF-Token oder
    benutzerbezogene Inhalte. Der Laufzeit-Cache muss es auslassen.
    """
    source = _sw_source()
    assert 'contentType.includes("text/html")' in source

    # Die Pruefung muss VOR dem cache.put stehen, sonst wirkt sie nicht.
    guard_at = source.index('contentType.includes("text/html")')
    put_at = source.index("cache.put(event.request")
    assert guard_at < put_at, "HTML-Sperre greift erst nach dem Schreiben"


def test_service_worker_cache_version_was_raised():
    """
    Ohne neue Cache-Version behalten bestehende Installationen den alten
    Cache samt gespeichertem Token - der activate-Handler loescht nur
    Caches mit ABWEICHENDEM Namen.
    """
    match = re.search(r'CACHE_NAME = "footsim-v(\d+)"', _sw_source())
    assert match, "CACHE_NAME nicht gefunden"
    assert int(match.group(1)) >= 29


def test_api_routes_stay_uncached():
    """Bestehender Schutz darf nicht verlorengehen."""
    source = _sw_source()
    start = source.index("const API_ROUTES")
    block = source[start:source.index("]", start)]
    assert '"/api/"' in block
    assert '"/tools/pdf/merge"' in block


# ---------------------------------------------------------------------------
# B9 - Lokale Browserdaten bei Logout und Kontoloeschung
# ---------------------------------------------------------------------------

def _script_source():
    return (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")


def test_account_local_data_is_cleared_on_logout_and_deletion():
    source = _script_source()
    assert "function clearAccountLocalData(" in source

    # An allen drei Stellen, an denen ein Konto verlassen wird.
    assert source.count("clearAccountLocalData();") >= 3


def test_cleared_keys_are_account_bound_only():
    """
    Sprache und Theme gehoeren zum Geraet, nicht zum Konto. Wer sich
    abmeldet, darf die App nicht in einer anderen Sprache wiederfinden.
    """
    source = _script_source()
    start = source.index("function clearAccountLocalData(")
    body = source[start:source.index("\n}", start)]

    assert "unverified_email" in body, "personenbezogener Schluessel fehlt"
    assert "ONBOARDING_KEY" in body

    assert '"theme"' not in body, "Theme ist eine Geraeteeinstellung"
    assert "footsim_lang" not in body, "Sprache ist eine Geraeteeinstellung"
    assert "localStorage.clear()" not in body, "zu grob - loescht auch Geraetedaten"


def test_unverified_email_is_the_key_that_mattered():
    """Bindet den Test oben an den tatsaechlichen Grund."""
    source = _script_source()
    assert "localStorage.setItem('unverified_email'" in source


# ---------------------------------------------------------------------------
# B10 - Entwicklungsserver
# ---------------------------------------------------------------------------

def test_dev_server_does_not_hardcode_debug_and_public_bind():
    """
    debug=True schaltet die interaktive Werkzeug-Konsole frei; zusammen
    mit host="0.0.0.0" war sie fuer jeden im selben Netz erreichbar.
    """
    source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    main_block = code[code.index('if __name__ == "__main__":'):]

    assert "debug=True" not in main_block
    assert '"0.0.0.0"' not in main_block
    assert 'os.environ.get("FOOTSIM_DEV_HOST"' in main_block
    # In Produktion darf der Entwicklungsserver gar nicht erst starten.
    assert "IS_PRODUCTION" in main_block
