import requests
import json
from flask import Flask, request, jsonify, render_template, make_response
from flask_cors import CORS
import mysql.connector
from mysql.connector import pooling

app = Flask(__name__)
CORS(app)

OPENSCORE_URL = "https://openscoring.du.edu/llm"
MODEL = "ocsai1-4o"
TASK = "uses"

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
