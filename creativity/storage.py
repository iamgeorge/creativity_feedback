"""Everything that reads or writes files under config.DATA_DIR."""
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from . import config
from .config import CSV_HEADERS, DELETE_AFTER_EXPORT_SECONDS, FIGURAL_DIR, ID_HEADERS, TABLE_MAP

# Guards every CSV write. A thread lock: run the app as a single process.
CSV_LOCK = threading.Lock()


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_") or "unknown"


def get_csv_path(prefix):
    table = TABLE_MAP.get(prefix)
    if not table:
        raise ValueError(f"Unknown user_id prefix: {prefix}")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, f"{table}.csv")


def _migrate_legacy_csv(csv_path):
    """If a CSV exists with an older header (missing our current columns),
    move it aside instead of corrupting it with mismatched rows."""
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        first_line = f.readline().strip()
    current_header = ",".join(CSV_HEADERS)
    if first_line == current_header:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{csv_path}.legacy-{stamp}.bak"
    os.rename(csv_path, backup_path)


def participant_dir(user_id):
    return os.path.join(config.DATA_DIR, "participants", _safe_name(user_id))


def _append_row(csv_path, row):
    _migrate_legacy_csv(csv_path)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore", restval="")
        if not file_exists or os.path.getsize(csv_path) == 0:
            writer.writeheader()
        writer.writerow(row)


