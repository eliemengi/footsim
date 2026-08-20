from flask import Flask, jsonify, render_template, request, send_file, g, make_response
import os
from dotenv import load_dotenv

load_dotenv()
import io
import tempfile
import shutil
import requests
from datetime import date, datetime
from werkzeug.utils import secure_filename
from pypdf import PdfWriter, PdfReader
from PIL import Image

from src.predict.matches_to_predict import (
    MATCHES_TO_PREDICT_EL
)

from src.predict.cl_match_sim import simulate_cl_league_phase_match

from src.api.league_api import (
    ApiUnavailable,
    get_matchday_matches,
    get_season_info,
    get_current_season,
    is_current_season,
    get_standings,
    get_scorers,
    get_matchday_match_options,
    get_finished_season_matches,
    get_competition_teams,
    get_cup_matches,
    get_all_matches,
    get_cl_league_phase_match_options,
    get_cl_knockout_matches,
)

from src.features.league_stats import build_league_profile, build_comparison
from src.features import cl_stats
from src.predict.season_sim import simulate_season
from src.predict.fixture_plan import build_season_plan
from src.predict.cl_fixture_plan import build_cl_league_phase_plan
from src.predict.cl_season_sim import simulate_cl_league_phase, VALID_MODES as CL_SIM_MODES
from src.predict.league_match_sim import simulate_league_match
from src.api import apisports_api
from src.api import live_api
from src.api import team_detail
from src.api.apisports_api import ApisportsUnavailable, ApisportsRateLimit
from src.utils import cache
from src.utils.disk_cache import disk_cached_call, read_entry as disk_read_entry
from src.data import transfer_loader
from src.data.player_stats_loader import get_player_target_league_stats
from src.features import transfer_comparison

# --- Big Games (Block F1) ---
from src.data import live_player_search
from src.data import uefa_coefficients
from src.data.big_games_loader import (
    build_big_games_profile as big_games_profile,
    search_big_games_players as big_games_search_players,
)

# --- Spielervergleich (Phase 3) ---
from src.data.player_compare_loader import (
    search_players as player_search_players,
    get_player_season_profile,
    get_player_trophies,
    build_comparison as build_player_comparison,
    normalize_scope as normalize_competition_scope,
    COMPETITION_SCOPES,
    SCOPE_LABELS,
    SCOPE_HINTS,
    DEFAULT_SCOPE,
    COMPARE_LEAGUE_CODES,
    COMPARE_LEAGUE_LABELS,
    MIN_QUERY_LENGTH as PLAYER_MIN_QUERY_LENGTH,
)
from src.data.percentile_engine import (
    load_snapshot as load_percentile_snapshot,
    DEFAULT_MIN_MINUTES,
    min_minutes_for_scope,
)
from src.data.player_pool import load_scatter_points
from src.data.national_competitions import tournament_scope_availability, TOURNAMENT_SCOPE_LEAGUE_IDS
from src.data.player_metrics import (
    METRICS,
    POSITION_GROUPS,
    POSITION_LABELS,
    metrics_for_position,
    compute_metric,
    describe_metric,
)
# disk_cached_call ist bereits oben importiert (Zeile 43), keine erneute nötig
from src.data.player_metrics import POSITION_LABELS
from src.i18n import (
    LANGUAGE_COOKIE,
    normalize_supported_locale,
    resolve_locale,
    translate,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# Database Configuration
db_url = os.environ.get("DATABASE_URL")

if not db_url and not app.config.get("TESTING"):
    raise RuntimeError("DATABASE_URL environment variable is required but not set.")

if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

if db_url and "postgres" in db_url:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
    }

# =============================================================================
#  BETRIEBSMODUS
#
#  Frueher entschied an mehreren Stellen ein direkter Stringvergleich
#  ueber sicherheitsrelevantes Verhalten:
#
#      is_production = os.environ.get("FLASK_ENV") == "production"     app.py
#      mock_mail     = os.environ.get("FLASK_ENV") != "production"     mail.py
#
#  Ein Tippfehler ("Produktion", "PRODUCTION", nicht gesetzt) fuehrte
#  damit lautlos zu einem Session-Cookie OHNE Secure-Flag - bei 30 Tagen
#  Lebensdauer. Die beiden Vergleiche waren zudem gegenlaeufig, sodass
#  derselbe Tippfehler im einen Pfad still und im anderen sichtbar war.
#
#  Jetzt gibt es genau eine Quelle: FOOTSIM_ENV (Fallback FLASK_ENV) mit
#  einer geschlossenen Liste gueltiger Werte. Ein unbekannter Wert ist
#  ein Fehler und wird nicht stillschweigend als Entwicklung gedeutet.
# =============================================================================

VALID_ENVIRONMENTS = ("development", "testing", "production")


def _resolve_environment():
    raw = (os.environ.get("FOOTSIM_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower()

    if not raw:
        return "development"

    if raw not in VALID_ENVIRONMENTS:
        raise RuntimeError(
            f"Unbekannter Betriebsmodus {raw!r}. Erlaubt: {', '.join(VALID_ENVIRONMENTS)}. "
            "Ein unbekannter Wert wird bewusst NICHT als 'development' behandelt, "
            "weil davon Secure-Cookies und der echte Mailversand abhaengen."
        )
    return raw


FOOTSIM_ENV = _resolve_environment()
IS_PRODUCTION = FOOTSIM_ENV == "production"
app.config["FOOTSIM_ENV"] = FOOTSIM_ENV
app.config["IS_PRODUCTION"] = IS_PRODUCTION


# =============================================================================
#  VERTRAUENSMODELL FUER REVERSE PROXIES
#
#  Ohne ProxyFix ist request.remote_addr hinter nginx fuer JEDEN Client
#  127.0.0.1. Flask-Limiter (key_func=get_remote_address) wirft dann alle
#  Nutzer in denselben Zaehler: ein einzelner Angreifer verbraucht das
#  Login-Limit fuer die gesamte Anwendung.
#
#  ProxyFix darf aber nur aktiv sein, wenn tatsaechlich ein
#  vertrauenswuerdiger Proxy davor sitzt - sonst darf sich jeder Client
#  seine "IP" per X-Forwarded-For selbst aussuchen und das Limit ist
#  schlechter als vorher. Deshalb bewusst opt-in ueber eine
#  Umgebungsvariable statt automatisch.
#
#  Verifiziert fuer das FootSim-Deployment (nginx sites-enabled/footsim):
#      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#  $proxy_add_x_forwarded_for HAENGT die echte $remote_addr HINTEN an.
#  ProxyFix mit x_for=1 liest den RECHTESTEN Eintrag - also genau den von
#  nginx gesetzten Wert. Ein vom Client mitgeschickter XFF-Header landet
#  weiter links und wird ignoriert. Genau ein Hop, nicht mehr.
# =============================================================================

try:
    TRUSTED_PROXY_HOPS = int(os.environ.get("FOOTSIM_TRUSTED_PROXY_HOPS", "0"))
except ValueError:
    raise RuntimeError(
        "FOOTSIM_TRUSTED_PROXY_HOPS muss eine ganze Zahl sein "
        "(0 = kein Proxy, 1 = genau ein vertrauenswuerdiger Reverse Proxy)."
    )

if TRUSTED_PROXY_HOPS < 0:
    raise RuntimeError("FOOTSIM_TRUSTED_PROXY_HOPS darf nicht negativ sein.")

if TRUSTED_PROXY_HOPS > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
        # Host, Port und Prefix werden NICHT uebernommen: sie werden hier
        # nicht gebraucht und jedes zusaetzlich vertraute Feld ist eine
        # weitere Stelle, an der ein Header etwas umschreiben koennte.
        x_host=0,
        x_port=0,
        x_prefix=0,
    )

app.config["TRUSTED_PROXY_HOPS"] = TRUSTED_PROXY_HOPS

# Auth / Session Configuration
secret_key = os.environ.get("SECRET_KEY")
is_production = IS_PRODUCTION

if not secret_key and not app.config.get("TESTING"):
    if IS_PRODUCTION:
        raise ValueError("SECRET_KEY is missing. Production requires a secure SECRET_KEY in the environment.")
    else:
        # We only warn and fallback if not in testing and not in production
        import warnings
        warnings.warn("SECRET_KEY is not set in environment. Using unsafe dev default.")
        secret_key = "dev-unsafe-secret-key"

# Der Dev-Fallback darf niemals in Produktion aktiv werden - auch dann
# nicht, wenn SECRET_KEY zwar gesetzt, aber genau dieser Platzhalter ist.
if IS_PRODUCTION and secret_key in (None, "", "dev-unsafe-secret-key", "test-secret-key"):
    raise ValueError(
        "SECRET_KEY ist in Produktion nicht sicher gesetzt. Der Start wird "
        "abgebrochen, statt mit einem bekannten Schluessel weiterzulaufen."
    )

app.config["SECRET_KEY"] = secret_key or "test-secret-key"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Require HTTPS in production
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
# Sessions expire after 30 days
from datetime import timedelta
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Email / Resend Configuration
resend_key = os.environ.get("RESEND_API_KEY")
if is_production and not resend_key:
    import warnings
    warnings.warn("RESEND_API_KEY is not set in production. Emails will not be sent.")
app.config["RESEND_API_KEY"] = resend_key

base_url = os.environ.get("BASE_URL")
if base_url and base_url.endswith("/"):
    base_url = base_url[:-1]
app.config["BASE_URL"] = base_url or "http://127.0.0.1:5000"
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "FootSim <noreply@footsim.de>")

from src.models.extensions import db, migrate, csrf, limiter
from flask_wtf.csrf import CSRFError
db.init_app(app)
migrate.init_app(app, db)
csrf.init_app(app)
limiter.init_app(app)

from src.api.auth import auth_bp
app.register_blueprint(auth_bp, url_prefix="/api/auth")

def _request_locale():
    """Resolve the locale once per request.

    ``?lang=`` is an explicit, shareable selection.  The first-party cookie
    is the persisted browser choice.  JavaScript mirrors the same preference
    in localStorage for a fast client-side first paint, then reloads with the
    query parameter when a user changes language.
    """

    if hasattr(g, "footsim_locale"):
        return g.footsim_locale

    explicit = normalize_supported_locale(request.args.get("lang"))
    persisted = normalize_supported_locale(request.cookies.get(LANGUAGE_COOKIE))
    g.footsim_locale = resolve_locale(
        explicit=explicit,
        persisted=persisted,
        browser_language=request.headers.get("Accept-Language"),
    )
    g.footsim_explicit_locale = explicit
    return g.footsim_locale


@app.context_processor
def inject_i18n_context():
    locale = _request_locale()
    return {
        "locale": locale,
        "t": lambda key, **params: translate(key, locale, **params),
    }


