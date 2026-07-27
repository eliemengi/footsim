from flask import Flask, jsonify, render_template, request, send_file
import os
import io
import tempfile
import shutil
import requests
from werkzeug.utils import secure_filename
from pypdf import PdfWriter, PdfReader
from PIL import Image

from src.predict.matches_to_predict import (
    MATCHES_TO_PREDICT_CL_RO16,
    MATCHES_TO_PREDICT_CL_QF,
    MATCHES_TO_PREDICT_CL_SF,
    MATCHES_TO_PREDICT_CL,
    MATCHES_TO_PREDICT_EL
)

from src.predict.simulate_scores import simulate_selected_match

from src.api.league_api import (
    ApiUnavailable,
    get_season_info,
    get_standings,
    get_scorers,
    get_matchday_match_options,
    get_finished_season_matches,
)

from src.features.league_stats import build_league_profile, build_comparison
from src.utils import cache

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


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


# Pokalwettbewerbe laufen ueber die manuell gepflegten Paarungen
# in src/predict/matches_to_predict.py und nicht ueber Spieltage.
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
}

# =============================================================================
#  ENDE KONFIGURATION
# =============================================================================


COMPETITION_MATCHES = {
    "cl": MATCHES_TO_PREDICT_CL,
    "el": MATCHES_TO_PREDICT_EL,
}

CREST_BASE_URL = "https://crests.football-data.org"


def is_matchday_unlocked(competition_code, matchday):
    if UNLOCK_ALL_MATCHDAYS:
        return True

    config = LEAGUE_CONFIG.get(competition_code)
    if not config:
        return False

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


@app.route("/impressum")
def impressum():
    return render_template("impressum.html")


@app.route("/datenschutz")
def datenschutz():
    return render_template("datenschutz.html")


# =============================================================================
#  API: WETTBEWERBE
# =============================================================================

