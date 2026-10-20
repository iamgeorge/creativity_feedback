"""Pages and endpoints used by participants (no login)."""
import base64
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from ..config import (FIGURAL_DIR, NONSENSE_FLAG, NONSENSE_MESSAGE, OPENSCORING_API_KEY, ROW_TYPES,
                      SEND_FIGURE_PREFIXES, USER_ID_RE)
from ..llm import generate_llm_feedback, is_meaningful_answer
from ..scoring import get_ocsai, score_answer
from ..storage import (_num_or_none, check_participant_login, figure_data_url, participant_id_allowed,
                       participant_token, participant_token_ok, save_drawing, store_user_entry, to_image_data_url)

logger = logging.getLogger(__name__)
bp = Blueprint("participant", __name__)
SCORING_POOL = ThreadPoolExecutor(max_workers=16)


@bp.route("/healthz", methods=["GET"])
def healthz():
    """For uptime checks: the app is up and answering."""
    return jsonify({"ok": True}), 200


@bp.route("/", methods=["GET"])
def index():
    return render_template("landing.html")


@bp.route("/templates/task.html", methods=["GET"])
def tasks():
    return render_template("task.html")


@bp.route("/figural/<path:filename>", methods=["GET"])
def figural_file(filename):
    return send_from_directory(FIGURAL_DIR, filename)


@bp.route("/api/login", methods=["POST"])
def participant_login():
    """Task page login: an ID the research team issued, plus its password.
    Returns a token the page sends with every saved row."""
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("id", "")).strip().upper()
    if not USER_ID_RE.fullmatch(user_id) or not check_participant_login(user_id, data.get("password")):
        return jsonify({"valid": False}), 200
    return jsonify({"valid": True, "token": participant_token(user_id)}), 200


@bp.route("/score", methods=["POST"])  # <--- 3. Remove "OPTIONS" from here, CORS handles it
def score():
    # Remove the manual OPTIONS check; flask-cors handles it automatically.
    
    # Get the data
    raw_data = request.get_data(as_text=True)
    try:
        data = json.loads(raw_data)
    except:
        data = request.get_json()

    item = data.get("item")
    answer = data.get("answer")
    api_key = data.get("api_key") or OPENSCORING_API_KEY or None

    if not item or not answer:
        return jsonify({"error": "item and answer are required"}), 400

    # Run the meaningful-answer check and the scoring call at the same time
    # (each takes seconds); the score is thrown away if the answer is nonsense.
    meaningful = SCORING_POOL.submit(is_meaningful_answer, item, answer)
    scored = SCORING_POOL.submit(score_answer, item, answer, api_key)
    if not meaningful.result():
        return jsonify({"nonsense": True, "message": NONSENSE_MESSAGE, "flag": NONSENSE_FLAG}), 200
    result, status = scored.result()
    return jsonify(result), status


@bp.route("/score-drawing", methods=["POST"])
def score_drawing():
    try:
        from PIL import Image
        import torch
    except Exception:
        return jsonify({"error": "Pillow and torch are required to score drawings"}), 500

    image = None

    if request.files and "image" in request.files:
        try:
            image = Image.open(request.files["image"].stream)
        except Exception:
            return jsonify({"error": "Invalid image upload"}), 400
    else:
        raw_data = request.get_data(as_text=True)
        try:
            data = json.loads(raw_data) if raw_data else request.get_json()
        except Exception:
            data = request.get_json(silent=True)

        if not data or "image" not in data:
            return jsonify({"error": "image is required"}), 400

        image_str = data.get("image", "")
        if image_str.startswith("data:"):
            parts = image_str.split(",", 1)
            if len(parts) != 2:
                return jsonify({"error": "Invalid data URL"}), 400
            image_str = parts[1]

        try:
            image_bytes = base64.b64decode(image_str)
            image = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return jsonify({"error": "Invalid base64 image"}), 400

    try:
        image = image.convert("RGB")
    except Exception:
        return jsonify({"error": "Invalid image format"}), 400

    try:
        processor, model, device = get_ocsai()
        inputs = processor(images=image, return_tensors="pt").to(device)
        with torch.no_grad():
            score = model(**inputs).logits.squeeze().item()
    except Exception:
        return jsonify({"error": "Failed to score image"}), 500

    return jsonify({"score": score}), 200