@app.after_request
def apply_security_headers(response):
    """
    Nicht brechende Basis-Sicherheitsheader.

    Bewusst KEINE Content-Security-Policy und KEIN HSTS an dieser
    Stelle:

    - Eine strikte CSP wuerde das bestehende Frontend mit seinen
      Inline-Handlern und den externen Wappenhosts
      (crests.football-data.org, media.api-sports.io) sofort
      beschaedigen. Sie gehoert erst nach einem Inventar und einer
      Report-Only-Phase aktiviert.
    - HSTS darf ausschliesslich auf einer verifiziert vollstaendig
      per HTTPS erreichbaren Domain gesetzt werden. Ein zu frueher
      max-age sperrt Besucher aus, falls TLS ausfaellt. Der Header
      gehoert deshalb in die nginx-Konfiguration, wo der TLS-Zustand
      tatsaechlich bekannt ist.

    setdefault() statt Zuweisung: sollte nginx dieselben Header bereits
    liefern, entstehen keine widersprechenden Doppelwerte.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    )

    # Authentifizierte bzw. personenbezogene Antworten gehoeren in
    # keinen geteilten Cache.
    if request.path.startswith("/api/auth/"):
        response.headers.setdefault("Cache-Control", "no-store")

    return response


@app.after_request
def persist_explicit_locale(response):
    """Persist only a deliberate URL selection, never a guessed locale."""

    explicit = getattr(g, "footsim_explicit_locale", None)
    if explicit:
        response.set_cookie(
            LANGUAGE_COOKIE,
            explicit,
            max_age=60 * 60 * 24 * 365,
            samesite="Lax",
            secure=request.is_secure,
        )
    return response


def current_locale():
    return _request_locale()


def ui_text(key, **params):
    return translate(key, current_locale(), **params)


# =============================================================================
#  KONFIGURATION
#
#  Das ist der einzige Block, den du im normalen Betrieb anfassen musst.
#  Alles darunter bleibt unveraendert.
# =============================================================================

# Wenn True, sind ALLE Spieltage sofort spielbar.
# Praktisch zum Testen oder wenn du die Sperre generell nicht mehr willst.
UNLOCK_ALL_MATCHDAYS = False

# Die Saison wird automatisch von football-data.org erkannt.
# Nur setzen, wenn du bewusst eine andere Saison erzwingen willst,
# zum Beispiel SEASON_OVERRIDE = 2025 fuer die Vorsaison.
SEASON_OVERRIDE = None

# Wie viele abgeschlossene Saisons zusaetzlich zur laufenden auswaehlbar sind.
# 1 bedeutet: laufende Saison plus die davor.
SEASON_HISTORY = 1

# Wettbewerb, dessen Saison als Bezugspunkt fuer die Auswahl dient.
SEASON_REFERENCE_CODE = "BL1"


LEAGUE_CONFIG = {
    "bl1": {
        "name": "Bundesliga",
        "api_code": "BL1",
        "country": "Deutschland",
        "total_matchdays": 34,

        # >>> HIER SPIELTAGE FREISCHALTEN <<<
        # Beispiele:
        #   [1]              nur Spieltag 1
        #   [1, 2, 3]        Spieltag 1 bis 3
        #   list(range(1, 6))  Spieltag 1 bis 5
        "unlocked_matchdays": [1],
    },
    "pl": {
        "name": "Premier League",
        "api_code": "PL",
        "country": "England",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "pd": {
        "name": "LaLiga",
        "api_code": "PD",
        "country": "Spanien",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "sa": {
        "name": "Serie A",
        "api_code": "SA",
        "country": "Italien",
        "total_matchdays": 38,
        "unlocked_matchdays": [1],
    },
    "fl1": {
        "name": "Ligue 1",
        "api_code": "FL1",
        "country": "Frankreich",
        "total_matchdays": 34,
        "unlocked_matchdays": [1],
    },
}


# Registrierung fuer /api/competitions (Anzeige, Verfuegbarkeit). Die
# Europa League laeuft weiterhin ueber die manuell gepflegten Paarungen
# in src/predict/matches_to_predict.py. Die Champions League ist seit
# Block B1 datengetrieben (siehe CL_LEAGUE_PHASE_CONFIG unten) und nutzt
# diese Datei nicht mehr.
CUP_CONFIG = {
    "cl": {
        "name": "Champions League",
        "api_code": "CL",
        "available": True,
        "coming_soon_text": "",
    },
    "el": {
        "name": "Europa League",
        "api_code": "EL",
        "available": False,
        "coming_soon_text": "Die Europa League wird spaeter freigeschaltet.",
    },
    "gsc": {
        "name": "German Super Cup",
        "api_code": "GSC",
        "available": False,
        "coming_soon_text": "",
    },
    "usc": {
        "name": "UEFA Super Cup",
        "api_code": "USC",
        "available": False,
        "coming_soon_text": "",
    },
    "facs": {
        "name": "Community Shield",
        "api_code": "FACS",
        "available": False,
        "coming_soon_text": "",
    },
}

# Champions-League-Ligaphase: eigene, kleine Konfiguration statt eines
# Eintrags in LEAGUE_CONFIG. Grund: LEAGUE_CONFIG bestimmt zugleich, was
# /api/competitions als "league" auflistet. Ein CL-Eintrag dort wuerde
# die Champions League doppelt anzeigen (einmal als Liga aus
# LEAGUE_CONFIG, einmal als Pokal aus CUP_CONFIG). Die Werte hier werden
# ausschliesslich von _resolve_competition_config() konsumiert, das die
# bestehenden Liga-Routen (Spieltage, Tabelle, Torjaeger, Spielsimulation)
# minimal-invasiv auch fuer "cl" nutzbar macht, ohne LEAGUE_CONFIG oder
# die fuenf Ligen selbst anzufassen.
CL_LEAGUE_PHASE_CONFIG = {
    "name": "Champions League",
    "api_code": "CL",
    "total_matchdays": 8,

    # >>> HIER SPIELTAGE FREISCHALTEN <<< (wie bei LEAGUE_CONFIG oben)
    "unlocked_matchdays": [1],
}

# =============================================================================
#  ENDE KONFIGURATION
# =============================================================================


def _resolve_competition_config(competition_code):
    """
    Liefert die Konfiguration eines spieltagsbasierten Wettbewerbs -
    die fuenf nationalen Ligen ODER die Champions-League-Ligaphase.

    Bewusst getrennt von einer Erweiterung von LEAGUE_CONFIG selbst: so
    bleibt das Verhalten fuer alle bestehenden Ligacodes (bl1, pl, pd,
    sa, fl1) unveraendert identisch zum bisherigen direkten
    LEAGUE_CONFIG.get(...)-Aufruf, und nur "cl" bekommt zusaetzlich eine
    Konfiguration.
    """
    config = LEAGUE_CONFIG.get(competition_code)
    if config:
        return config

    if competition_code == "cl":
        return CL_LEAGUE_PHASE_CONFIG

    return None


COMPETITION_MATCHES = {
    "el": MATCHES_TO_PREDICT_EL,
}

CREST_BASE_URL = "https://crests.football-data.org"

# Champions-League-Stage-Bezeichnungen fuer die K.-o.-Phase.
# Reihenfolge bestimmt die Sortierung in der UI.
CL_STAGE_ORDER = ["PLAYOFFS", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "FINAL"]
CL_STAGE_LABELS = {
    "PLAYOFFS": "Playoffs",
    "LAST_16": "Achtelfinale",
    "QUARTER_FINALS": "Viertelfinale",
    "SEMI_FINALS": "Halbfinale",
    "FINAL": "Finale",
}

COUNTRY_TEXT_KEYS = {
    "Deutschland": "country.germany",
    "England": "country.england",
    "Spanien": "country.spain",
    "Italien": "country.italy",
    "Frankreich": "country.france",
    "Europa": "country.europe",
}


def localized_country(country):
    """Translate only FootSim's known display-country values, never data names."""
    return ui_text(COUNTRY_TEXT_KEYS.get(country, "")) if country in COUNTRY_TEXT_KEYS else country


def localized_cl_stage(stage):
    """Return a stable stage-code translation with the legacy label as fallback."""
    return ui_text(f"clStage.{stage}") if stage in CL_STAGE_LABELS else CL_STAGE_LABELS.get(stage, stage)


def resolve_requested_season(raw_value):
    """
    Liest den Saisonparameter aus der Anfrage.

    Ohne Angabe gilt die laufende Saison. SEASON_OVERRIDE hat Vorrang,
    falls jemand bewusst eine Saison erzwingen will.
    """
    if SEASON_OVERRIDE is not None:
        return int(SEASON_OVERRIDE)

    if raw_value in (None, "", "current"):
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def build_season_options():
    """
    Liste der auswaehlbaren Saisons.
    Die laufende steht vorn und ist die Voreinstellung.
    """
    current = get_current_season(SEASON_REFERENCE_CODE)

    options = []

    for offset in range(0, SEASON_HISTORY + 1):
        year = current - offset
        options.append({
            "season": year,
            "label": f"{year}/{str(year + 1)[2:]}",
            "is_current": offset == 0,
            "is_complete": offset > 0,
            "description": ui_text("season.running") if offset == 0 else ui_text("season.completed"),
        })

    return options


def _cl_league_phase_status(season):
    """
    Datengetriebener Status der CL-Ligaphase fuer eine Saison.

    Ersetzt fuer CL die is_current_season()-Pruefung: die vergleicht nur
    eine Jahreszahl gegen CL's eigene, moeglicherweise nachlaufende
    Saison-Auto-Erkennung bei football-data (die CL-Competition-Ressource
    kann eine neue Saison spaeter als die Domestic-Ligen als "aktuell"
    fuehren). Eine abgeschlossene Saison - alle echten Ligaphasen-Spiele
    FINISHED - muss trotzdem immer alle Spieltage freigeben.

    Rueckgabe: (has_fixtures, is_complete)

    Bei einem Fehler (auch 404 fuer "diese Saison existiert dort noch
    nicht") gilt has_fixtures=False: lieber Spieltage sicher gesperrt
    lassen als faelschlich als verfuegbar zeigen, wenn wir nicht wissen,
    ob echte Daten existieren. get_all_matches faengt den erwartbaren
    CL-404-Fall bereits selbst ab (liefert dann []); dieses except greift
    nur noch fuer echte technische Fehler (Rate Limit, Netzwerk, ...).
    """
    try:
        matches = get_all_matches(CL_LEAGUE_PHASE_CONFIG["api_code"], season=season, only_finished=False)
    except ApiUnavailable:
        return False, False

    league_stage = [m for m in matches if m.get("stage") == "LEAGUE_STAGE"]
    has_fixtures = bool(league_stage)
    is_complete = has_fixtures and all(m.get("status") == "FINISHED" for m in league_stage)
    return has_fixtures, is_complete


def is_matchday_unlocked(competition_code, matchday, season=None):
    """
    Ein Spieltag ist spielbar, wenn er freigeschaltet wurde.

    Bei abgeschlossenen Saisons entfaellt die Sperre komplett. Dort sind
    alle Partien laengst gespielt, eine Sperre waere sinnlos.
    """
    config = _resolve_competition_config(competition_code)
    if not config:
        return False

    if competition_code == "cl":
        has_fixtures, is_complete = _cl_league_phase_status(season)
        if not has_fixtures:
            return False
        if is_complete:
            return True
        if UNLOCK_ALL_MATCHDAYS:
            return True
        return matchday in config["unlocked_matchdays"]

    if season is not None and not is_current_season(config["api_code"], season):
        return True

    if UNLOCK_ALL_MATCHDAYS:
        return True

    return matchday in config["unlocked_matchdays"]


def build_match_response(match_dict):
    matches = []

    for match_id, teams in match_dict.items():
        home_team, away_team = teams
        matches.append({
            "id": match_id,
            "home_team": home_team,
            "away_team": away_team,
            "label": f"{home_team} vs {away_team}"
        })

    return matches


def parse_league_codes(raw):
    """Liest die Ligaliste aus dem Parameter, entfernt Unbekanntes und Doppeltes."""
    codes = [c.strip().lower() for c in raw.split(",") if c.strip()]
    codes = [c for c in codes if c in LEAGUE_CONFIG]

    seen = set()
    return [c for c in codes if not (c in seen or seen.add(c))]


def api_error(error, status=503):
    return jsonify({
        "error": str(error),
        "code": "EXTERNAL_API_UNAVAILABLE"
    }), status


