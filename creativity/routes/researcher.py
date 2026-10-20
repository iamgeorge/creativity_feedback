"""Researcher-only pages: dashboard, downloads, and the admin page."""
import csv
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, Response, g, jsonify, render_template, request, send_file, send_from_directory

from .. import config
from ..auth import researcher_only
from ..config import CSV_HEADERS, TABLE_MAP, USER_ID_RE
from ..dashboard import build_participant
from ..storage import (CSV_LOCK, _ensure_participant_files, _files_under, _last_export_path, _safe_name, add_researcher,
                       create_participant_ids, data_status, get_csv_path, load_issued_ids, load_researchers,
                       participant_dir, remove_researcher, reset_participant_password)

logger = logging.getLogger(__name__)
bp = Blueprint("researcher", __name__)


@bp.route("/admin", methods=["GET"])
@researcher_only
def admin():
    return render_template("admin.html")


@bp.route("/api/admin/state", methods=["GET"])
@researcher_only
def admin_state():
    with CSV_LOCK:
        ids = load_issued_ids()
        started = {name.upper() for name in os.listdir(os.path.join(config.DATA_DIR, "participants"))} \
            if os.path.isdir(os.path.join(config.DATA_DIR, "participants")) else set()
        for row in ids:
            row["has_data"] = row["user_id"].upper() in started
            row["has_password"] = bool(row.pop("password_hash"))
        researchers = [{"username": name, "source": ".env", "created_by": "", "created_at": ""}
                       for name in config.RESEARCHER_LOGINS]
        researchers += [{"username": name, "source": "admin page", "created_by": info["created_by"],
                         "created_at": info["created_at"]}
                        for name, info in load_researchers().items() if name not in config.RESEARCHER_LOGINS]
        return jsonify({"me": g.researcher, "ids": ids, "researchers": researchers, "data": data_status()}), 200


@bp.route("/api/admin/ids/<user_id>/reset-password", methods=["POST"])
@researcher_only
def admin_reset_password(user_id):
    password = reset_participant_password(user_id)
    if password is None:
        return jsonify({"error": "Unknown participant ID"}), 404
    return jsonify({"user_id": user_id.upper(), "password": password}), 200


@bp.route("/api/admin/researchers", methods=["POST"])
@researcher_only
def admin_add_researcher():
    """Add a researcher login (or change its password)."""
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    password = str(data.get("password", ""))
    if not config.RESEARCHER_USERNAME_RE.fullmatch(username):
        return jsonify({"error": "Usernames are 2-32 characters: lowercase letters, numbers, dot, dash or underscore."}), 400
    if username in config.RESEARCHER_LOGINS:
        return jsonify({"error": "This login is set in the server's .env file; change it there."}), 400
    if len(password) < config.MIN_RESEARCHER_PASSWORD:
        return jsonify({"error": f"Passwords need at least {config.MIN_RESEARCHER_PASSWORD} characters."}), 400
    add_researcher(username, password, g.researcher)
    return jsonify({"username": username}), 200


@bp.route("/api/admin/researchers/<username>", methods=["DELETE"])
@researcher_only
def admin_remove_researcher(username):
    if username == g.researcher:
        return jsonify({"error": "You can't remove the account you're signed in with."}), 400
    if username in config.RESEARCHER_LOGINS:
        return jsonify({"error": "This login is set in the server's .env file; remove it there."}), 400
    if not remove_researcher(username):
        return jsonify({"error": "No such account."}), 404
    return jsonify({"removed": username}), 200


@bp.route("/api/admin/ids", methods=["POST"])
@researcher_only
def admin_create_ids():
    data = request.get_json(silent=True) or {}
    group = str(data.get("group", "auto"))
    group = group.upper() if group.lower() in TABLE_MAP else "auto"
    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        count = 0
    if not 1 <= count <= 100:
        return jsonify({"error": "count must be between 1 and 100"}), 400
    return jsonify({"created": create_participant_ids(group, count, g.researcher)}), 200


