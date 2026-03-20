import os
import requests
import json
import base64
import io
import csv
import threading
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
try:
    from google import genai
except Exception:
    genai = None

app = Flask(__name__)
CORS(app)

OPENSCORE_URL = "https://openscoring.du.edu/llm"
MODEL = "ocsai1-4o"
TASK = "uses"
# Gemini config (paste your keys directly here)
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_KEY = "AIzaSyDt6jQwdMIXbtjWQpkAuYTOGRlSfOIK6Vg"
GOOGLE_API_KEY = "AIzaSyDt6jQwdMIXbtjWQpkAuYTOGRlSfOIK6Vg"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OCSAI_MODEL_DIR = os.path.join(BASE_DIR, "ocsai-d-large")
FIGURAL_DIR = os.path.join(BASE_DIR, "Figural")
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_HEADERS = ["user_id", "time", "question", "answer", "feedback"]
CSV_LOCK = threading.Lock()


_ocsai_processor = None
_ocsai_model = None
_ocsai_device = None


def get_ocsai():
    global _ocsai_processor, _ocsai_model, _ocsai_device
    if _ocsai_model is None or _ocsai_processor is None:
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        import torch

        _ocsai_device = "cuda" if torch.cuda.is_available() else "cpu"
        _ocsai_processor = AutoImageProcessor.from_pretrained(OCSAI_MODEL_DIR)
        _ocsai_model = AutoModelForImageClassification.from_pretrained(OCSAI_MODEL_DIR).to(_ocsai_device)
        _ocsai_model.eval()
    return _ocsai_processor, _ocsai_model, _ocsai_device

TABLE_MAP = {
    "a": "control",
    "b": "evaluative",
    "c": "informative",
    "d": "positive",
    "e": "negative",
}

PROMPT_MAP = {
    "c": os.path.join(BASE_DIR, "prompts", "informative.txt"),
    "d": os.path.join(BASE_DIR, "prompts", "positive.txt"),
    "e": os.path.join(BASE_DIR, "prompts", "negative.txt"),
}


def get_csv_path(prefix):
    table = TABLE_MAP.get(prefix)
    if not table:
        raise ValueError(f"Unknown user_id prefix: {prefix}")
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{table}.csv")


def store_user_entry(user_id, timestamp, question, answer, feedback):
    if not user_id:
        raise ValueError("user_id is required")

    prefix = user_id[0].lower()
    if prefix not in TABLE_MAP:
        raise ValueError(f"Unknown user_id prefix: {user_id[0]}")

    csv_path = get_csv_path(prefix)
    row = {
        "user_id": user_id,
        "time": timestamp,
        "question": question,
        "answer": answer,
        "feedback": "" if prefix == "a" else (feedback or ""),
    }

    with CSV_LOCK:
        file_exists = os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if not file_exists or os.path.getsize(csv_path) == 0:
                writer.writeheader()
            writer.writerow(row)


def load_prompt(prefix):
    path = PROMPT_MAP.get(prefix)
    if not path:
        raise ValueError(f"No prompt configured for prefix: {prefix}")
    with open(path, "r") as f:
        return f.read().strip()


def generate_gemini_feedback(prefix, question, answer):
    if genai is None:
        raise RuntimeError("google-genai SDK is not installed")
    api_key = GEMINI_API_KEY if GEMINI_API_KEY != "PASTE_YOUR_GEMINI_API_KEY_HERE" else GOOGLE_API_KEY
    if not api_key or api_key in ("PASTE_YOUR_GEMINI_API_KEY_HERE", "PASTE_YOUR_GOOGLE_API_KEY_HERE"):
        raise RuntimeError("Paste a real Gemini API key into app.py")

    prompt_text = load_prompt(prefix)
    full_prompt = (
        f"{prompt_text}\n\n"
        "Provide one short feedback message for the participant.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}\n"
        "Feedback:"
    )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
    )
    feedback = ""
    if response and getattr(response, "text", None):
        feedback = response.text.strip()
    if not feedback:
        raise RuntimeError("Empty feedback from Gemini")
    return feedback

def score_answer(item, answer, api_key=None):
    # Build CSV for ONE answer
    csv_input = f'"{item}","{answer.replace(chr(34), chr(34)*2)}"'

    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key

    params = {
        "model": MODEL,
        "task": TASK,
        "input": csv_input,
    }

    r = requests.post(OPENSCORE_URL, params=params, headers=headers, timeout=120)

    if r.status_code != 200:
        return {"error": r.text}, r.status_code

    # OpenScoring returns NaN (invalid JSON) → fix it
    clean_text = r.text.replace("NaN", "null")

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError:
        return {"error": "Failed to parse OpenScoring response"}, 500

    try:
        originality = data["scores"][0]["originality"]
    except (KeyError, IndexError, TypeError):
        return {"error": "Originality score not found"}, 500

    return {"originality": originality}, 200


@app.route("/", methods=["GET"])
def index():
    return render_template("landing.html")

@app.route("/templates/task.html", methods=["GET"])
def tasks():
    return render_template("task.html")

@app.route("/figural/<path:filename>", methods=["GET"])
def figural_file(filename):
    return send_from_directory(FIGURAL_DIR, filename)

@app.route("/score", methods=["POST"])  # <--- 3. Remove "OPTIONS" from here, CORS handles it
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
    api_key = data.get("api_key")

    if not item or not answer:
        return jsonify({"error": "item and answer are required"}), 400

    result, status = score_answer(item, answer, api_key)
    return jsonify(result), status


@app.route("/score-drawing", methods=["POST"])
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


@app.route("/store", methods=["POST"])
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

    if not user_id or not timestamp or not question or not answer:
        return jsonify({"error": "user_id, time, question, and answer are required"}), 400

    try:
        store_user_entry(user_id, timestamp, question, answer, feedback)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": "Failed to store entry"}), 500

    return jsonify({"status": "ok"}), 200


@app.route("/feedback", methods=["POST"])
def feedback():
    raw_data = request.get_data(as_text=True)
    try:
        data = json.loads(raw_data)
    except Exception:
        data = request.get_json()

    user_id = data.get("user_id")
    question = data.get("question")
    answer = data.get("answer")

    if not user_id or not question or not answer:
        return jsonify({"error": "user_id, question, and answer are required"}), 400

    prefix = user_id[0].lower()
    if prefix in ("a", "b"):
        return jsonify({"error": "No feedback for this group"}), 400

    try:
        msg = generate_gemini_feedback(prefix, question, answer)
        return jsonify({"feedback": msg}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Failed to generate feedback"}), 500

@app.route("/db-test", methods=["GET"])
def db_test():
    try:
        files = {}
        for prefix, table in TABLE_MAP.items():
            path = get_csv_path(prefix)
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists else 0
            files[table] = {"path": path, "exists": exists, "size": size}
        return jsonify({"ok": True, "storage": "csv", "files": files}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=True)