# =============================================================================
#  SEITEN
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/manifest.json")
def manifest():
    locale = current_locale()
    payload = {
        "name": "FootSim",
        "short_name": "FootSim",
        "description": ui_text("meta.description"),
        "start_url": f"/?lang={locale}",
        "display": "standalone",
        "background_color": "#0d1b30",
        "theme_color": "#0d1b30",
        "orientation": "portrait-primary",
        "lang": locale,
        "icons": [
            {
                "src": "/static/images/logofoot.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/images/logofoot.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
        "categories": ["sports", "entertainment"],
        "shortcuts": [
            {
                "name": ui_text("nav.simulation"),
                "short_name": ui_text("nav.simulation"),
                "description": ui_text("manifest.simulationDescription"),
                "url": f"/?mode=simulation&lang={locale}",
                "icons": [{"src": "/static/images/logofoot.png", "sizes": "192x192"}],
            },
            {
                "name": ui_text("manifest.compareName"),
                "short_name": ui_text("manifest.compareShortName"),
                "description": ui_text("manifest.compareDescription"),
                "url": f"/?mode=compare&lang={locale}",
                "icons": [{"src": "/static/images/logofoot.png", "sizes": "192x192"}],
            },
        ],
    }
    response = make_response(jsonify(payload))
    response.mimetype = "application/manifest+json"
    response.headers["Vary"] = "Cookie, Accept-Language"
    return response


@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/impressum")
def impressum():
    return render_template("impressum.html")


@app.route("/datenschutz")
def datenschutz():
    return render_template("datenschutz.html")


@app.route("/kontakt")
def kontakt():
    return render_template("kontakt.html")


@app.route("/feedback")
def feedback():
    return render_template("feedback.html")


@app.route("/offline")
def offline():
    return render_template("offline.html")


# =============================================================================
#  API: SAISONS
# =============================================================================

@app.route("/api/seasons", methods=["GET"])
def api_seasons():
    return jsonify(build_season_options())


# =============================================================================
#  API: WETTBEWERBE
# =============================================================================

@app.route("/api/competitions", methods=["GET"])
def get_competitions():
    season = resolve_requested_season(request.args.get("season"))

    competitions = []

    for code, config in LEAGUE_CONFIG.items():
        past_season = season is not None and not is_current_season(config["api_code"], season)

        if past_season:
            sub = ui_text("availability.completedSeason")
        elif UNLOCK_ALL_MATCHDAYS:
            sub = ui_text("availability.allMatchdays")
        else:
            unlocked = config["unlocked_matchdays"]
            if not unlocked:
                sub = ui_text("availability.noMatchdays")
            elif len(unlocked) == 1:
                sub = ui_text("availability.matchday", matchday=unlocked[0])
            else:
                sub = ui_text(
                    "availability.matchdayRange",
                    **{"from": min(unlocked), "to": max(unlocked)},
                )

        competitions.append({
            "code": code,
            "name": config["name"],
            "country": localized_country(config["country"]),
            "type": "league",
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": True,
            "subtitle": sub,
            "coming_soon_text": "",
        })

    for code, config in CUP_CONFIG.items():
        if code in ("gsc", "usc", "facs"):
            continue
            
        # Champions League bekommt einen eigenen Typ, damit das Frontend
        # den hybriden Ligaphase-/K.-o.-Flow sauber erkennen kann, ohne
        # competition.code === "cl"-Sonderfaelle zu streuen.
        comp_type = "cl" if code == "cl" else "cup"

        competitions.append({
            "code": code,
            "name": config["name"],
            "country": localized_country("Europa"),
            "type": comp_type,
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": config["available"],
            "subtitle": ui_text(
                "availability.available" if config["available"] else "availability.comingSoon"
            ),
            "coming_soon_text": (
                ui_text("competition.europaLeagueComingSoon")
                if code == "el" and config["coming_soon_text"] else config["coming_soon_text"]
            ),
        })

    return jsonify(competitions)


# =============================================================================
#  API: SPIELTAGE
# =============================================================================

@app.route("/api/matchdays", methods=["GET"])
def get_matchdays():
    """
    Liefert ALLE Spieltage der Saison.
    Gesperrte Spieltage sind sichtbar, aber nicht anwaehlbar.
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    config = _resolve_competition_config(competition_code)

    if not config:
        return jsonify([])

    try:
        info = get_season_info(config["api_code"])
        current = info.get("current_matchday") or 1
        is_running = is_current_season(config["api_code"], season)
    except ApiUnavailable:
        current = 1
        is_running = True

    # CL-Ligaphase: is_matchday_unlocked() prueft fuer CL bereits echte
    # Ligaphasen-Daten statt nur is_current_season() (siehe dort). Hier nur
    # noch fuer die Nachricht gebraucht, ob ueberhaupt Spiele existieren.
    cl_has_fixtures = True
    if competition_code == "cl":
        cl_has_fixtures, _ = _cl_league_phase_status(season)

    matchdays = []

    for day in range(1, config["total_matchdays"] + 1):
        unlocked = is_matchday_unlocked(competition_code, day, season)

        if competition_code == "cl" and not cl_has_fixtures:
            message = ui_text("matchday.clUnavailable")
        else:
            message = "" if unlocked else ui_text("matchday.locked")

        matchdays.append({
            "matchday": day,
            "available": unlocked,
            "label": ui_text("matchday.label", matchday=day),
            "is_current": is_running and day == current,
            "message": message,
        })

    return jsonify(matchdays)


# =============================================================================
#  API: SPIELE
# =============================================================================

@app.route("/api/matches", methods=["GET"])
def get_matches():
    """
    Spieltags-Spiele fuer die fuenf nationalen Ligen UND die
    Champions-League-Ligaphase.

    Domestic-Ligen laufen ueber den bewaehrten generischen Pfad
    (get_matchday_match_options). Die CL-Ligaphase nutzt den in B2
    eingefuehrten stage-gefilterten Loader (get_cl_league_phase_match_options),
    der explizit stage=LEAGUE_STAGE an football-data sendet und die
    Saison der Response validiert.
    """
    competition_code = request.args.get("competition", "cl").lower()
    season = resolve_requested_season(request.args.get("season"))

    config = _resolve_competition_config(competition_code)

    if not config:
        return jsonify(build_match_response(COMPETITION_MATCHES.get(competition_code, {})))

    try:
        matchday = int(request.args.get("matchday", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Ungueltiger Spieltag"}), 400

    if not is_matchday_unlocked(competition_code, matchday, season):
        return jsonify([])

    try:
        if competition_code == "cl":
            matches = get_cl_league_phase_match_options(matchday, season=season)
        else:
            matches = get_matchday_match_options(
                competition_code=competition_code,
                api_code=config["api_code"],
                matchday=matchday,
                season=season,
            )
        return jsonify(matches)
    except ApiUnavailable as error:
        return api_error(error)


@app.route("/api/cl-stages", methods=["GET"])
def api_cl_stages():
    """
    Liefert die K.-o.-Runden, die fuer die gewaehlte Saison TATSAECHLICH
    Spiele haben - nie mehr statisch vorgegebene Achtelfinale-/
    Viertelfinale-/Halbfinale-Elemente, bevor die Daten dafuer existieren.

    Fragt football-data.org einmal nach allen Spielen der Saison
    (gecacht) und liest daraus, welche stage-Werte jenseits der
    Ligaphase vorkommen. Vor einer Auslosung ist die Antwort schlicht
    eine leere Liste - das Frontend zeigt dann einen Empty-State statt
    erfundener Runden.
    """
    season = resolve_requested_season(request.args.get("season"))
    cl_api_code = CL_LEAGUE_PHASE_CONFIG["api_code"]

    try:
        matches = get_all_matches(cl_api_code, season=season, only_finished=False)
    except ApiUnavailable as error:
        return api_error(error)

    seen_stages = {
        match.get("stage")
        for match in matches
        if match.get("stage") and match.get("stage") != "LEAGUE_STAGE"
    }

    ordered = [stage for stage in CL_STAGE_ORDER if stage in seen_stages]
    ordered += sorted(stage for stage in seen_stages if stage not in CL_STAGE_ORDER)

    return jsonify({
        "season": season,
        "stages": [
            {"stage": stage, "label": localized_cl_stage(stage)}
            for stage in ordered
        ],
    })


@app.route("/api/cl-knockout", methods=["GET"])
def api_cl_knockout():
    """
    Matches einer bestimmten Champions-League-K.-o.-Stage.

    Aufruf: /api/cl-knockout?season=2025&stage=LAST_16

    Gruppiert die Matches zu Ties: zwei Matches mit denselben Teams
    (home/away vertauscht) sind Hin- und Rueckspiel desselben Duells.
    Das Finale oder andere Single-Leg-Runden haben nur ein Match pro Tie.

    Die Saison wird gegen die Response validiert (kein stiller Fallback
    auf die currentSeason). Ohne echte Daten kommt ein leeres Ergebnis.
    """
    season = resolve_requested_season(request.args.get("season"))
    stage = request.args.get("stage", "").upper()

    if not stage:
        return jsonify({"error": "stage-Parameter fehlt"}), 400

    try:
        raw_matches = get_cl_knockout_matches(stage, season=season)
    except ApiUnavailable as error:
        return api_error(error)

    if not raw_matches:
        return jsonify({
            "season": season,
            "stage": stage,
            "label": localized_cl_stage(stage),
            "ties": [],
        })

    # Matches zu Ties gruppieren: zwei Matches desselben Duells (Teams
    # vertauscht) gehoeren zusammen. Sortierung: Leg 1 (frueher) zuerst.
    ties_map = {}

    for match in raw_matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}
        home_id = home.get("id")
        away_id = away.get("id")

        if home_id is None or away_id is None:
            continue

        # Kanonischer Tie-Key: kleinere ID zuerst, damit Hin-/Rueckspiel
        # denselben Key bekommen.
        tie_key = tuple(sorted([home_id, away_id]))

        score = (match.get("score") or {}).get("fullTime") or {}

        match_entry = {
            "utc_date": match.get("utcDate"),
            "status": match.get("status"),
            "home_team": home.get("name") or "Unbekannt",
            "away_team": away.get("name") or "Unbekannt",
            "home_id": home_id,
            "away_id": away_id,
            "home_crest": home.get("crest"),
            "away_crest": away.get("crest"),
            "home_score": score.get("home"),
            "away_score": score.get("away"),
        }

        if tie_key not in ties_map:
            ties_map[tie_key] = []
        ties_map[tie_key].append(match_entry)

    # Innerhalb jedes Ties chronologisch sortieren (Leg 1 zuerst).
    ties = []
    for legs in ties_map.values():
        legs.sort(key=lambda m: m.get("utc_date") or "")
        ties.append({"legs": legs})

    return jsonify({
        "season": season,
        "stage": stage,
        "label": localized_cl_stage(stage),
        "ties": ties,
    })


# =============================================================================
#  API: TABELLE
# =============================================================================

@app.route("/api/personalization/teams", methods=["GET"])
def api_personalization_teams():
    """
    Vereine eines Wettbewerbs fuer die Lieblingsteam-Auswahl.

    Bewusst NICHT /api/standings: dessen Team-IDs stammen von
    football-data.org, waehrend Teamprofil (src/api/team_detail.py) und
    Live (src/api/live_api.py) ausschliesslich mit API-Football-IDs
    arbeiten. Ein hier gewaehltes Team soll spaeter anklickbar sein und
    in Live wiedererkannt werden - also muss die Auswahl von vornherein
    aus demselben Namensraum kommen. Ein Mapping zwischen beiden Raeumen
    gibt es im Projekt bewusst nicht.

    Die Saison wird wie ueberall sonst aufgeloest (resolve_requested_season
    -> laufende Saison), NICHT aus apisports_api.CURRENT_SEASON: diese
    Konstante bedient Torjaeger/Verletzungen/Spielersuche und liegt hinter
    der laufenden Tabellensaison zurueck.
    """
    from src.api.apisports_api import LEAGUE_IDS

    competition_code = (request.args.get("competition") or "").lower().strip()
    config = _resolve_competition_config(competition_code)
    league_id = LEAGUE_IDS.get(competition_code)

    if not config or league_id is None:
        return jsonify({"error": "Unbekannter Wettbewerb", "teams": []}), 400

    season = resolve_requested_season(request.args.get("season"))
    if season is None:
        season = get_current_season(config["api_code"])

    try:
        raw = apisports_api.get_standings_table(league_id, season)
    except ApisportsRateLimit as error:
        return jsonify({
            "error": "Das taegliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "detail": str(error),
            "teams": [],
        }), 429
    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Die Vereinsliste kann momentan nicht geladen werden.",
            "detail": str(error),
            "teams": [],
        }), 503

    # Die Antwort ist eine Liste von Gruppen (Liste von Listen). Alle
    # Gruppen werden gelesen, damit ein Gruppenformat nicht stillschweigend
    # leer bliebe - dieselbe Vorsicht wie in team_detail.find_standings_row.
    teams = {}
    for entry in raw or []:
        league_block = (entry or {}).get("league") or {}
        for group in league_block.get("standings") or []:
            for row in group or []:
                team = (row or {}).get("team") or {}
                team_id = team.get("id")
                if team_id is None or team_id in teams:
                    continue
                teams[team_id] = {
                    "team_id": team_id,
                    "team_name": team.get("name"),
                    "crest": team.get("logo"),
                }

    return jsonify({
        "competition": competition_code,
        "season": season,
        "source": "apisports",
        "teams": list(teams.values()),
    })


@app.route("/api/standings", methods=["GET"])
def api_standings():
    competition_code = request.args.get("competition", "").lower()
    table_type = request.args.get("type", "TOTAL").upper()
    season = resolve_requested_season(request.args.get("season"))

    config = _resolve_competition_config(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Tabelle"}), 400

    if table_type not in ("TOTAL", "HOME", "AWAY"):
        table_type = "TOTAL"

    try:
        standings = get_standings(config["api_code"], season=season)
    except ApiUnavailable as error:
        return api_error(error)

    tables = standings.get("tables") or {}
    rows = tables.get(table_type) or tables.get("TOTAL") or []

    return jsonify({
        "competition": config["name"],
        "season": standings.get("season"),
        "type": table_type,
        "available_types": [t for t in ("TOTAL", "HOME", "AWAY") if t in tables],
        "table": rows,
    })


# =============================================================================
#  API: TORJAEGER
# =============================================================================

@app.route("/api/scorers", methods=["GET"])
def api_scorers():
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    config = _resolve_competition_config(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Torjaegerliste"}), 400

    try:
        data = get_scorers(config["api_code"], season=season, limit=limit)
    except ApiUnavailable as error:
        return api_error(error)

    return jsonify({
        "competition": config["name"],
        "season": data.get("season"),
        "scorers": data.get("scorers", []),
    })


# =============================================================================
#  API: LIGENVERGLEICH, NATIONAL
# =============================================================================

@app.route("/api/compare", methods=["GET"])
def api_compare():
    """
    Vergleicht zwei bis fuenf Ligen anhand echter Saisondaten.
    Aufruf: /api/compare?leagues=bl1,pd,sa&season=2025
    """
    codes = parse_league_codes(request.args.get("leagues", ""))
    season = resolve_requested_season(request.args.get("season"))

    if len(codes) < 2:
        return jsonify({"error": "Bitte mindestens zwei Ligen auswaehlen"}), 400

    if len(codes) > 5:
        return jsonify({"error": "Maximal fuenf Ligen gleichzeitig"}), 400

    profiles = []

    for code in codes:
        config = LEAGUE_CONFIG[code]

        try:
            standings = get_standings(config["api_code"], season=season)
            matches = get_finished_season_matches(config["api_code"], season=season)
        except ApiUnavailable as error:
            return api_error(error)

        profiles.append(
            build_league_profile(code, config["name"], standings, matches)
        )

    result = build_comparison(profiles)
    result["season"] = profiles[0].get("season") if profiles else None
    return jsonify(result)


# =============================================================================
#  API: LIGENVERGLEICH INNERHALB EINES POKALWETTBEWERBS
# =============================================================================

@app.route("/api/cup-compare", methods=["GET"])
def api_cup_compare():
    """
    Vergleicht Ligen anhand der Leistung ihrer Vereine in einem
    Pokalwettbewerb, in der Regel der Champions League.

    Aufruf: /api/cup-compare?leagues=bl1,pd,pl&phase=all&season=2025&cup=cl

    phase:
        all       komplette Saison, Ligaphase und K o Phase
        league    nur die Ligaphase
        knockout  nur die K o Phase
    """
    codes = parse_league_codes(request.args.get("leagues", ""))
    season = resolve_requested_season(request.args.get("season"))
    phase = (request.args.get("phase") or "all").lower()
    cup_code = (request.args.get("cup") or "cl").lower()

    if phase not in cl_stats.PHASE_FILTERS:
        phase = "all"

    cup = CUP_CONFIG.get(cup_code)

    if not cup:
        return jsonify({"error": "Unbekannter Wettbewerb"}), 400

    if len(codes) < 2:
        return jsonify({"error": "Bitte mindestens zwei Ligen auswaehlen"}), 400

    if len(codes) > 5:
        return jsonify({"error": "Maximal fuenf Ligen gleichzeitig"}), 400

    try:
        matches = get_cup_matches(cup["api_code"], season=season)
    except ApiUnavailable as error:
        return api_error(error)

    if not matches:
        return jsonify({
            "error": "Fuer diese Saison liegen noch keine gespielten Partien vor",
            "code": "NO_DATA"
        }), 404

    # Zuordnung Verein zu Liga fuer genau diese Saison aufbauen
    teams_by_league = {}

    for code in codes:
        config = LEAGUE_CONFIG[code]
        try:
            teams_by_league[code] = get_competition_teams(config["api_code"], season=season)
        except ApiUnavailable as error:
            return api_error(error)

    team_league_map = cl_stats.build_team_league_map(teams_by_league)

    allowed_stages = cl_stats.PHASE_FILTERS[phase]
    include_knockout = phase in ("all", "knockout")

    counters = cl_stats.collect_league_results(matches, team_league_map, allowed_stages)
    participation = cl_stats.collect_stage_participation(matches)
    winner_id = cl_stats.find_winner(matches)
    progression = cl_stats.compute_progression(participation, winner_id, team_league_map, codes)

    profiles = []

    for code in codes:
        config = LEAGUE_CONFIG[code]
        profiles.append(cl_stats.build_cup_profile(
            league_code=code,
            league_name=config["name"],
            emblem=f"{CREST_BASE_URL}/{config['api_code']}.png",
            counters=counters.get(code),
            progression=progression.get(code),
        ))

    # Ligen ohne einen einzigen Teilnehmer machen den Vergleich unbrauchbar
    without_teams = [p["name"] for p in profiles if p["metrics"]["teams"] == 0]

    result = cl_stats.build_cup_comparison(profiles, phase, include_knockout)
    result["cup"] = {"code": cup_code, "name": cup["name"]}
    result["season"] = season if season is not None else get_current_season(cup["api_code"])
    result["stages_played"] = [
        cl_stats.STAGE_LABELS[s]
        for s in cl_stats.STAGE_ORDER
        if participation.get(s)
    ]
    result["notice"] = (
        f"Ohne Teilnehmer in diesem Wettbewerb: {', '.join(without_teams)}"
        if without_teams else ""
    )

    return jsonify(result)


# =============================================================================
#  API: SIMULATION
# =============================================================================

@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request Body fehlt"}), 400

    competition_code = data.get("competition", "cl")
    simulations = data.get("simulations", 5000)
    use_seed = data.get("use_seed", False)

    try:
        simulations = max(100, min(int(simulations), 50000))
    except (TypeError, ValueError):
        simulations = 5000

    try:
        if competition_code in LEAGUE_CONFIG:
            home_team = data.get("home_team")
            away_team = data.get("away_team")

            if not home_team or not away_team:
                return jsonify({"error": "home_team oder away_team fehlt"}), 400

            # Ligaspiele laufen ueber das moderne Staerkemodell mit
            # garantierter Fallback-Kette. Damit sind auch Aufsteiger
            # und neue Teams IMMER simulierbar - der alte Pfad ueber
            # team_matches.json kannte sie nicht und brach ab.
            config = LEAGUE_CONFIG[competition_code]
            result = simulate_league_match(
                competition_code=competition_code,
                api_code=config["api_code"],
                home_team=home_team,
                away_team=away_team,
                home_id=data.get("home_id"),
                away_id=data.get("away_id"),
                season=resolve_requested_season(data.get("season")),
                simulations=simulations,
                use_seed=use_seed,
            )
            return jsonify(result)

        if competition_code == "cl":
            home_team = data.get("home_team")
            away_team = data.get("away_team")

            if not home_team or not away_team:
                return jsonify({"error": "home_team oder away_team fehlt"}), 400

            # Champions-League-Ligaphase: eigenes Staerkemodell mit einer
            # anderen Fallback-Kette als die nationalen Ligen (siehe
            # src/predict/cl_match_sim.py und
            # strength_provider.get_cl_team_strengths). Ersetzt den alten
            # Pfad ueber MATCHES_TO_PREDICT_CL-Dictionaries vollstaendig -
            # Teams werden ausschliesslich ueber football-data-Team-IDs
            # identifiziert, nicht ueber Klarnamen. Deckt in Block B1 nur
            # die Ligaphase ab (Einzelspiel, kein Hin-/Rueckspiel).
            result = simulate_cl_league_phase_match(
                home_team=home_team,
                away_team=away_team,
                home_id=data.get("home_id"),
                away_id=data.get("away_id"),
                season=resolve_requested_season(data.get("season")),
                simulations=simulations,
                use_seed=use_seed,
            )
            return jsonify(result)

        return jsonify({"error": "Aktuell nicht verfuegbar."}), 400

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Interner Fehler: {str(error)}"}), 500


# =============================================================================
#  API: STATUS
# =============================================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """Kleine Diagnoseseite. Zeigt erkannte Saison und Cache Zustand."""
    seasons = {}

    for code, config in LEAGUE_CONFIG.items():
        info = get_season_info(config["api_code"])
        seasons[code] = {
            "name": config["name"],
            "season": info["season"],
            "current_matchday": info["current_matchday"],
            "auto_detected": info["auto_detected"],
            "unlocked_matchdays": config["unlocked_matchdays"],
        }

    return jsonify({
        "unlock_all": UNLOCK_ALL_MATCHDAYS,
        "season_override": SEASON_OVERRIDE,
        "season_history": SEASON_HISTORY,
        "season_options": build_season_options(),
        "leagues": seasons,
        "cache": cache.stats(),
    })



# =============================================================================
#  API: SAISONSIMULATION
# =============================================================================

@app.route("/api/season-sim", methods=["GET"])
def api_season_sim():
    """
    Simuliert den Ausgang einer Ligasaison.

    Ablauf:
      1. Aktuelle Tabelle holen (gespielte Punkte, Tordifferenz)
      2. Alle Spieltage durchgehen, noch nicht gespielte Partien sammeln
      3. season_sim.simulate_season aufrufen
      4. Ergebnis ans Frontend schicken

    Aufruf: /api/season-sim?competition=bl1&simulations=10000
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    raw_sims = request.args.get("simulations")
    if raw_sims is not None:
        try:
            simulations = int(raw_sims)
            if not (1 <= simulations <= 50000):
                return jsonify({"error": "Die Anzahl der Simulationen muss zwischen 1 und 50.000 liegen."}), 400
        except ValueError:
            return jsonify({"error": "Ungültige Eingabe für Simulationen."}), 400
    else:
        simulations = 10000

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    try:
        # Tabelle holen
        standings_data = get_standings(config["api_code"], season=season)
        table = standings_data.get("tables", {}).get("TOTAL", [])

        if not table:
            return jsonify({"error": "Keine Tabellendaten verfügbar"}), 404

        total_matchdays = config["total_matchdays"]

        # Vollstaendigen Saisonplan laden: EIN API-Request liefert alle
        # 306 bzw. 380 Partien. Die Saisonsimulation haengt damit NICHT
        # mehr an der UI-Freischaltung einzelner Spieltage - die gilt
        # nur fuer die Einzelspielansicht.
        plan = build_season_plan(
            config["api_code"],
            season=season,
            expected_team_count=len(table),
        )

        coverage = plan["coverage"]

        # Harte Validierung VOR der Monte-Carlo-Simulation: Fuer jedes
        # Team muss gespielte + verbleibende Spiele die volle Doppelrunde
        # ergeben. Ist der Plan unvollstaendig, gibt es KEINE serioes
        # wirkende Tabelle, sondern eine klare Fehlermeldung.
        if not coverage["ok"]:
            return jsonify({
                "error": (
                    "Die vollständige Saisonprognose konnte nicht berechnet "
                    "werden, weil der Spielplan unvollständig ist."
                ),
                "fixture_coverage": coverage,
                "invalid_matches": plan["invalid_matches"][:20],
            }), 503

        result = simulate_season(
            competition_code=competition_code,
            standings_table=table,
            remaining_matches=plan["remaining_matches"],
            simulations=simulations,
            current_matches=plan["finished_matches"],
            season=plan["season"],
            fixture_coverage=coverage,
        )

        result["competition"] = config["name"]
        result["season"] = standings_data.get("season")
        result["played_matchdays"] = plan["played_matchdays"]
        result["total_matchdays"] = total_matchdays

        return jsonify(result)

    except ApiUnavailable as error:
        return api_error(error)
    except Exception as error:
        return jsonify({"error": f"Simulationsfehler: {str(error)}"}), 500


# =============================================================================
#  API: CHAMPIONS-LEAGUE-LIGAPHASEN-SIMULATION
# =============================================================================

@app.route("/api/cl-season-sim", methods=["GET"])
def api_cl_season_sim():
    """
    Simuliert die komplette Champions-League-Ligaphase.

    Aufruf: /api/cl-season-sim?season=2025&simulations=10000[&mode=...]

    Bewusst ein eigener Endpoint statt einer Erweiterung von
    /api/season-sim: die Ligaphase ist keine Doppelrunde, braucht eine
    eigene Coverage-Pruefung, eigene Zonen und die offizielle
    UEFA-Tiebreak-Kaskade. /api/season-sim bleibt fuer die fuenf
    nationalen Ligen unveraendert.

    mode ist optional. Ohne Angabe entscheidet der Spielplan:
    offene Partien -> simulate_remaining, sonst full_resimulation.
    """
    season = resolve_requested_season(request.args.get("season"))

    raw_sims = request.args.get("simulations")
    if raw_sims is not None:
        try:
            simulations = int(raw_sims)
            if not (1 <= simulations <= 50000):
                return jsonify({"error": "Die Anzahl der Simulationen muss zwischen 1 und 50.000 liegen."}), 400
        except ValueError:
            return jsonify({"error": "Ungültige Eingabe für Simulationen."}), 400
    else:
        simulations = 10000

    mode = (request.args.get("mode") or "").strip().lower() or None
    if mode is not None and mode not in CL_SIM_MODES:
        return jsonify({"error": "Unbekannter Simulationsmodus"}), 400

    config = CL_LEAGUE_PHASE_CONFIG

    try:
        plan = build_cl_league_phase_plan(
            season=season,
            expected_matches_per_team=config["total_matchdays"],
        )
    except ApiUnavailable as error:
        return api_error(error)

    plan_season = plan["season"]
    season_label = f"{plan_season}/{str(plan_season + 1)[2:]}"
    coverage = plan["coverage"]

    # Noch nicht ausgelost: erwartbarer Zustand, kein technischer Fehler.
    # Gleiches Muster wie bei Tabelle/Torjaeger/Spielen (Season-Leak-Fix).
    if not coverage["has_fixtures"]:
        return jsonify({
            "competition": config["name"],
            "season": plan_season,
            "entries": [],
            "empty_state": True,
            "empty_state_message": (
                f"Die Ligaphase der Champions League {season_label} wurde noch "
                "nicht ausgelost. Sobald die Spielpaarungen feststehen, kann "
                "sie hier simuliert werden."
            ),
        })

    # Fixtures vorhanden, aber der Plan geht nicht auf: hier waere eine
    # Tabelle serioes aussehend und trotzdem falsch. Also klarer Fehler.
    if not coverage["ok"]:
        return jsonify({
            "error": (
                "Die Ligaphase kann nicht simuliert werden, weil der "
                "Spielplan unvollständig ist."
            ),
            "fixture_coverage": coverage,
            "invalid_matches": plan["invalid_matches"][:20],
        }), 503

    try:
        result = simulate_cl_league_phase(
            plan=plan,
            mode=mode,
            simulations=simulations,
            season=plan_season,
        )
    except ApiUnavailable as error:
        return api_error(error)
    except Exception as error:
        return jsonify({"error": f"Simulationsfehler: {str(error)}"}), 500

    result["competition"] = config["name"]
    result["season"] = plan_season
    result["total_matchdays"] = config["total_matchdays"]

    return jsonify(result)


# =============================================================================
#  API: API-SPORTS SCORERS MIT FOTOS
# =============================================================================

@app.route("/api/player-scorers", methods=["GET"])
def api_player_scorers():
    """
    Torjäger mit Spielerfoto von API-Sports.
    Fällt sauber auf football-data.org Daten zurück wenn nicht verfügbar.

    Saisonzuordnung:
      FootSim season=2025 -> API-Sports season=2025 -> Saison 2025/26.
      FootSim season=2026 -> API-Sports season=2026 -> Saison 2026/27.
      Beide APIs verwenden das Startjahr der Saison (kein Offset).

    Empty-State-Gate:
      Wenn fuer die angefragte Saison noch keine beendeten Ligaspiele
      vorliegen (Saison noch nicht gestartet), wird kein API-Request
      gestellt. Stattdessen kommt ein leeres Ergebnis mit einem
      erklaerenden Hinweis zurueck.
    """
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    config = _resolve_competition_config(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    if season is not None:
        apisports_season = season
    else:
        try:
            apisports_season = get_current_season(config["api_code"])
        except Exception:
            apisports_season = apisports_api.CURRENT_SEASON

    try:
        finished = get_finished_season_matches(config["api_code"], season=apisports_season)
    except Exception:
        finished = []

    if not finished:
        season_label = f"{apisports_season}/{str(apisports_season + 1)[2:]}"
        if competition_code == "cl":
            empty_message = (
                f"Für die Champions League {season_label} sind aktuell "
                "noch keine Torjägerdaten verfügbar."
            )
        else:
            empty_message = (
                f"Für die Saison {season_label} liegen noch keine "
                "Torjägerdaten vor – die Saison hat noch nicht begonnen."
            )
        return jsonify({
            "source": "empty-state",
            "competition": config["name"],
            "season": apisports_season,
            "scorers": [],
            "empty_state": True,
            "empty_state_message": empty_message,
        })

    try:
        scorers = apisports_api.get_top_scorers(
            competition_code,
            season=apisports_season,
            limit=limit,
        )
        return jsonify({
            "source": "api-sports",
            "competition": config["name"],
            "season": apisports_season,
            "scorers": scorers,
        })

    except ApisportsUnavailable as error:
        try:
            data = get_scorers(config["api_code"], season=apisports_season, limit=limit)
            scorers = [
                _normalize_footballdata_scorer(scorer)
                for scorer in data.get("scorers", [])
            ]

            if competition_code == "cl" and not scorers:
                season_label = f"{apisports_season}/{str(apisports_season + 1)[2:]}"
                return jsonify({
                    "source": "empty-state",
                    "competition": config["name"],
                    "season": apisports_season,
                    "scorers": [],
                    "empty_state": True,
                    "empty_state_message": (
                        f"Für die Champions League {season_label} sind aktuell "
                        "noch keine Torjägerdaten verfügbar."
                    ),
                })

            return jsonify({
                "source": "football-data",
                "competition": config["name"],
                "season": data.get("season"),
                "scorers": scorers,
            })
        except ApiUnavailable as fallback_error:
            return api_error(fallback_error)


def _normalize_footballdata_scorer(scorer):
    """
    Uebersetzt einen football-data-Torjaeger auf das API-Sports-Schema.

    So sieht das Frontend immer die gleichen Feldnamen, egal welche
    Quelle geantwortet hat. player_photo bleibt None, weil football-data
    keine Fotos liefert; das Frontend faengt das ueber Initialen ab.
    """
    return {
        "rank": scorer.get("rank"),
        "player_id": scorer.get("player_id"),
        "player_name": scorer.get("player_name"),
        "player_photo": None,
        "nationality": scorer.get("nationality"),
        "age": None,
        "position": scorer.get("position"),
        "team_id": scorer.get("team_id"),
        "team_name": scorer.get("team_name"),
        "team_logo": scorer.get("team_crest"),
        "goals": scorer.get("goals") or 0,
        "assists": scorer.get("assists"),
        "penalties": scorer.get("penalties"),
        "appearances": scorer.get("played_matches"),
        "minutes": None,
        "goals_per_match": scorer.get("goals_per_match"),
        "key_passes": None,
    }


# =============================================================================
#  API: VERLETZUNGEN UND SPERREN
# =============================================================================

@app.route("/api/injuries", methods=["GET"])
def api_injuries():
    competition_code = request.args.get("competition", "").lower()
    season = resolve_requested_season(request.args.get("season"))

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return jsonify({"error": "Unbekannte Liga"}), 400

    if season is not None:
        apisports_season = season
    else:
        try:
            apisports_season = get_current_season(config["api_code"])
        except Exception:
            apisports_season = apisports_api.CURRENT_SEASON

    try:
        injuries = apisports_api.get_injuries(competition_code, season=apisports_season)
        return jsonify({
            "competition": config["name"],
            "season": apisports_season,
            "injuries": injuries,
        })
    except ApisportsUnavailable as error:
        return jsonify({"error": str(error), "injuries": []}), 503


# =============================================================================
#  API: API-SPORTS STATUS
# =============================================================================

@app.route("/api/apisports-status", methods=["GET"])
def api_apisports_status():
    usage = apisports_api.get_request_usage()
    if not usage:
        return jsonify({"available": False, "error": "API-Sports nicht erreichbar"})
    return jsonify({"available": True, **usage})


# =============================================================================
#  API: LIVE (Block LIVE A)
# =============================================================================
#
#  Tagesuebersicht aller FootSim-Wettbewerbe. Datenquelle ist
#  API-Football; football-data.org bleibt fuer Tabellen, Torjaeger und
#  Simulation unveraendert zustaendig (siehe src/api/live_api.py).

# Wie weit der Nutzer vom heutigen Tag weg abfragen darf.
#
# Die Oberflaeche erlaubt seit LIVE A+ freie Tagesnavigation (Pfeile,
# Kalender, Datumsstreifen), keine feste Gestern/Heute/Morgen-Auswahl
# mehr. 60 Tage in beide Richtungen decken mehrere Wochen Rueckschau und
# die komplette naechste Ansetzungsrunde ab - deutlich mehr als "gestern
# bis morgen", aber immer noch eine bewusste Produktgrenze statt
# unbegrenzter Werte: ein Aufrufer soll den Plattencache nicht mit
# beliebigen historischen oder weit entfernten Zukunftsdaten fuellen
# koennen, fuer die API-Football ohnehin kaum verlaessliche Ansetzungen
# hat.
LIVE_DATE_WINDOW_DAYS = 60


def _live_competitions():
    """
    FootSim-Wettbewerbe fuer den Live-Bereich, in Anzeigereihenfolge.

    Bewusst KEINE neue Liga-Liste: die Wettbewerbe kommen aus
    LEAGUE_CONFIG und CUP_CONFIG (was FootSim ueberhaupt kennt), die
    API-Football-IDs aus apisports_api.LEAGUE_IDS (die bestehende
    Zuordnung FootSim-Code -> API-Football-ID). Beide bleiben die
    jeweils einzige Quelle der Wahrheit.

    CUP_CONFIG["available"] wird hier bewusst nicht ausgewertet: das Flag
    steuert die Verfuegbarkeit der Simulation, nicht die von Live-Ergebnissen.
    Ein Wettbewerb, den FootSim kennt, darf Ergebnisse zeigen, auch wenn
    er noch nicht simulierbar ist.
    """
    competitions = {}

    for code in list(LEAGUE_CONFIG.keys()) + list(CUP_CONFIG.keys()):
        league_id = apisports_api.LEAGUE_IDS.get(code)
        if league_id is not None:
            competitions[code] = league_id

    return competitions


def _today_in_display_timezone():
    """Heutiges Datum in Europe/Berlin - nicht in der Zeitzone des Servers."""
    return datetime.now(live_api.BERLIN).date()


def _resolve_live_date(raw_value):
    """
    Validiert das angefragte Datum.

    Rueckgabe (date, None) bei Erfolg, (None, Fehlermeldung) sonst.
    Ohne Angabe gilt der heutige Tag in Europe/Berlin.
    """
    today = _today_in_display_timezone()

    if not raw_value:
        return today, None

    try:
        requested = date.fromisoformat(raw_value.strip())
    except (ValueError, AttributeError):
        return None, "Ungueltiges Datum. Erwartet wird YYYY-MM-DD."

    if abs((requested - today).days) > LIVE_DATE_WINDOW_DAYS:
        return None, (
            f"Datum liegt zu weit von heute entfernt "
            f"(maximal {LIVE_DATE_WINDOW_DAYS} Tage)."
        )

    return requested, None


@app.route("/api/live-matches", methods=["GET"])
def api_live_matches():
    """
    Spiele eines Kalendertags, gruppiert nach Wettbewerb.

    Die Antwort ist bewusst von der API-Football-Struktur entkoppelt:
    das Frontend sieht FootSim-Felder, keine Provider-Interna und
    selbstverstaendlich keine Schluessel.
    """
    requested_date, error_message = _resolve_live_date(request.args.get("date"))

    if error_message:
        return jsonify({"error": error_message}), 400

    date_str = requested_date.isoformat()
    today = _today_in_display_timezone()

    try:
        payload = live_api.get_matches_for_date(date_str, _live_competitions())
    except ApisportsRateLimit:
        return jsonify({
            "error": "Live-Daten sind gerade nicht abrufbar. Bitte kurz warten.",
            "date": date_str,
            "groups": [],
            "match_count": 0,
            "live_count": 0,
        }), 503
    except ApisportsUnavailable:
        # Bewusst ohne Provider-Details nach aussen.
        return jsonify({
            "error": "Live-Daten sind derzeit nicht verfügbar.",
            "date": date_str,
            "groups": [],
            "match_count": 0,
            "live_count": 0,
        }), 503

    return jsonify({
        **payload,
        "is_today": date_str == today.isoformat(),
    })


@app.route("/api/live-match", methods=["GET"])
def api_live_match():
    """
    Ein einzelnes Spiel in voller Tiefe (Match Center, Block LIVE B).

    Fuehrt Stammdaten, Aufstellungen, Ereignisse und Statistiken zu einer
    Antwort zusammen. Bewusst eine aggregierte Route statt vier: im Match
    Center gehoeren die vier Aspekte zusammen, ein Tabwechsel soll keinen
    weiteren Request kosten.

    Wie /api/live-matches: FootSim-Felder nach aussen, keine
    Provider-Interna und keine Schluessel.
    """
    raw_fixture = request.args.get("fixture", "").strip()

    if not raw_fixture:
        return jsonify({"error": "Parameter fixture fehlt."}), 400

    try:
        fixture_id = int(raw_fixture)
    except ValueError:
        return jsonify({"error": "Ungueltige fixture id."}), 400

    if fixture_id <= 0:
        return jsonify({"error": "Ungueltige fixture id."}), 400

    try:
        payload = live_api.get_match_center(fixture_id)
    except ApisportsRateLimit:
        return jsonify({
            "error": "Spieldaten sind gerade nicht abrufbar. Bitte kurz warten.",
        }), 503
    except ApisportsUnavailable:
        # Bewusst ohne Provider-Details nach aussen.
        return jsonify({
            "error": "Spieldaten sind derzeit nicht verfügbar.",
        }), 503

    if payload is None:
        return jsonify({"error": "Spiel nicht gefunden."}), 404

    return jsonify(payload)


# =============================================================================
#  API: TRANSFER-VERGLEICH (Liga zu Liga)
# =============================================================================
#
#  Vergleicht zwei Transfergruppen unter denselben Zielbedingungen:
#      Quelliga A -> Zielliga   gegen   Quelliga B -> Zielliga
#  fuer einen bestimmten Saisonwechsel (Sommertransfers).
#
#  Request-Sparsamkeit (ein Vergleich beruehrt sehr viele Einzelabrufe):
#    1. Jeder einzelne API-Aufruf ist dauerhaft im Disk-Cache
#       (Teams, Transfers, Spielerstatistiken).
#    2. Das komplette Endergebnis wird zusaetzlich gecacht, damit
#       wiederholte Seitenaufrufe exakt 0 API-Requests kosten.
#    3. Faellt die API mitten im Lauf aus, wird ein evtl. vorhandenes
#       aelteres Endergebnis aus dem Cache ausgeliefert.

# Fruehestes Jahr, fuer das API-Sports verlaesslich Transfer- und
# Statistikdaten liefert.
TRANSFER_COMPARE_MIN_SEASON = 2016

TTL_TRANSFER_COMPARE_FINISHED = 60 * 60 * 24 * 30   # 30 Tage
TTL_TRANSFER_COMPARE_CURRENT  = 60 * 60 * 24        # 24 Stunden


def _build_transfer_group_players(source_league, target_league, season):
    """
    Laedt die Transfers einer Quelliga und ergaenzt jeden Spieler um
    seine normalisierten Zielliga-Statistiken. Spieler-IDs werden
    dedupliziert geladen (kein N+1 fuer denselben Spieler).
    """
    transfers = transfer_loader.load_summer_transfers(
        source_league, target_league, season
    )

    stats_by_player = {}
    for transfer in transfers:
        player_id = transfer["player_id"]
        if player_id in stats_by_player:
            continue
        stats_by_player[player_id] = get_player_target_league_stats(
            player_id, season, target_league
        )

    enriched = []
    for transfer in transfers:
        stats = stats_by_player.get(transfer["player_id"]) or {}
        enriched.append({**transfer, **stats})

    return enriched


@app.route("/api/transfer-leagues", methods=["GET"])
def api_transfer_leagues():
    """
    Liefert die vollstaendige Liste der unterstuetzten Transfer-Ligen
    in der konfigurierten Reihenfolge. Kein API-Request noetig.
    """
    from src.data.transfer_loader import SUPPORTED_LEAGUES, LEAGUE_LABELS
    return jsonify([
        {"code": code, "name": LEAGUE_LABELS.get(code, code)}
        for code in SUPPORTED_LEAGUES
    ])


@app.route("/api/transfer-seasons", methods=["GET"])
def api_transfer_seasons():
    """
    Liefert die verfuegbaren Saisons einer Liga laut API-Sports.
    Wird dauerhaft im Disk-Cache gespeichert (Saisons aendern sich nicht).

    Parameter: league=bl1
    """
    from src.api.apisports_api import LEAGUE_IDS, ApisportsUnavailable
    from src.utils.disk_cache import disk_cached_call

    league_code = (request.args.get("league") or "").lower().strip()
    from src.data.transfer_loader import SUPPORTED_LEAGUES
    if league_code not in SUPPORTED_LEAGUES:
        return jsonify({"error": f"Unbekannte Liga: {league_code}"}), 400

    league_id = LEAGUE_IDS.get(league_code)

    def loader():
        raw = apisports_api._get("leagues", params={"id": league_id})
        seasons = []
        for entry in raw:
            for season_entry in (entry.get("seasons") or []):
                year = season_entry.get("year")
                if isinstance(year, int):
                    seasons.append(year)
        return sorted(set(seasons), reverse=True)

    try:
        seasons = disk_cached_call(
            key=f"apisports:seasons:{league_code}",
            ttl_seconds=60 * 60 * 24 * 30,  # 30 Tage
            loader=loader,
            source="api-sports",
        )
        return jsonify({"league": league_code, "seasons": seasons})
    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Saisondaten konnten nicht geladen werden.",
            "detail": str(error),
        }), 503


@app.route("/api/transfer-compare", methods=["GET"])
def api_transfer_compare():
    from_a = (request.args.get("from_a") or "").lower().strip()
    from_b = (request.args.get("from_b") or "").lower().strip()
    target = (request.args.get("to") or "").lower().strip()
    raw_season = request.args.get("season", "")

    supported = transfer_loader.SUPPORTED_LEAGUES

    # --- Parameter validieren -------------------------------------------
    for code, name in ((from_a, "from_a"), (from_b, "from_b"), (target, "to")):
        if code not in supported:
            return jsonify({
                "error": f"Unbekannter oder nicht unterstuetzter Ligacode "
                         f"fuer '{name}'. Erlaubt: {', '.join(supported)}"
            }), 400

    if from_a == from_b:
        return jsonify({
            "error": "Quelliga A und Quelliga B muessen unterschiedlich sein."
        }), 400

    if target in (from_a, from_b):
        return jsonify({
            "error": "Die Zielliga darf keiner der beiden Quelligen entsprechen."
        }), 400

    try:
        season = int(raw_season)
    except (TypeError, ValueError):
        return jsonify({"error": "Ungueltige Saison."}), 400

    if not (TRANSFER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
        return jsonify({
            "error": f"Saison muss zwischen {TRANSFER_COMPARE_MIN_SEASON} und "
                     f"{apisports_api.CURRENT_SEASON} liegen."
        }), 400

    # --- Ergebnis laden (Cache zuerst) ----------------------------------
    result_key = f"transfercompare:{from_a}:{from_b}:{target}:{season}"
    result_ttl = (
        TTL_TRANSFER_COMPARE_FINISHED
        if season < apisports_api.CURRENT_SEASON
        else TTL_TRANSFER_COMPARE_CURRENT
    )

    labels = transfer_loader.LEAGUE_LABELS

    def loader():
        players_a = _build_transfer_group_players(from_a, target, season)
        players_b = _build_transfer_group_players(from_b, target, season)
        return transfer_comparison.build_comparison_result(
            from_a, from_b, target, season,
            labels[from_a], labels[from_b], labels[target],
            players_a, players_b,
        )

    try:
        result = disk_cached_call(
            key=result_key,
            ttl_seconds=result_ttl,
            loader=loader,
            source="api-sports",
        )
        return jsonify(result)

    except ApisportsUnavailable as error:
        # Notfall: auch ein abgelaufenes Endergebnis ist besser als nichts.
        stale = disk_read_entry(result_key)
        if stale and stale.get("payload"):
            payload = stale["payload"]
            warnings = list(payload.get("warnings") or [])
            warnings.append(
                "Die Datenquelle ist momentan nicht erreichbar. "
                "Es werden zuletzt gespeicherte Daten angezeigt."
            )
            payload = {**payload, "warnings": warnings}
            return jsonify(payload)

        if isinstance(error, ApisportsRateLimit):
            return jsonify({
                "error": "Das taegliche Kontingent der Datenquelle ist "
                         "aufgebraucht. Bitte morgen erneut versuchen.",
                "detail": str(error),
            }), 429

        return jsonify({
            "error": "Diese Analyse kann momentan nicht geladen werden. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
        }), 503

# =============================================================================
#  PDF MERGE TOOL
# =============================================================================

PDF_ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
PDF_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
PDF_MAX_FILES = 40

# Dekompressionsbomben: ein wenige Kilobyte grosses PNG kann sich zu
# Gigabytes entpacken. Pillows Standardgrenze loest nur eine WARNUNG aus,
# der Prozess rechnet weiter. Hier wird daraus ein harter Fehler, und die
# Grenze liegt bewusst unter Pillows Default - 50 Megapixel decken jedes
# reale Handyfoto ab, ohne einem Angreifer den RAM zu schenken.
PDF_MAX_IMAGE_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = PDF_MAX_IMAGE_PIXELS


def pdf_get_extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def pdf_is_allowed(filename):
    return pdf_get_extension(filename) in PDF_ALLOWED_EXTENSIONS


def pdf_is_image(filename):
    return pdf_get_extension(filename) in PDF_IMAGE_EXTENSIONS


def pdf_convert_image(image_path, target_path):
    """
    Wandelt ein Bild in eine einseitige PDF um.
    Unterstuetzt RGB, CMYK, RGBA, Palette und alle anderen Modi.
    Transparente PNGs kriegen weissen Hintergrund.
    """
    from PIL import ImageOps
    with Image.open(image_path) as image:
        # Groesse VOR dem Dekodieren pruefen: Image.open() liest nur den
        # Header, erst der Zugriff auf die Pixel kostet Speicher. Ein zu
        # grosses Bild wird deshalb hier abgelehnt, bevor es entpackt wird.
        width, height = image.size
        if width * height > PDF_MAX_IMAGE_PIXELS:
            raise ValueError("image exceeds pixel budget")

        # EXIF-Rotation beruecksichtigen (Handy-Fotos)
        image = ImageOps.exif_transpose(image)

        if image.mode == "CMYK":
            image_to_save = image.convert("RGB")
        elif image.mode in ("RGBA", "LA", "P"):
            converted = image.convert("RGBA")
            background = Image.new("RGB", converted.size, (255, 255, 255))
            background.paste(converted, mask=converted.split()[-1])
            image_to_save = background
        elif image.mode != "RGB":
            image_to_save = image.convert("RGB")
        else:
            image_to_save = image.copy()

        image_to_save.save(target_path, "PDF", resolution=150.0)


def pdf_build_output_name(raw_name):
    cleaned = secure_filename(raw_name or "merged")

    if not cleaned:
        cleaned = "merged"

    if cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4]

    return f"{cleaned}.pdf"


@app.route("/tools/pdf", methods=["GET"])
def pdf_merge_page():
    return render_template("pdfmerge.html")


@app.route("/tools/pdf/merge", methods=["POST"])
@limiter.limit("12 per hour")
def pdf_merge_run():
    uploaded_files = request.files.getlist("files")

    if not uploaded_files:
        return jsonify({"error": "Keine Dateien empfangen"}), 400

    if len(uploaded_files) > PDF_MAX_FILES:
        return jsonify({"error": f"Maximal {PDF_MAX_FILES} Dateien pro Merge"}), 400

    work_dir = tempfile.mkdtemp(prefix="footsim_pdfmerge_")

    try:
        writer = PdfWriter()
        merged_count = 0

        for position, uploaded in enumerate(uploaded_files):
            if not uploaded.filename or not pdf_is_allowed(uploaded.filename):
                continue

            extension = pdf_get_extension(uploaded.filename)
            source_path = os.path.join(work_dir, f"{position:03d}_input.{extension}")
            uploaded.save(source_path)

            if pdf_is_image(uploaded.filename):
                try:
                    converted_path = os.path.join(work_dir, f"{position:03d}_converted.pdf")
                    pdf_convert_image(source_path, converted_path)
                    writer.append(converted_path)
                except Exception:
                    return jsonify({
                        "error": f"Bild konnte nicht gelesen werden: {uploaded.filename}"
                    }), 400
            else:
                try:
                    reader = PdfReader(source_path)

                    if reader.is_encrypted:
                        if reader.decrypt("") == 0:
                            return jsonify({
                                "error": f"Passwortgeschuetzt: {uploaded.filename}"
                            }), 400

                    writer.append(reader)
                except Exception:
                    return jsonify({
                        "error": f"Beschaedigte oder ungueltige PDF: {uploaded.filename}"
                    }), 400

            merged_count += 1

        if merged_count == 0:
            return jsonify({"error": "Keine gueltigen Dateien dabei"}), 400

        total_pages = len(writer.pages)
        output_path = os.path.join(work_dir, "__output.pdf")

        writer.write(output_path)
        writer.close()

        with open(output_path, "rb") as output_file:
            pdf_bytes = output_file.read()

        response = send_file(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            download_name=pdf_build_output_name(request.form.get("output_name")),
            mimetype="application/pdf"
        )
        response.headers["X-Total-Pages"] = str(total_pages)
        return response

    except Exception:
        # Bewusst OHNE str(error) an den Client: die Ausnahmetexte von
        # pypdf/Pillow enthalten Bibliotheksinterna und temporaere Pfade.
        # Der technische Typ bleibt serverseitig im Log.
        app.logger.exception("PDF merge failed")
        return jsonify({"error": "Verarbeitung fehlgeschlagen."}), 500

    finally:
        # Laeuft auch bei Exception und bei Client-Abbruch - es bleiben
        # keine hochgeladenen Dateien im Temp-Verzeichnis zurueck.
        shutil.rmtree(work_dir, ignore_errors=True)


# =============================================================================
# SPIELERVERGLEICH (Phase 3)
#
# Drei Endpunkte:
#   /api/player-seasons  - waehlbare Saisons, keine API-Requests
#   /api/player-search   - Namenssuche, ein Request je Begriff und Saison
#   /api/player-compare  - Vergleich zweier Spieler
#
# Keiner dieser Endpunkte loest jemals einen vollstaendigen Ligaimport aus.
# Der Perzentil-Pool wird ausschliesslich von refresh_players.py befuellt.
# Fehlt er, liefert der Vergleich ehrliche Rohwerte ohne Perzentile.
# =============================================================================

# Aelteste Saison, fuer die Spielerdaten angeboten werden.
PLAYER_COMPARE_MIN_SEASON = 2020


@app.route("/api/player-seasons", methods=["GET"])
def api_player_seasons():
    """
    Waehlbare Saisons fuer den Spielervergleich.

    Reine Berechnung, kein API-Request. Zusaetzlich wird gemeldet, fuer
    welche Saisons ein Perzentil-Snapshot vorliegt, damit das Frontend
    das vorab kennzeichnen kann statt es erst nach dem Vergleich zu zeigen.
    """
    current = apisports_api.CURRENT_SEASON
    seasons = []

    for year in range(current, PLAYER_COMPARE_MIN_SEASON - 1, -1):
        snapshot = load_percentile_snapshot(year)
        seasons.append({
            "season": year,
            "label": f"{year}/{str(year + 1)[2:]}",
            "is_current": year == current,
            "percentiles_available": snapshot is not None,
            # Welche Turnier-Scopes es in DIESEM Saisonzyklus ueberhaupt
            # gibt. EM und WM finden nicht jede Saison statt; das Frontend
            # graut die Auswahl dann aus, statt einen Fehlzustand zu zeigen.
            # Bewusst getrennt von "liegen Daten vor" - ein stattgefundenes
            # Turnier ohne Import bleibt hier True und faellt erst beim
            # Vergleich auf den neutralen data_available-Zustand.
            "tournaments_available": tournament_scope_availability(year),
            "tournaments_imported": {
                scope: bool(
                    snapshot and 
                    snapshot.get("distributions_by_scope") and 
                    scope in snapshot["distributions_by_scope"]
                )
                for scope in TOURNAMENT_SCOPE_LEAGUE_IDS
            },
        })

    return jsonify({
        "seasons": seasons,
        "current_season": current,
        "min_query_length": PLAYER_MIN_QUERY_LENGTH,
        "leagues": [
            {"code": code, "label": COMPARE_LEAGUE_LABELS.get(code, code)}
            for code in COMPARE_LEAGUE_CODES
        ],
    })


@app.route("/api/player-search", methods=["GET"])
def api_player_search():
    """
    Spielersuche nach Namensbestandteil.

    Die Saison gehoert zur Suche, nicht zu einem nachgelagerten Filter:
    derselbe Spieler hat je Saison einen eigenen Statistikdatensatz.
    """
    query = (request.args.get("q") or "").strip()
    raw_season = request.args.get("season", "")

    if len(query) < PLAYER_MIN_QUERY_LENGTH:
        return jsonify({
            "error": f"Bitte mindestens {PLAYER_MIN_QUERY_LENGTH} Zeichen eingeben.",
            "results": [],
        }), 400

    try:
        season = int(raw_season)
    except (TypeError, ValueError):
        return jsonify({"error": "Ungueltige Saison.", "results": []}), 400

    if not (PLAYER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
        return jsonify({
            "error": f"Saison muss zwischen {PLAYER_COMPARE_MIN_SEASON} und "
                     f"{apisports_api.CURRENT_SEASON} liegen.",
            "results": [],
        }), 400

    try:
        results = player_search_players(query, season)
        return jsonify({
            "query": query,
            "season": season,
            "results": results,
            "comparable_count": sum(1 for r in results if r["comparable"]),
        })

    except ApisportsRateLimit as error:
        return jsonify({
            "error": "Das taegliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "detail": str(error),
            "results": [],
        }), 429

    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Die Spielersuche ist momentan nicht erreichbar. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
            "results": [],
        }), 503