@app.route("/api/competitions", methods=["GET"])
def get_competitions():
    competitions = []

    for code, config in LEAGUE_CONFIG.items():
        unlocked = config["unlocked_matchdays"]

        if UNLOCK_ALL_MATCHDAYS:
            sub = "Alle Spieltage verfuegbar"
        elif not unlocked:
            sub = "Noch keine Spieltage freigeschaltet"
        elif len(unlocked) == 1:
            sub = f"Spieltag {unlocked[0]} verfuegbar"
        else:
            sub = f"Spieltag {min(unlocked)} bis {max(unlocked)} verfuegbar"

        competitions.append({
            "code": code,
            "name": config["name"],
            "country": config["country"],
            "type": "league",
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": True,
            "subtitle": sub,
            "coming_soon_text": "",
        })

    for code, config in CUP_CONFIG.items():
        competitions.append({
            "code": code,
            "name": config["name"],
            "country": "Europa",
            "type": "cup",
            "emblem": f"{CREST_BASE_URL}/{config['api_code']}.png",
            "available": config["available"],
            "subtitle": "Verfuegbar" if config["available"] else "Bald verfuegbar",
            "coming_soon_text": config["coming_soon_text"],
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
    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify([])

    try:
        season_info = get_season_info(config["api_code"])
        current = season_info.get("current_matchday") or 1
    except ApiUnavailable:
        current = 1

    matchdays = []

    for day in range(1, config["total_matchdays"] + 1):
        unlocked = is_matchday_unlocked(competition_code, day)

        matchdays.append({
            "matchday": day,
            "available": unlocked,
            "label": f"Spieltag {day}",
            "is_current": day == current,
            "message": "" if unlocked else "Noch nicht freigeschaltet",
        })

    return jsonify(matchdays)


# =============================================================================
#  API: SPIELE
# =============================================================================

@app.route("/api/matches", methods=["GET"])
def get_matches():
    competition_code = request.args.get("competition", "cl").lower()

    if competition_code in LEAGUE_CONFIG:
        config = LEAGUE_CONFIG[competition_code]

        try:
            matchday = int(request.args.get("matchday", 1))
        except (TypeError, ValueError):
            return jsonify({"error": "Ungueltiger Spieltag"}), 400

        if not is_matchday_unlocked(competition_code, matchday):
            return jsonify([])

        try:
            matches = get_matchday_match_options(
                competition_code=competition_code,
                api_code=config["api_code"],
                matchday=matchday,
                season=SEASON_OVERRIDE,
            )
            return jsonify(matches)
        except ApiUnavailable as error:
            return api_error(error)

    if competition_code == "cl":
        knockout_round = request.args.get("round", "ro16").lower()

        rounds = {
            "ro16": MATCHES_TO_PREDICT_CL_RO16,
            "qf": MATCHES_TO_PREDICT_CL_QF,
            "sf": MATCHES_TO_PREDICT_CL_SF,
        }

        return jsonify(build_match_response(rounds.get(knockout_round, {})))

    return jsonify(build_match_response(COMPETITION_MATCHES.get(competition_code, {})))


# =============================================================================
#  API: TABELLE
# =============================================================================

@app.route("/api/standings", methods=["GET"])
def api_standings():
    competition_code = request.args.get("competition", "").lower()
    table_type = request.args.get("type", "TOTAL").upper()

    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Tabelle"}), 400

    if table_type not in ("TOTAL", "HOME", "AWAY"):
        table_type = "TOTAL"

    try:
        standings = get_standings(config["api_code"], season=SEASON_OVERRIDE)
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

    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except (TypeError, ValueError):
        limit = 20

    config = LEAGUE_CONFIG.get(competition_code)

    if not config:
        return jsonify({"error": "Fuer diesen Wettbewerb gibt es keine Torjaegerliste"}), 400

    try:
        data = get_scorers(config["api_code"], season=SEASON_OVERRIDE, limit=limit)
    except ApiUnavailable as error:
        return api_error(error)

    return jsonify({
        "competition": config["name"],
        "season": data.get("season"),
        "scorers": data.get("scorers", []),
    })


# =============================================================================
#  API: LIGENVERGLEICH
# =============================================================================

@app.route("/api/compare", methods=["GET"])
def api_compare():
    """
    Vergleicht zwei bis fuenf Ligen anhand echter Saisondaten.
    Aufruf: /api/compare?leagues=bl1,pd,sa
    """
    raw = request.args.get("leagues", "")
    codes = [c.strip().lower() for c in raw.split(",") if c.strip()]
    codes = [c for c in codes if c in LEAGUE_CONFIG]

    # Doppelte entfernen, Reihenfolge beibehalten
    seen = set()
    codes = [c for c in codes if not (c in seen or seen.add(c))]

    if len(codes) < 2:
        return jsonify({"error": "Bitte mindestens zwei Ligen auswaehlen"}), 400

    if len(codes) > 5:
        return jsonify({"error": "Maximal fuenf Ligen gleichzeitig"}), 400

    profiles = []

    for code in codes:
        config = LEAGUE_CONFIG[code]

        try:
            standings = get_standings(config["api_code"], season=SEASON_OVERRIDE)
            matches = get_finished_season_matches(config["api_code"], season=SEASON_OVERRIDE)
        except ApiUnavailable as error:
            return api_error(error)

        profiles.append(
            build_league_profile(code, config["name"], standings, matches)
        )

    return jsonify(build_comparison(profiles))


# =============================================================================
#  API: SIMULATION
# =============================================================================

@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request Body fehlt"}), 400

    competition_code = data.get("competition", "cl")
    match_id = data.get("match_id")
    simulations = data.get("simulations", 5000)
    use_seed = data.get("use_seed", False)
    leg_mode = data.get("leg_mode", "first")

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

            result = simulate_selected_match(
                simulations=simulations,
                use_seed=use_seed,
                home_team=home_team,
                away_team=away_team
            )
            return jsonify(result)

        if not match_id:
            return jsonify({"error": "match_id fehlt"}), 400

        if competition_code == "cl":
            result = simulate_selected_match(
                match_id=match_id,
                simulations=simulations,
                use_seed=use_seed,
                leg_mode=leg_mode
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
        "leagues": seasons,
        "cache": cache.stats(),
    })


# =============================================================================
#  PDF MERGE TOOL
# =============================================================================

PDF_ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
PDF_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
PDF_MAX_FILES = 40


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

    except Exception as error:
        return jsonify({"error": f"Verarbeitung fehlgeschlagen: {str(error)}"}), 500

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.errorhandler(413)
def pdf_file_too_large(error):
    return jsonify({"error": "Dateien zu gross. Maximal 50 MB pro Merge."}), 413


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
