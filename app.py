import os
import requests
import json
from flask import Flask, request, jsonify, render_template, make_response
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling
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

# MySQL configuration (credentials provided by user request)
DB_CONFIG = {
    "host": "localhost",
    "user": "remoteuser",
    "password": "StrongPassword123!",
    "database": "creativity",
    "port": 3306,
}

# Simple connection pool to reuse connections
DB_POOL = pooling.MySQLConnectionPool(pool_name="creativity_pool", pool_size=5, **DB_CONFIG)


def get_db():
    return DB_POOL.get_connection()

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


def store_user_entry(user_id, timestamp, question, answer, feedback):
    if not user_id:
        raise ValueError("user_id is required")

    prefix = user_id[0].lower()
    table = TABLE_MAP.get(prefix)
    if not table:
        raise ValueError(f"Unknown user_id prefix: {user_id[0]}")

    conn = get_db()
    try:
        cur = conn.cursor()
        if prefix == "a":
            cur.execute(
                f"INSERT INTO {table} (user_id, time, question, answer) VALUES (%s, %s, %s, %s)",
                (user_id, timestamp, question, answer),
            )
        else:
            cur.execute(
                f"INSERT INTO {table} (user_id, time, question, answer, feedback) VALUES (%s, %s, %s, %s, %s)",
                (user_id, timestamp, question, answer, feedback),
            )
        conn.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


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
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        row = cur.fetchone()
        return jsonify({"ok": True, "result": row[0]}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=True)