@app.route("/api/player-compare", methods=["GET"])
def api_player_compare():
    """
    Vergleicht zwei Spieler.

    Parameter:
        a, b               Spieler-IDs
        season_a, season_b Saison je Spieler (unterschiedlich erlaubt)

    Unterschiedliche Saisons sind ausdruecklich zugelassen: "Musiala 2023/24
    gegen Musiala 2025/26" ist ein sinnvoller Vergleich. Perzentile werden
    dann je Spieler gegen den Pool SEINER Saison berechnet.
    """
    def _int_arg(name, default=None):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    player_a = _int_arg("a")
    player_b = _int_arg("b")

    if not player_a or not player_b:
        return jsonify({"error": "Es werden zwei Spieler-IDs benoetigt."}), 400

    if player_a == player_b:
        return jsonify({
            "error": "Bitte zwei unterschiedliche Spieler waehlen."
        }), 400

    season_a = _int_arg("season_a", apisports_api.CURRENT_SEASON)
    season_b = _int_arg("season_b", season_a)

    # Freier Vergleichsmodus der Oberflaeche: erzwingt das General-Radar,
    # auch wenn beide Spieler zufaellig dieselbe Position haben.
    force_general = (request.args.get("mode") or "").strip().lower() == "general"

    # Wettbewerbsumfang. Unbekannte Werte fallen auf den Standard zurueck
    # (alle Vereinswettbewerbe), statt einen Fehler zu erzeugen.
    scope = normalize_competition_scope(request.args.get("scope"))

    for season in (season_a, season_b):
        if season is None:
            return jsonify({"error": "Ungueltige Saison."}), 400
        if not (PLAYER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
            return jsonify({
                "error": f"Saison muss zwischen {PLAYER_COMPARE_MIN_SEASON} und "
                         f"{apisports_api.CURRENT_SEASON} liegen."
            }), 400

    try:
        profile_a = get_player_season_profile(player_a, season_a, scope=scope)
        profile_b = get_player_season_profile(player_b, season_b, scope=scope)

        # Der Perzentil-Pool ist saisonspezifisch. Bei unterschiedlichen
        # Saisons wird jeder Spieler gegen seinen eigenen Jahrgang gemessen.
        snapshot_a = load_percentile_snapshot(season_a)
        snapshot_b = (
            snapshot_a if season_a == season_b
            else load_percentile_snapshot(season_b)
        )

        comparison = build_player_comparison(
            profile_a, profile_b,
            snapshot=snapshot_a,
            snapshot_b=snapshot_b,
            force_general=force_general,
        )

        return jsonify({
            "player_a": _player_summary(profile_a),
            "player_b": _player_summary(profile_b),
            "comparison": comparison,
            # Scope-genau: fuer EM/WM gilt die Turnierhuerde, nicht die
            # Ligahuerde. Sonst stuende unter einem WM-Radar eine falsche
            # Mindestminutenangabe.
            "min_minutes": min_minutes_for_scope(scope),
        })

    except ApisportsRateLimit as error:
        return jsonify({
            "error": "Das taegliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "detail": str(error),
        }), 429

    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Der Vergleich kann momentan nicht geladen werden. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
        }), 503