@bp.route("/store", methods=["POST"])
def store():
    raw_data = request.get_data(as_text=True)
    try:
        data = json.loads(raw_data)
    except:
        data = request.get_json()

    user_id = data.get("user_id")
    timestamp = data.get("time")
    question = data.get("question")
    answer = data.get("answer")
    feedback = data.get("feedback")
    score = data.get("score")
    duration_seconds = data.get("duration_seconds")
    row_type = data.get("type") or "answer"
    image_str = data.get("image")  # drawing rows carry the PNG

    if not user_id or not timestamp or not question or not answer:
        return jsonify({"error": "user_id, time, question, and answer are required"}), 400

    # Anyone can POST here, so only accept rows shaped like the task page's.
    if not isinstance(user_id, str) or not USER_ID_RE.fullmatch(user_id):
        return jsonify({"error": "Invalid user_id"}), 400
    if not participant_id_allowed(user_id):
        return jsonify({"error": "Unknown participant ID"}), 400
    if not participant_token_ok(user_id, data.get("token")):
        return jsonify({"error": "Please log in again"}), 403
    if row_type not in ROW_TYPES:
        return jsonify({"error": "Invalid type"}), 400
    if row_type.startswith("mood_") and str(answer) not in {"1", "2", "3", "4", "5"}:
        return jsonify({"error": "Mood ratings must be 1-5"}), 400
    if len(str(timestamp)) > 40 or len(str(question)) > 500 or len(str(answer)) > 2000 or len(str(feedback or "")) > 2000:
        return jsonify({"error": "Field too long"}), 400
    if _num_or_none(score) is None:
        score = None
    if _num_or_none(duration_seconds) is None:
        duration_seconds = None

    if image_str and row_type.startswith("drawing"):
        try:
            answer = save_drawing(user_id, question, image_str)
        except ValueError:
            return jsonify({"error": "Invalid drawing image"}), 400
        except OSError:
            logger.exception("Failed to save drawing")
            return jsonify({"error": "Failed to save drawing"}), 500

    try:
        store_user_entry(user_id, timestamp, question, answer, feedback,
                          score=score, duration_seconds=duration_seconds, row_type=row_type)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Failed to store entry")
        return jsonify({"error": "Failed to store entry"}), 500

    return jsonify({"status": "ok"}), 200


@bp.route("/feedback", methods=["POST"])
def feedback():
    raw_data = request.get_data(as_text=True)
    try:
        data = json.loads(raw_data)
    except Exception:
        data = request.get_json()

    user_id = data.get("user_id")
    question = data.get("question")
    answer = data.get("answer")
    image_str = data.get("image")  # figural tasks send the drawing instead of text
    figure_file = data.get("figure")  # and the blank figure's filename, e.g. "f1.png"

    if not user_id or not question or not (answer or image_str):
        return jsonify({"error": "user_id, question, and answer (or image) are required"}), 400

    prefix = user_id[0].lower()
    if prefix in ("a", "b"):
        return jsonify({"error": "No feedback for this group"}), 400

    image = None
    if image_str:
        try:
            image = to_image_data_url(image_str)
        except Exception:
            return jsonify({"error": "Invalid base64 image"}), 400

    figure = None
    if image and figure_file and prefix in SEND_FIGURE_PREFIXES:
        try:
            figure = figure_data_url(figure_file)
        except OSError:
            return jsonify({"error": "Unknown figure"}), 400

    if not image and not is_meaningful_answer(question, answer):
        return jsonify({"nonsense": True, "message": NONSENSE_MESSAGE, "flag": NONSENSE_FLAG}), 200

    try:
        msg = generate_llm_feedback(prefix, question, answer, image=image, figure=figure)
        return jsonify({"feedback": msg}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("Feedback generation failed")
        return jsonify({"error": "Failed to generate feedback"}), 500
