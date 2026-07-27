from flask import Flask, jsonify, render_template, request, send_file
import io
import tempfile
import shutil
from werkzeug.utils import secure_filename
from pypdf import PdfWriter, PdfReader
from PIL import Image
import os
import requests


from src.predict.matches_to_predict import (
    MATCHES_TO_PREDICT_CL_RO16,
    MATCHES_TO_PREDICT_CL_QF,
    MATCHES_TO_PREDICT_CL_SF,
    MATCHES_TO_PREDICT_CL,
    MATCHES_TO_PREDICT_EL
)

from src.predict.simulate_scores import simulate_selected_match
from src.api.football_api import (
    get_bundesliga_matchday_match_options,
    get_premier_league_matchday_match_options,
    get_laliga_matchday_match_options,
    get_serie_a_matchday_match_options
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_API_KEY")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

COMPETITION_CONFIG = {
    "cl": {
        "name": "Champions League",
        "api_code": "CL",
        "coming_soon_text": ""
    },
    "el": {
        "name": "Europa League",
        "api_code": "EL",
        "coming_soon_text": "Europa League wird bald freigeschaltet."
    },
    "bl1": {
        "name": "Bundesliga",
        "api_code": "BL1",
        "coming_soon_text": ""
    },
    "pl": {
        "name": "Premier League",
        "api_code": "PL",
        "coming_soon_text": ""
    },
    "pd": {
        "name": "LaLiga",
        "api_code": "PD",
        "coming_soon_text": ""
    },
    "sa": {
        "name": "Serie A",
        "api_code": "SA",
        "coming_soon_text": ""
    }
}

COMPETITION_MATCHES = {
    "cl": MATCHES_TO_PREDICT_CL,
    "el": MATCHES_TO_PREDICT_EL,
    "bl1": {},
    "pl": {},
    "pd": {},
    "sa": {}
}

BUNDESLIGA_ENABLED_MATCHDAYS = set(range(28, 35))
PREMIER_LEAGUE_ENABLED_MATCHDAYS = set(range(32, 39))
LALIGA_ENABLED_MATCHDAYS = set(range(30, 39))
SERIEA_ENABLED_MATCHDAYS = set(range(31, 39))

LEAGUE_SEASON = 2025


def get_headers():
    if not FOOTBALL_DATA_API_KEY:
        return {}
    return {
        "X-Auth-Token": FOOTBALL_DATA_API_KEY
    }


def fetch_competition_emblem(api_code):
    if not FOOTBALL_DATA_API_KEY:
        return None

    try:
        response = requests.get(
            f"{FOOTBALL_DATA_BASE_URL}/competitions/{api_code}",
            headers=get_headers(),
            timeout=8
        )
        if response.ok:
            data = response.json()
            return data.get("emblem")
    except Exception:
        return None

    return None


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/competitions", methods=["GET"])
def get_competitions():
    competitions = []

    for code, config in COMPETITION_CONFIG.items():
        matches = COMPETITION_MATCHES.get(code, {})
        available = len(matches) > 0

        if code in ["bl1", "pl", "pd", "sa"]:
            available = True

        competitions.append({
            "code": code,
            "name": config["name"],
            "api_code": config["api_code"],
            "emblem": fetch_competition_emblem(config["api_code"]),
            "available": available,
            "coming_soon_text": config["coming_soon_text"]
        })

    return jsonify(competitions)


@app.route("/api/matchdays", methods=["GET"])
def get_matchdays():
    competition_code = request.args.get("competition", "").lower()

    if competition_code == "bl1":
        matchdays = []
        for day in range(28, 35):
            matchdays.append({
                "matchday": day,
                "available": day in BUNDESLIGA_ENABLED_MATCHDAYS,
                "label": f"Spieltag {day}",
                "message": "" if day in BUNDESLIGA_ENABLED_MATCHDAYS else "Noch nicht verfügbar"
            })
        return jsonify(matchdays)

    if competition_code == "pl":
        matchdays = []
        for day in range(32, 39):
            matchdays.append({
                "matchday": day,
                "available": day in PREMIER_LEAGUE_ENABLED_MATCHDAYS,
                "label": f"Matchday {day}",
                "message": "" if day in PREMIER_LEAGUE_ENABLED_MATCHDAYS else "Noch nicht verfügbar"
            })
        return jsonify(matchdays)

    if competition_code == "pd":
        matchdays = []
        for day in range(30, 39):
            matchdays.append({
                "matchday": day,
                "available": day in LALIGA_ENABLED_MATCHDAYS,
                "label": f"Matchday {day}",
                "message": "" if day in LALIGA_ENABLED_MATCHDAYS else "Noch nicht verfügbar"
            })
        return jsonify(matchdays)

    if competition_code == "sa":
        matchdays = []
        for day in range(31, 39):
            matchdays.append({
                "matchday": day,
                "available": day in SERIEA_ENABLED_MATCHDAYS,
                "label": f"Matchday {day}",
                "message": "" if day in SERIEA_ENABLED_MATCHDAYS else "Noch nicht verfügbar"
            })
        return jsonify(matchdays)

    return jsonify([])


@app.route("/api/matches", methods=["GET"])
def get_matches():
    competition_code = request.args.get("competition", "cl").lower()

    if competition_code == "bl1":
        matchday = int(request.args.get("matchday", min(BUNDESLIGA_ENABLED_MATCHDAYS)))

        if matchday not in BUNDESLIGA_ENABLED_MATCHDAYS:
            return jsonify([])

        matches = get_bundesliga_matchday_match_options(
            matchday=matchday,
            season=LEAGUE_SEASON
        )
        return jsonify(matches)

    if competition_code == "pl":
        matchday = int(request.args.get("matchday", min(PREMIER_LEAGUE_ENABLED_MATCHDAYS)))

        if matchday not in PREMIER_LEAGUE_ENABLED_MATCHDAYS:
            return jsonify([])

        matches = get_premier_league_matchday_match_options(
            matchday=matchday,
            season=LEAGUE_SEASON
        )
        return jsonify(matches)

    if competition_code == "pd":
        matchday = int(request.args.get("matchday", min(LALIGA_ENABLED_MATCHDAYS)))

        if matchday not in LALIGA_ENABLED_MATCHDAYS:
            return jsonify([])

        matches = get_laliga_matchday_match_options(
            matchday=matchday,
            season=LEAGUE_SEASON
        )
        return jsonify(matches)

    if competition_code == "sa":
        matchday = int(request.args.get("matchday", min(SERIEA_ENABLED_MATCHDAYS)))

        if matchday not in SERIEA_ENABLED_MATCHDAYS:
            return jsonify([])

        matches = get_serie_a_matchday_match_options(
            matchday=matchday,
            season=LEAGUE_SEASON
        )
        return jsonify(matches)

    if competition_code == "cl":
        knockout_round = request.args.get("round", "ro16").lower()

        if knockout_round == "ro16":
            return jsonify(build_match_response(MATCHES_TO_PREDICT_CL_RO16))

        if knockout_round == "qf":
            return jsonify(build_match_response(MATCHES_TO_PREDICT_CL_QF))

        if knockout_round == "sf":
            return jsonify(build_match_response(MATCHES_TO_PREDICT_CL_SF))

        return jsonify([])

    competition_matches = COMPETITION_MATCHES.get(competition_code, {})
    return jsonify(build_match_response(competition_matches))


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
        if competition_code in ["bl1", "pl", "pd", "sa"]:
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

        return jsonify({
            "error": "Aktuell nicht verfügbar."
        }), 400

    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": f"Interner Fehler: {str(error)}"}), 500


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
    """Baut einen sicheren Dateinamen mit .pdf Endung."""
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

    # Ein einziges Arbeitsverzeichnis. Das finally unten raeumt es in
    # JEDEM Fall auf, egal ob Erfolg, Fehler oder frueher Return.
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
                        # Leeres Passwort probieren, viele PDFs sind nur
                        # gegen Bearbeitung geschuetzt, nicht gegen Lesen
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

        # Ergebnis in den Speicher lesen, damit das Arbeitsverzeichnis
        # sofort geloescht werden kann. Bei maximal 50 MB unproblematisch
        # und deutlich robuster als das Streamen von der Platte, wo der
        # Cleanup mit dem Versand ins Rennen geraten kann.
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