def _player_summary(profile):
    """Kopfdaten eines Spielers fuer die Anzeige ueber dem Vergleich."""
    return {
        "player_id": profile.get("player_id"),
        "name": profile.get("name"),
        "photo": profile.get("photo"),
        "age": profile.get("age"),
        "nationality": profile.get("nationality"),
        "season": profile.get("season"),
        "season_label": (
            f"{profile['season']}/{str(profile['season'] + 1)[2:]}"
            if profile.get("season") else None
        ),
        "team_name": profile.get("team_name"),
        "team_logo": profile.get("team_logo"),
        "league_code": profile.get("league_code"),
        "league_label": profile.get("league_label"),
        "position": profile.get("position"),
        "position_label": POSITION_LABELS.get(profile.get("position")),
        "minutes": profile.get("minutes"),
        "data_available": profile.get("data_available"),
    }


# ---------------------------------------------------------------------------
# Spielerprofil (Block LIVE D1)
# ---------------------------------------------------------------------------
#
# EIN Spieler im Detail, im Unterschied zu /api/player-compare (IMMER zwei).
# Bewusst KEIN zweiter Loader: build_player_detail() ist ein duenner
# Formatierer um genau dieselbe get_player_season_profile(), die auch der
# Vergleich nutzt. Cache, Rohdatenabruf und Wettbewerbsumfang-Logik bleiben
# vollstaendig in src/data/player_compare_loader.py - hier wird nichts davon
# verdoppelt.
#
# Kennzahlenkatalog: dieselbe METRICS-Tabelle wie beim Radar (Phase 3.2).
# "Kernwerte" sind eine feste, immer gleiche Kurzliste; "weitere Statistiken"
# ist exakt das Radar-Profil der jeweiligen Position (RADAR_PROFILES in
# player_metrics.py) - das ist bereits die sinnvolle, positionsabhaengige
# Gruppierung, die dieses Feature braucht. Eine zweite Gruppierungslogik
# waere nur eine zweite Wahrheit ueber dieselben Daten.