def _ensure_participant_files():
    """One-time: build participants/<id>/responses.csv from rows that were
    stored in the group CSVs before per-participant files existed.
    Built in a temp folder and renamed, so a crash can't leave it half done.
    Call with CSV_LOCK held."""
    root = os.path.join(config.DATA_DIR, "participants")
    if os.path.exists(root):
        return
    tmp_root = root + ".building"
    shutil.rmtree(tmp_root, ignore_errors=True)
    os.makedirs(tmp_root)
    for table in TABLE_MAP.values():
        group_csv = os.path.join(config.DATA_DIR, f"{table}.csv")
        if not os.path.exists(group_csv):
            continue
        with open(group_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("user_id"):
                    _append_row(os.path.join(tmp_root, _safe_name(row["user_id"]), "responses.csv"), row)
    os.rename(tmp_root, root)


def store_user_entry(user_id, timestamp, question, answer, feedback,
                      score=None, duration_seconds=None, row_type="answer"):
    if not user_id:
        raise ValueError("user_id is required")

    prefix = user_id[0].lower()
    if prefix not in TABLE_MAP:
        raise ValueError(f"Unknown user_id prefix: {user_id[0]}")

    csv_path = get_csv_path(prefix)
    row = {
        "user_id": user_id,
        "time": timestamp,
        "type": row_type or "answer",
        "question": question,
        "answer": answer,
        "score": "" if score is None else score,
        "feedback": "" if prefix == "a" else (feedback or ""),
        "duration_seconds": "" if duration_seconds is None else duration_seconds,
    }
    with CSV_LOCK:
        _ensure_participant_files()
        _append_row(csv_path, row)
        _append_row(os.path.join(participant_dir(user_id), "responses.csv"), row)


def to_image_data_url(image_str):
    """Validate a data URL or bare base64 PNG and return it as a data URL."""
    if not image_str.startswith("data:"):
        image_str = "data:image/png;base64," + image_str
    base64.b64decode(image_str.partition(",")[2], validate=True)
    return image_str


def save_drawing(user_id, question, image_str):
    """Save a drawing to participants/<user_id>/drawings/ and return its path
    relative to config.DATA_DIR. Every submission gets its own timestamped file."""
    png = base64.b64decode(to_image_data_url(image_str).partition(",")[2], validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Drawing must be a PNG image")
    with CSV_LOCK:
        _ensure_participant_files()  # before this creates participants/
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    rel_path = f"participants/{_safe_name(user_id)}/drawings/{_safe_name(question)}__{stamp}.png"
    abs_path = os.path.join(config.DATA_DIR, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(png)
    return rel_path


def figure_data_url(filename):
    """The original blank figure (Figural/<filename>) as a data URL."""
    path = os.path.join(FIGURAL_DIR, os.path.basename(filename))
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ids_path():
    return os.path.join(config.DATA_DIR, "participant_ids.csv")


def load_issued_ids():
    if not os.path.exists(_ids_path()):
        return []
    with open(_ids_path(), newline="", encoding="utf-8") as f:
        return [{h: row.get(h) or "" for h in ID_HEADERS} for row in csv.DictReader(f)]


def _write_issued_ids(rows):
    """Rewrite the whole ID list (also upgrades files from before passwords)."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _ids_path() + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ID_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, _ids_path())


def _new_participant_password():
    return "".join(secrets.choice(config.PARTICIPANT_PASSWORD_ALPHABET)
                   for _ in range(config.PARTICIPANT_PASSWORD_LENGTH))


def find_issued_id(user_id, issued=None):
    for row in issued if issued is not None else load_issued_ids():
        if row["user_id"].upper() == (user_id or "").upper():
            return row
    return None


def participant_id_allowed(user_id):
    issued = load_issued_ids()
    return not issued or find_issued_id(user_id, issued) is not None


def check_participant_login(user_id, password):
    """Before any ID is issued, any well-formed ID works (pilot testing).
    After that, the ID must be issued and, if it has one, the password must match."""
    issued = load_issued_ids()
    if not issued:
        return True
    row = find_issued_id(user_id, issued)
    if row is None:
        return False
    return not row["password_hash"] or check_password_hash(row["password_hash"], (password or "").strip().lower())


def create_participant_ids(group, count, created_by):
    """Issue `count` new IDs like "C007", each with a new password. group is a
    letter A-E, or "auto" to keep the groups balanced. Numbers run on per
    group, so odd/even (verbal-first vs figural-first) alternates within each
    group. Returns the new rows with the plain password (only stored hashed)."""
    with CSV_LOCK:
        issued = load_issued_ids()
        numbers = {letter.upper(): [0] for letter in TABLE_MAP}
        for row in issued:
            digits = re.sub(r"\D", "", row["user_id"])
            numbers[row["user_id"][0].upper()].append(int(digits or 0))
        created = []
        for _ in range(count):
            letter = min(numbers, key=lambda k: (len(numbers[k]), k)) if group == "auto" else group
            number = max(numbers[letter]) + 1
            numbers[letter].append(number)
            password = _new_participant_password()
            row = {"user_id": f"{letter}{number:03d}", "group": TABLE_MAP[letter.lower()],
                   "created_by": created_by, "created_at": datetime.now(timezone.utc).isoformat(),
                   "password_hash": generate_password_hash(password)}
            issued.append(row)
            created.append({**row, "password": password})
        _write_issued_ids(issued)
        return [{k: v for k, v in row.items() if k != "password_hash"} for row in created]


def reset_participant_password(user_id):
    """Give an issued ID a new password; returns it, or None if unknown."""
    with CSV_LOCK:
        issued = load_issued_ids()
        row = find_issued_id(user_id, issued)
        if row is None:
            return None
        password = _new_participant_password()
        row["password_hash"] = generate_password_hash(password)
        _write_issued_ids(issued)
        return password


# --- Participant session tokens -------------------------------------------
# After a successful login the page gets a token (an HMAC of the ID) and sends
# it with every saved row, so rows for password-protected IDs can't be posted
# by someone who only knows the ID.

def _secret_key():
    key = os.getenv("SECRET_KEY", "")
    if key:
        return key.encode()
    path = os.path.join(config.DATA_DIR, ".secret_key")
    if not os.path.exists(path):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip().encode()


def participant_token(user_id):
    return hmac.new(_secret_key(), user_id.upper().encode(), hashlib.sha256).hexdigest()


def participant_token_ok(user_id, token):
    """Only IDs with a password need a token; older IDs and pilot IDs don't."""
    row = find_issued_id(user_id)
    if row is None or not row["password_hash"]:
        return True
    return hmac.compare_digest(participant_token(user_id), token or "")


# --- Researcher accounts added on /admin -----------------------------------
# (Logins in .env keep working too; see config.RESEARCHER_LOGINS.)

def _researchers_path():
    return os.path.join(config.DATA_DIR, "researchers.json")


def load_researchers():
    if not os.path.exists(_researchers_path()):
        return {}
    with open(_researchers_path(), encoding="utf-8") as f:
        return json.load(f)


def _save_researchers(accounts):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = _researchers_path() + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)
    os.replace(tmp, _researchers_path())


def check_researcher_login(username, password):
    expected = config.RESEARCHER_LOGINS.get(username or "")
    if expected is not None:
        return hmac.compare_digest((password or "").encode(), expected.encode())
    account = load_researchers().get(username or "")
    return bool(account) and check_password_hash(account["password_hash"], password or "")


def researcher_logins_exist():
    return bool(config.RESEARCHER_LOGINS) or bool(load_researchers())


def add_researcher(username, password, created_by):
    with CSV_LOCK:
        accounts = load_researchers()
        accounts[username] = {"password_hash": generate_password_hash(password), "created_by": created_by,
                              "created_at": datetime.now(timezone.utc).isoformat()}
        _save_researchers(accounts)


def remove_researcher(username):
    with CSV_LOCK:
        accounts = load_researchers()
        if accounts.pop(username, None) is None:
            return False
        _save_researchers(accounts)
        return True


def _last_export_path():
    return os.path.join(config.DATA_DIR, ".last_export.json")


def _files_under(folder, prefix):
    for dirpath, _, filenames in os.walk(folder):
        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            yield path, os.path.join(prefix, os.path.relpath(path, folder))


def _response_files():
    """Every file holding participant responses (not the issued-ID list)."""
    files = [os.path.join(config.DATA_DIR, f"{t}.csv") for t in TABLE_MAP.values()]
    files += [path for path, _ in _files_under(os.path.join(config.DATA_DIR, "participants"), "")]
    return [path for path in files if os.path.exists(path)]


def data_status():
    last_export = None
    if os.path.exists(_last_export_path()):
        with open(_last_export_path(), encoding="utf-8") as f:
            last_export = json.load(f)
    files = _response_files()
    last_change = max((os.path.getmtime(path) for path in files), default=None)
    can_delete, reason = False, "There is no response data on the server."
    if files:
        exported_at = _parse_time(last_export["time"]).timestamp() if last_export else None
        if exported_at is None:
            reason = "Download everything first."
        elif exported_at < last_change:
            reason = "New responses were saved after the last download. Download everything again first."
        elif datetime.now(timezone.utc).timestamp() - exported_at > DELETE_AFTER_EXPORT_SECONDS:
            reason = "The last download is more than 30 minutes old. Download everything again first."
        else:
            can_delete, reason = True, ""
    return {"last_export": last_export, "has_data": bool(files), "can_delete": can_delete, "reason": reason}