@bp.route("/api/admin/delete-data", methods=["POST"])
@researcher_only
def admin_delete_data():
    """Delete all participant responses from the server. Only allowed right
    after a full download that already contains every saved row. The list
    of issued IDs is kept so numbers are never reused."""
    if (request.get_json(silent=True) or {}).get("confirm") != "DELETE":
        return jsonify({"error": 'Type DELETE to confirm.'}), 400
    with CSV_LOCK:
        status = data_status()
        if not status["can_delete"]:
            return jsonify({"error": status["reason"]}), 409
        for path in [os.path.join(config.DATA_DIR, f"{t}.csv") for t in TABLE_MAP.values()]:
            if os.path.exists(path):
                os.remove(path)
        shutil.rmtree(os.path.join(config.DATA_DIR, "participants"))
        os.makedirs(os.path.join(config.DATA_DIR, "participants"))  # so old CSVs are never re-imported
        os.remove(_last_export_path())
        logger.warning("Response data deleted by %s", g.researcher)
    return jsonify({"status": "deleted"}), 200


@bp.route("/dashboard", methods=["GET"])
@researcher_only
def dashboard():
    return render_template("dashboard.html")


@bp.route("/participants/<path:filename>", methods=["GET"])
@researcher_only
def participant_file(filename):
    """Any file in a participant's folder, e.g. /participants/C2/drawings/<file>.png"""
    return send_from_directory(os.path.join(config.DATA_DIR, "participants"), filename)


def _zip_response(paths_and_names, download_name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, name in paths_and_names:
            zf.write(path, name)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=download_name)


@bp.route("/export/participant/<user_id>.zip", methods=["GET"])
@researcher_only
def export_participant(user_id):
    """One participant's responses.csv and drawings."""
    with CSV_LOCK:
        _ensure_participant_files()
        folder = participant_dir(user_id)
        if not USER_ID_RE.fullmatch(user_id) or not os.path.isdir(folder):
            return jsonify({"error": "Unknown participant"}), 404
        return _zip_response(list(_files_under(folder, _safe_name(user_id))), f"{_safe_name(user_id)}.zip")


@bp.route("/export/all.zip", methods=["GET"])
@researcher_only
def export_all():
    """Everything: the group CSVs plus every participant folder (also a handy backup)."""
    with CSV_LOCK:
        _ensure_participant_files()
        files = [(os.path.join(config.DATA_DIR, f"{t}.csv"), f"data/{t}.csv")
                 for t in TABLE_MAP.values() if os.path.exists(os.path.join(config.DATA_DIR, f"{t}.csv"))]
        files += list(_files_under(os.path.join(config.DATA_DIR, "participants"), "data/participants"))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        response = _zip_response(files, f"creativity-data-{stamp}.zip")
        # Remember when (and by whom) everything was last downloaded.
        with open(_last_export_path(), "w", encoding="utf-8") as f:
            json.dump({"time": datetime.now(timezone.utc).isoformat(), "by": g.researcher}, f)
        return response


@bp.route("/export/<table>.csv", methods=["GET"])
@researcher_only
def export_csv(table):
    if table not in TABLE_MAP.values():
        return jsonify({"error": "Unknown table"}), 404
    path = os.path.join(config.DATA_DIR, f"{table}.csv")
    with CSV_LOCK:
        content = open(path, encoding="utf-8").read() if os.path.exists(path) else ",".join(CSV_HEADERS) + "\n"
    return Response(content, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{table}.csv"'})


@bp.route("/api/dashboard-data", methods=["GET"])
@researcher_only
def dashboard_data():
    groups = {}
    by_user = {}
    for prefix, table in TABLE_MAP.items():
        path = get_csv_path(prefix)
        rows = []
        if os.path.exists(path):
            with CSV_LOCK:
                with open(path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
        groups[table] = {"count": len(rows)}
        for row in rows:
            uid = row.get("user_id")
            if not uid:
                continue
            by_user.setdefault((table, uid), []).append(row)

    participants = []
    for (table, uid), rows in by_user.items():
        rows.sort(key=lambda r: r.get("time") or "")
        participants.append(build_participant(uid, table, rows))
    participants.sort(key=lambda p: p.get("last_seen") or "", reverse=True)

    return jsonify({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "groups": groups,
        "participants": participants,
    }), 200


@bp.route("/db-test", methods=["GET"])
@researcher_only
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