PLAYER_DETAIL_CORE_METRICS = ("appearances", "minutes", "goals", "assists", "rating")

# Karten gelten fuer jede Position gleich und stehen deshalb nicht in den
# positionsspezifischen RADAR_PROFILES; hier werden sie den weiteren
# Statistiken jeder Position angehaengt.
PLAYER_DETAIL_UNIVERSAL_EXTRA_METRICS = ("cards_yellow", "cards_red")


def _metric_row(key, stats, minutes):
    """Eine Kennzahlenzeile mit Metadaten UND berechnetem Wert."""
    meta = describe_metric(key)
    if meta is None:
        return None
    return {**meta, "value": compute_metric(key, stats, minutes)}


def _player_detail_stats(profile):
    """
    Baut Kernwerte und weitere Statistiken eines Spielerprofils.

    Reine Funktion auf einem bereits geladenen Profil - kein API-Zugriff.
    """
    stats = profile.get("stats") or {}
    minutes = profile.get("minutes")
    position = profile.get("position")

    core = [
        row for row in (
            _metric_row(key, stats, minutes) for key in PLAYER_DETAIL_CORE_METRICS
        ) if row is not None
    ]

    extra_keys = list(PLAYER_DETAIL_UNIVERSAL_EXTRA_METRICS) + metrics_for_position(position)
    seen = set(PLAYER_DETAIL_CORE_METRICS)
    extra = []
    for key in extra_keys:
        if key in seen:
            continue
        seen.add(key)
        row = _metric_row(key, stats, minutes)
        if row is not None:
            extra.append(row)

    return core, extra


