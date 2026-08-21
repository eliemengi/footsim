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

def test_docker_compose_has_no_plaintext_credentials():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    # Die frueher eingecheckten Werte duerfen nicht zurueckkehren.
    assert "footsim_pass" not in compose
    assert "POSTGRES_PASSWORD: footsim" not in compose

    # Alle drei Werte kommen aus der Umgebung, und zwar OHNE Fallback:
    # '${VAR:-standard}' waere wieder ein Wert im Repo, '${VAR:?meldung}'
    # bricht stattdessen mit klarer Meldung ab.
    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert f"${{{var}:?" in compose, var
        assert f"${{{var}:-" not in compose, var


def test_env_example_contains_only_placeholders():
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "footsim_pass" not in example
    assert "footsim_user:footsim_pass" not in example

    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
                "FOOTSIM_ENV", "FOOTSIM_TRUSTED_PROXY_HOPS"):
        assert var in example, var


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