def _player_trophies_safe(player_id):
    """
    Erfolge eines Spielers, ohne dass ein Ausfall das gesamte Profil
    unbenutzbar macht (Block D2+).

    Anders als das Saisonprofil selbst ist das hier eine Zusatzkategorie
    - dieselbe Abwaegung wie bei den Nebenkategorien des Teamprofils
    (_soft_call in src/api/team_detail.py): ohne Erfolge ist das Profil
    weiterhin vollstaendig nutzbar, ohne Identitaet und Saisonwerte waere
    es das nicht.
    """
    if not player_id:
        return []
    try:
        return get_player_trophies(player_id)
    except (ApisportsUnavailable, ApisportsRateLimit):
        return []


def build_player_detail(profile):
    """Formatiert ein Spielerprofil fuer /api/player-profile."""
    core_stats, extra_stats = _player_detail_stats(profile)

    return {
        **_player_summary(profile),
        "firstname": profile.get("firstname"),
        "lastname": profile.get("lastname"),
        "height": profile.get("height"),
        "weight": profile.get("weight"),
        "birth_date": profile.get("birth_date"),

        "scope": profile.get("scope"),
        "scope_label": profile.get("scope_label"),
        "scope_hint": SCOPE_HINTS.get(profile.get("scope")),

        "competitions": profile.get("competitions") or [],
        "competition_count": profile.get("competition_count") or 0,

        "core_stats": core_stats,
        "extra_stats": extra_stats,

        # Saisonunabhaengig (siehe get_player_trophies) - bleibt beim
        # Scope-Wechsel unveraendert, kostet dabei aber keinen
        # zusaetzlichen Request: derselbe lange gecachte Wert wird bei
        # jedem Aufruf von build_player_detail() erneut eingefuegt.
        "trophies": _player_trophies_safe(profile.get("player_id")),
    }


@app.route("/api/player-profile", methods=["GET"])
def api_player_profile():
    """
    Ein einzelner Spieler im Detail (Block LIVE D1).

    Parameter:
        player_id  API-Football-Player-ID (Pflicht)
        season     API-Football-Saisonjahr, Standard: aktuelle Saison.
                   Kommt der Aufruf aus LIVE, ist das exakt der Wert aus
                   match.league.season - keine eigene Herleitung noetig.
        scope      Wettbewerbsumfang, Standard club_all. Unbekannte Werte
                   fallen wie ueberall sonst auf den Standard zurueck statt
                   einen Fehler zu erzeugen (normalize_scope()).

    Unbekannte Player-ID ergibt 404, nicht ein leeres 200 - der Unterschied
    zu "Spieler bekannt, aber keine Saisondaten" (data_available=False,
    Identitaet bleibt) ist fachlich wichtig und wird hier bewusst getrennt.
    """
    raw_player_id = (request.args.get("player_id") or "").strip()
    if not raw_player_id:
        return jsonify({"error": "Parameter player_id fehlt."}), 400

    try:
        player_id = int(raw_player_id)
    except ValueError:
        return jsonify({"error": "Ungueltige player_id."}), 400

    if player_id <= 0:
        return jsonify({"error": "Ungueltige player_id."}), 400

    raw_season = request.args.get("season")
    if raw_season is None or raw_season == "":
        season = apisports_api.CURRENT_SEASON
    else:
        try:
            season = int(raw_season)
        except ValueError:
            return jsonify({"error": "Ungueltige Saison."}), 400

    if not (PLAYER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
        return jsonify({
            "error": f"Saison muss zwischen {PLAYER_COMPARE_MIN_SEASON} und "
                     f"{apisports_api.CURRENT_SEASON} liegen."
        }), 400

    scope = normalize_competition_scope(request.args.get("scope"))

    try:
        profile = get_player_season_profile(player_id, season, scope=scope)

        if profile.get("player_id") is None:
            return jsonify({"error": "Spieler nicht gefunden."}), 404

        return jsonify(build_player_detail(profile))

    except ApisportsRateLimit as error:
        return jsonify({
            "error": "Das taegliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "detail": str(error),
        }), 429

    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Das Spielerprofil kann momentan nicht geladen werden. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
        }), 503


# ---------------------------------------------------------------------------
# Team-Detailseite (Block LIVE D2)
# ---------------------------------------------------------------------------
#
# Analog zu /api/player-profile: ein duenner Formatierer um
# src/api/team_detail.py, das die eigentliche Normalisierung und das
# Caching traegt. Diese Route validiert nur die Parameter und uebersetzt
# Providerfehler in FootSim-Fehlerantworten - keine eigene Fachlogik.

@app.route("/api/team-detail", methods=["GET"])
def api_team_detail():
    """
    Ein Team im Detail (Block LIVE D2).

    Parameter:
        team_id    API-Football-Team-ID (Pflicht)
        league_id  API-Football-Liga-ID (optional)
        season     API-Football-Saisonjahr (optional)

    league_id/season legen fest, gegen welchen Wettbewerb die
    Tabellenzeile gezogen wird. Aus LIVE kommen beide unveraendert aus
    dem bereits geladenen Match-Center-Payload (data.league.id/
    data.league.season) - keine eigene Herleitung, kein zusaetzlicher
    Request nur fuer diese beiden Werte.

    Fehlen sie (z. B. Team ueber einen anderen Weg geoeffnet), liefert
    die Antwort schlicht keine Tabellenzeile - kein Fehler, nur eine
    fehlende Kategorie wie jede andere auch (siehe build_team_detail()).
    """
    raw_team_id = (request.args.get("team_id") or "").strip()
    if not raw_team_id:
        return jsonify({"error": "Parameter team_id fehlt."}), 400

    try:
        team_id = int(raw_team_id)
    except ValueError:
        return jsonify({"error": "Ungueltige team_id."}), 400

    if team_id <= 0:
        return jsonify({"error": "Ungueltige team_id."}), 400

    def _optional_int(name):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    league_id = _optional_int("league_id")
    season = _optional_int("season")

    try:
        detail = team_detail.build_team_detail(team_id, league_id=league_id, season=season)

        if detail is None:
            return jsonify({"error": "Team nicht gefunden."}), 404

        return jsonify(detail)

    except ApisportsRateLimit as error:
        return jsonify({
            "error": "Das taegliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "detail": str(error),
        }), 429

    except ApisportsUnavailable as error:
        return jsonify({
            "error": "Das Teamprofil kann momentan nicht geladen werden. "
                     "Bitte spaeter erneut versuchen.",
            "detail": str(error),
        }), 503


# ---------------------------------------------------------------------------
# Scatter-Plot (Phase 3.2 Teil 2)
# ---------------------------------------------------------------------------
#
# Ein einziger Endpunkt liefert Punkte UND Metadaten in einer Antwort
# (Poolstatus, verfuegbare Achsen). Bewusst kein separater -meta-Endpunkt:
# das Frontend braucht beides ohnehin fuer denselben Render-Schritt, ein
# zweiter Request waere nur zusaetzliche Latenz ohne Nutzen.
#
# Macht KEINEN einzigen API-Request. Liest ausschliesslich den vorhandenen
# Player Pool (siehe load_scatter_points in player_pool.py) - denselben
# Pool, den auch die Perzentil-Berechnung des Radars nutzt.

# Metriken, die im Scatter als Achse waehlbar sind. Absichtlich ohne reine
# Ereigniszaehler wie appearances/lineups - die sagen fuer eine X/Y-Analyse
# wenig aus und waeren nur Rauschen im Dropdown.
SCATTER_AXIS_KEYS = [
    key for key in METRICS
    if key not in ("appearances", "lineups")
]

SCATTER_LEAGUE_CODES = set(COMPARE_LEAGUE_CODES)


def _scatter_axis_meta():
    """Metadaten aller waehlbaren Achsen, direkt aus dem METRICS-Katalog."""
    result = []
    for key in SCATTER_AXIS_KEYS:
        metric = METRICS[key]
        result.append({
            "key": key,
            "label": metric["label"],
            "kind": metric["kind"],
            "direction": metric["direction"],
            "description": metric["description"],
        })
    return result


@app.route("/api/player-scatter", methods=["GET"])
def api_player_scatter():
    x_key = (request.args.get("x") or "goals_per90").strip()
    y_key = (request.args.get("y") or "assists_per90").strip()

    if x_key not in SCATTER_AXIS_KEYS or y_key not in SCATTER_AXIS_KEYS:
        return jsonify({
            "error": "Unbekannte Kennzahl fuer X- oder Y-Achse.",
        }), 400

    if x_key == y_key:
        return jsonify({
            "error": "X- und Y-Achse duerfen nicht identisch sein.",
        }), 400

    position = (request.args.get("position") or "").strip()
    if position and position not in POSITION_GROUPS:
        return jsonify({"error": "Unbekannte Position."}), 400

    leagues_param = (request.args.get("leagues") or "").strip()
    if leagues_param:
        requested_leagues = [
            code.strip() for code in leagues_param.split(",") if code.strip()
        ]
    else:
        requested_leagues = list(COMPARE_LEAGUE_CODES)

    unknown_leagues = [c for c in requested_leagues if c not in SCATTER_LEAGUE_CODES]
    if unknown_leagues:
        return jsonify({
            "error": f"Unbekannte Liga(en): {', '.join(unknown_leagues)}",
        }), 400

    def _int_arg(name, default):
        raw = request.args.get(name)
        if raw in (None, ""):
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    season = _int_arg("season", apisports_api.CURRENT_SEASON)
    if season is None or not (PLAYER_COMPARE_MIN_SEASON <= season <= apisports_api.CURRENT_SEASON):
        return jsonify({"error": "Ungueltige Saison."}), 400

    # Wettbewerbsumfang - dieselben Modi wie im Radar. Der Pool haelt je
    # Scope eine eigene Kennzahlenmenge bereit, es entsteht dadurch kein
    # zusaetzlicher Import und kein API-Request.
    scope = normalize_competition_scope(request.args.get("scope"))

    # Standardhuerde je Wettbewerb: 450 fuer Liga/CL, 270 fuer die kurzen
    # Endrunden (EM/WM). Sie greift AUSSCHLIESSLICH, wenn der Aufrufer
    # keinen eigenen Wert mitgibt - eine ausdrueckliche Nutzereingabe hat
    # immer Vorrang, auch wenn sie hoeher oder niedriger liegt.
    min_minutes = _int_arg("min_minutes", min_minutes_for_scope(scope))
    if min_minutes is None or min_minutes < 0:
        return jsonify({"error": "Ungueltige Mindestminuten."}), 400

    # Ergebnis 1h gecacht. Der Pool selbst aendert sich nur durch einen
    # manuellen Import; ein kurzer Cache reicht, um wiederholte Requests
    # mit denselben Filtern (z. B. beim Zurueckblaettern) nicht neu zu
    # berechnen, ohne veraltete Daten nach einem Reimport lange vorzuhalten.
    cache_key = (
        f"scatter:{season}:{','.join(sorted(requested_leagues))}:"
        f"{position or 'all'}:{min_minutes}:{x_key}:{y_key}:{scope}"
    )

    def _compute():
        pts, used = load_scatter_points(
            season, requested_leagues, position, min_minutes, x_key, y_key,
            scope=scope,
        )
        return {"points": pts, "used_leagues": used}

    result = disk_cached_call(
        key=cache_key, ttl_seconds=3600, loader=_compute, source="player-pool",
    )

    used_leagues = result["used_leagues"]
    missing_leagues = [c for c in requested_leagues if c not in used_leagues]

    return jsonify({
        "points": result["points"],
        "point_count": len(result["points"]),

        "season": season,
        "season_label": f"{season}/{str(season + 1)[2:]}",
        "position": position or None,
        "position_label": POSITION_LABELS.get(position) if position else "Alle Positionen",
        "min_minutes": min_minutes,
        "scope": scope,
        "scope_label": SCOPE_LABELS.get(scope),
        "scope_hint": SCOPE_HINTS.get(scope),
        "scopes": [
            {"key": key, "label": SCOPE_LABELS.get(key), "hint": SCOPE_HINTS.get(key)}
            for key in COMPETITION_SCOPES
        ],
        "x": {"key": x_key, **{k: v for k, v in METRICS[x_key].items()
                                if k in ("label", "kind", "direction", "description")}},
        "y": {"key": y_key, **{k: v for k, v in METRICS[y_key].items()
                                if k in ("label", "kind", "direction", "description")}},

        # Poolstatus direkt mitgeliefert - kein zweiter Endpunkt noetig.
        "used_leagues": used_leagues,
        "missing_leagues": missing_leagues,
        "pool_complete": len(missing_leagues) == 0,

        "axes": _scatter_axis_meta(),
        "leagues": [
            {"code": code, "label": COMPARE_LEAGUE_LABELS.get(code, code)}
            for code in COMPARE_LEAGUE_CODES
        ],
        "positions": [
            {"key": pos, "label": POSITION_LABELS.get(pos, pos)}
            for pos in POSITION_GROUPS
        ],
    })


# =============================================================================
#  API: BIG GAMES (Block F1)
# =============================================================================
#
#  Big Games ist eine zusaetzliche Datenbasis INNERHALB des bestehenden
#  Spielervergleichs, kein eigener Bereich. Die drei Routen hier sind
#  duenne Formatierer um src/data/big_games_loader.py - Parametervalidierung
#  und Fehleruebersetzung, keine eigene Fachlogik.
#
#  VERTRAUENSGRENZE
#  ----------------
#  Der Browser darf ausschliesslich Spieler, Saisonbereich und
#  Darstellungswuensche schicken. Rang, Koeffizient, Gegnerstaerke,
#  Bedeutung, Zulassung und Score entstehen AUSSCHLIESSLICH serverseitig
#  aus den privaten Snapshots. Ein vom Client mitgeschicktes Gewicht wird
#  nirgends gelesen - es gibt schlicht keinen Parameter dafuer.
#
#  Die privaten UEFA-Koeffizienten- und FIFA-Rankingdateien selbst verlassen
#  den Server nie. Es gibt bewusst KEINE Route, die eine Rangliste ausliefert;
#  nach aussen gehen nur die je Spiel abgeleiteten Werte des angefragten
#  Vergleichs.

# Wettbewerbe, in denen die historische Big-Games-Suche nachsieht. Bewusst
# die bestehenden FootSim-Wettbewerbe und NICHT der komplette
# API-Football-Katalog: die Suche soll gezielt bleiben.
#
# Seit F1.1 teilt sich der normale Radar dieselbe Live-Suche als
# Rueckfallebene - die Liste steht deshalb an genau einer Stelle
# (src/data/live_player_search.py) statt zweimal.
BIG_GAMES_SEARCH_LEAGUE_CODES = live_player_search.LIVE_SEARCH_LEAGUE_CODES

# Laengster erlaubter Zeitraum. Fuenf Saisons decken den vorhandenen
# Snapshot-Bestand vollstaendig ab und begrenzen zugleich den Aufwand
# eines einzelnen Vergleichs.
BIG_GAMES_MAX_SEASON_SPAN = 5


def _big_games_season_bounds():
    """
    Aelteste und neueste Saison, fuer die Big Games ueberhaupt moeglich ist.

    Die bestehende Club-Big-Games-Abdeckung bleibt die Obergrenze der
    gemeinsamen Zeitraumwahl. Nationale F1+-Matches werden innerhalb
    derselben FootSim-Saisons hinzugefuegt und benutzen eigene FIFA-
    Jahressnapshots; sie erweitern weder die Auswahl noch die Population.
    """
    latest = apisports_api.CURRENT_SEASON
    seasons = uefa_coefficients.available_seasons(
        uefa_coefficients.EARLIEST_COEFFICIENT_SEASON, latest
    )
    return (min(seasons) if seasons else None,
            max(seasons) if seasons else None,
            seasons)


@app.route("/api/big-games-seasons", methods=["GET"])
def api_big_games_seasons():
    """
    Waehlbarer Zeitraum fuer Big Games. Kein API-Request, reine Auskunft.

    Liefert ausdruecklich NUR die Saisons, fuer die ein Snapshot vorliegt.
    Das Frontend kann damit unmoegliche Zeitraeume gar nicht erst anbieten,
    statt sie erst nach dem Vergleich als leer zu melden.
    """
    earliest, latest, seasons = _big_games_season_bounds()

    return jsonify({
        "available": bool(seasons),
        "earliest_season": earliest,
        "latest_season": latest,
        "max_span": BIG_GAMES_MAX_SEASON_SPAN,
        "seasons": [
            {
                "season": season,
                "label": uefa_coefficients.season_label(season),
                "provisional": uefa_coefficients.load_snapshot(season)["provisional"],
            }
            for season in seasons
        ],
    })


def _resolve_big_games_range(raw_from, raw_to):
    """
    Validiert einen Saisonbereich. Rueckgabe (from, to, None) oder (None, None, Fehler).
    """
    earliest, latest, seasons = _big_games_season_bounds()

    if not seasons:
        return None, None, "Für Big Games liegen derzeit keine Vergleichsdaten vor."

    try:
        season_from = int(raw_from)
        season_to = int(raw_to)
    except (TypeError, ValueError):
        return None, None, "Ungueltiger Zeitraum."

    if season_from > season_to:
        season_from, season_to = season_to, season_from

    if season_from < earliest or season_to > latest:
        return None, None, (
            f"Big Games ist derzeit für die Saisons "
            f"{uefa_coefficients.season_label(earliest)} bis "
            f"{uefa_coefficients.season_label(latest)} verfügbar."
        )

    if (season_to - season_from + 1) > BIG_GAMES_MAX_SEASON_SPAN:
        return None, None, (
            f"Maximal {BIG_GAMES_MAX_SEASON_SPAN} Saisons pro Vergleich."
        )

    return season_from, season_to, None


@app.route("/api/big-games-search", methods=["GET"])
def api_big_games_search():
    """
    Spielersuche fuer Big Games - ausdruecklich NICHT die Pool-Suche.

    Warum eine zweite Suche: /api/player-search durchsucht den lokal
    importierten Top-5-Pool. Der enthaelt nur Spieler, die in einer der
    fuenf Vergleichsligen der jeweiligen Saison gespielt haben. Fuer eine
    HISTORISCHE Big-Games-Analyse ist das zu eng - ein Spieler kann 2021/22
    in einer unserer Ligen gespielt haben und heute anderswo sein.

    Diese Route laesst deshalb API-Football direkt suchen, aber bewusst
    eingegrenzt auf die FootSim-Wettbewerbe des ANGEFRAGTEN ZEITRAUMS.

    Gesucht wird ueber den GESAMTEN Zeitraum, nicht nur ueber dessen
    letzte Saison (Block F1.1): ein Spieler, der nur in der ersten Saison
    in einem unserer Wettbewerbe stand und danach wechselte, muss fuer
    den Zeitraum trotzdem auffindbar bleiben.

    WICHTIG: Sie fuellt keinen Pool und veraendert keine Population. Die
    Perzentil- und Plot-Kohorte bleibt unberuehrt - siehe
    docs/player_comparison.md. Ein hier gefundener Spieler taucht dadurch
    NICHT in den Top-5-Plots auf.
    """
    query = (request.args.get("q") or "").strip()

    if len(query) < PLAYER_MIN_QUERY_LENGTH:
        return jsonify({
            "error": f"Bitte mindestens {PLAYER_MIN_QUERY_LENGTH} Zeichen eingeben.",
            "results": [],
        }), 400

    # Der Zeitraum wird mit derselben Funktion geprueft wie beim Vergleich -
    # Suche und Auswertung koennen dadurch nicht auseinanderlaufen.
    # "season" bleibt als Einzelwert zulaessig, damit aeltere Aufrufe
    # (und ein Zeitraum von genau einer Saison) unveraendert funktionieren.
    raw_from = request.args.get("season_from")
    raw_to = request.args.get("season_to")
    if raw_from is None and raw_to is None:
        raw_from = raw_to = request.args.get("season")

    season_from, season_to, error = _resolve_big_games_range(raw_from, raw_to)
    if error:
        return jsonify({"error": error, "results": []}), 400

    try:
        results = big_games_search_players(
            query, season_from, season_to, BIG_GAMES_SEARCH_LEAGUE_CODES)
    except ApisportsRateLimit:
        return jsonify({
            "error": "Das tägliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
            "results": [],
        }), 429
    except ApisportsUnavailable:
        return jsonify({
            "error": "Die Spielersuche ist derzeit nicht verfügbar.",
            "results": [],
        }), 503

    return jsonify({
        "query": query,
        "season_from": season_from,
        "season_to": season_to,
        "results": results,
    })


@app.route("/api/big-games-compare", methods=["GET"])
def api_big_games_compare():
    """
    Big-Games-Auswertung fuer einen oder zwei Spieler.

    Parameter:
        a            Player-ID (Pflicht)
        b            Player-ID (optional - Einzelauswertung ist zulaessig)
        season_from  API-Football-Saisonjahr
        season_to    API-Football-Saisonjahr

    Bewusst kein Positions- oder Metrikparameter: welche Kennzahlen
    sinnvoll sind, entscheidet die Position des Spielers und damit der
    Server (siehe big_games_profile).
    """
    def _player_arg(name, required):
        raw = (request.args.get(name) or "").strip()
        if not raw:
            if required:
                return None, f"Parameter {name} fehlt."
            return None, None
        try:
            value = int(raw)
        except ValueError:
            return None, f"Ungueltige Player-ID ({name})."
        if value <= 0:
            return None, f"Ungueltige Player-ID ({name})."
        return value, None

    player_a, error = _player_arg("a", required=True)
    if error:
        return jsonify({"error": error}), 400

    player_b, error = _player_arg("b", required=False)
    if error:
        return jsonify({"error": error}), 400

    season_from, season_to, error = _resolve_big_games_range(
        request.args.get("season_from"), request.args.get("season_to")
    )
    if error:
        return jsonify({"error": error}), 400

    try:
        result = {
            "season_from": season_from,
            "season_to": season_to,
            "a": big_games_profile(player_a, season_from, season_to),
            "b": (big_games_profile(player_b, season_from, season_to)
                  if player_b is not None else None),
        }
    except ApisportsRateLimit:
        return jsonify({
            "error": "Das tägliche Kontingent der Datenquelle ist aufgebraucht. "
                     "Bitte morgen erneut versuchen.",
        }), 429
    except ApisportsUnavailable:
        return jsonify({
            "error": "Die Big-Games-Daten sind derzeit nicht verfügbar.",
        }), 503

    return jsonify(result)


@app.errorhandler(413)
def pdf_file_too_large(error):
    return jsonify({"error": "Dateien zu gross. Maximal 50 MB pro Merge."}), 413


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    """
    Flask-WTF raises CSRFError (a 400) for a missing, invalid, or expired
    token, from a before_request hook that runs ahead of every route.
    Left to Flask's default handling, an HTTPException like this renders
    as an HTML error page - the frontend's fetch-based auth calls only
    understand JSON, so every CSRF failure surfaced as an opaque
    "HTTP 400 (Serverfehler)" instead of something actionable.

    This does not weaken CSRF protection - validate_csrf() has already
    run and already rejected the request by the time this fires. It only
    changes the response's shape, and gives the frontend a stable
    identifier (error_key) so it can distinguish "your token needs a
    refresh" from an ordinary validation failure.
    """
    return jsonify({
        "error": "Your session has expired. Please try again.",
        "error_key": "auth.csrfError",
    }), 400


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
