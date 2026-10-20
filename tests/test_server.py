import base64
import csv
import io
import os
import time
import zipfile

import pytest

from creativity import config, llm, storage
from creativity.dashboard import build_participant

from .conftest import basic

PNG = "data:image/png;base64," + base64.b64encode(open(os.path.join(config.FIGURAL_DIR, "f1.png"), "rb").read()).decode()
BRICK = "Brick. Think of as many uses as you can."


def row(**overrides):
    return {"user_id": "C7", "time": "2026-10-02T10:00:00Z", "question": BRICK, "answer": "doorstop",
            "type": "answer", **overrides}


def read_csv(*parts):
    with open(os.path.join(config.DATA_DIR, *parts), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- pages ---

def test_participant_pages_are_public(client):
    for url in ["/", "/templates/task.html", "/healthz", "/static/css/site.css", "/figural/f1.png"]:
        assert client.get(url).status_code == 200, url


@pytest.mark.parametrize("url", ["/dashboard", "/admin", "/api/dashboard-data", "/api/admin/state",
                                 "/export/all.zip", "/export/control.csv", "/db-test"])
def test_researcher_pages_need_login(client, admin, ashley, url):
    assert client.get(url).status_code == 401
    assert client.get(url, headers=basic("admin", "wrong")).status_code == 401
    assert client.get(url, headers=basic("nobody", "test-pass")).status_code == 401
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url, headers=ashley).status_code == 200


# --- storing rows ---

def test_row_goes_to_group_and_participant_files(client):
    assert client.post("/store", json=row(score=1.25, duration_seconds=42)).status_code == 200
    assert read_csv("informative.csv") == read_csv("participants", "C7", "responses.csv")
    assert read_csv("informative.csv")[0]["answer"] == "doorstop"


def test_drawing_is_saved_as_png(client):
    assert client.post("/store", json=row(type="drawing", question="Figural Task 1", image=PNG)).status_code == 200
    path = read_csv("informative.csv")[0]["answer"]
    assert path.startswith("participants/C7/drawings/Figural_Task_1__") and path.endswith(".png")
    assert open(os.path.join(config.DATA_DIR, path), "rb").read() == base64.b64decode(PNG.split(",")[1])


@pytest.mark.parametrize("bad", [
    {"user_id": "../../x"}, {"user_id": "Z1"}, {"type": "whatever"},
    {"type": "mood_pleasant", "answer": "<img src=x onerror=alert(1)>"},
    {"type": "drawing", "image": "data:image/png;base64," + base64.b64encode(b"<svg>").decode()},
    {"answer": "x" * 3000},
])
def test_bad_rows_are_rejected(client, bad):
    assert client.post("/store", json=row(**bad)).status_code == 400


def test_old_group_rows_are_copied_into_participant_folders(client):
    with open(os.path.join(config.DATA_DIR, "control.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(config.CSV_HEADERS) + "\nA1,t1,answer,Brick.,wall,,,\nA2,t2,answer,Brick.,step,,,\n")
    client.post("/store", json=row())
    assert len(read_csv("participants", "A1", "responses.csv")) == 1
    assert len(read_csv("participants", "A2", "responses.csv")) == 1


# --- nonsense answers and unsafe feedback ---

@pytest.mark.parametrize("text,gibberish", [
    ("asdfgh", True), ("qwer", True), ("idk", True), ("aaaaaa", True), ("12345", True), ("sdfg hjkl", True),
    ("doorstop", False), ("hat", False), ("use it as a hat for a snowman", False),
])
def test_quick_gibberish_check(text, gibberish):
    assert llm.looks_like_gibberish(text) is gibberish


def test_nonsense_answer_gets_no_score_or_feedback(client, monkeypatch):
    monkeypatch.setattr(llm, "_openai_chat", lambda prompt, images=(): "NONSENSE")
    scored = client.post("/score", json={"item": "brick", "answer": "pizza is my favorite food"}).get_json()
    assert scored["nonsense"] and "originality" not in scored
    fed = client.post("/feedback", json={"user_id": "C7", "question": BRICK, "answer": "pizza is nice"}).get_json()
    assert fed["nonsense"] and fed["flag"] == config.NONSENSE_FLAG and "feedback" not in fed


def test_real_answer_gets_score_and_feedback(client, monkeypatch):
    assert client.post("/score", json={"item": "brick", "answer": "doorstop"}).get_json() == {"originality": 1.25}
    monkeypatch.setattr(llm, "_openai_chat", lambda prompt, images=(): "OK" if "one word" in prompt else "Try a museum.")
    fed = client.post("/feedback", json={"user_id": "C7", "question": BRICK, "answer": "doorstop"}).get_json()
    assert fed == {"feedback": "Try a museum."}


def test_check_failure_gives_benefit_of_the_doubt(monkeypatch):
    def boom(prompt, images=()):
        raise RuntimeError("OpenAI down")
    monkeypatch.setattr(llm, "_openai_chat", boom)
    assert llm.is_meaningful_answer(BRICK, "doorstop") is True


def test_violent_feedback_is_replaced(client, monkeypatch):
    monkeypatch.setattr(llm, "_openai_chat", lambda prompt, images=(): "OK" if "one word" in prompt else "It could be a weapon!")
    fed = client.post("/feedback", json={"user_id": "C7", "question": "Pencil.", "answer": "write"}).get_json()
    assert fed["feedback"] == config.SAFE_FALLBACK_FEEDBACK["c"]


@pytest.mark.parametrize("text,safe", [
    ("Try stabbing it", False), ("Use it as a weapon", False),
    ("A stable base shows real skill", True), ("Let's avoid harmful ideas. Try art instead.", True),
])
def test_word_filter(client, text, safe):
    assert llm.feedback_is_safe(text) is safe


def test_control_and_score_groups_get_no_llm_feedback(client):
    for uid in ["A1", "B1"]:
        assert client.post("/feedback", json={"user_id": uid, "question": BRICK, "answer": "doorstop"}).status_code == 400


# --- participant IDs, passwords and researcher accounts ---

def login(client, uid, password=None):
    return client.post("/api/login", json={"id": uid, "password": password}).get_json()


def test_issuing_ids_with_passwords(client, admin, ashley):
    assert login(client, "B7")["valid"]                                       # nothing issued yet: pilot mode
    made = client.post("/api/admin/ids", headers=ashley, json={"group": "auto", "count": 5}).get_json()["created"]
    assert [m["user_id"] for m in made] == ["A001", "B001", "C001", "D001", "E001"]
    assert all(len(m["password"]) == config.PARTICIPANT_PASSWORD_LENGTH and "password_hash" not in m for m in made)
    made = client.post("/api/admin/ids", headers=admin, json={"group": "C", "count": 2}).get_json()["created"]
    assert [m["user_id"] for m in made] == ["C002", "C003"]
    password = made[0]["password"]

    assert not login(client, "B7")["valid"]                                   # not issued
    assert not login(client, "C002")["valid"]                                 # password missing
    assert not login(client, "C002", "wrong1")["valid"]
    ok = login(client, "c002", f" {password.upper()} ")                       # case and spaces forgiven
    assert ok["valid"] and ok["token"]
    assert "password" not in open(os.path.join(config.DATA_DIR, "participant_ids.csv")).read().split("\n")[1]

    assert client.post("/store", json=row(user_id="B7")).status_code == 400
    assert client.post("/store", json=row(user_id="C002")).status_code == 403             # no token
    assert client.post("/store", json=row(user_id="C002", token="forged")).status_code == 403
    assert client.post("/store", json=row(user_id="C002", token=ok["token"])).status_code == 200

    state = client.get("/api/admin/state", headers=ashley).get_json()
    assert state["me"] == "ashley" and state["ids"][0]["created_by"] == "ashley"
    assert all(i["has_password"] and "password_hash" not in i for i in state["ids"])
    assert [i["user_id"] for i in state["ids"] if i["has_data"]] == ["C002"]
    assert client.post("/api/admin/ids", json={"count": 1}).status_code == 401
    assert client.post("/api/admin/ids", headers=admin, json={"count": 500}).status_code == 400


def test_reset_participant_password(client, admin):
    made = client.post("/api/admin/ids", headers=admin, json={"group": "D", "count": 1}).get_json()["created"][0]
    new = client.post("/api/admin/ids/D001/reset-password", headers=admin).get_json()["password"]
    assert new != made["password"]
    assert not login(client, "D001", made["password"])["valid"]
    assert login(client, "D001", new)["valid"]
    assert client.post("/api/admin/ids/D999/reset-password", headers=admin).status_code == 404


def test_ids_from_before_passwords_still_work(client, admin):
    with open(os.path.join(config.DATA_DIR, "participant_ids.csv"), "w") as f:
        f.write("user_id,group,created_by,created_at\nA001,control,ashley,2026-10-01\n")
    assert login(client, "A001")["valid"]                                     # old ID, no password
    assert client.post("/store", json=row(user_id="A001")).status_code == 200
    client.post("/api/admin/ids", headers=admin, json={"group": "A", "count": 1})
    assert [r["user_id"] for r in storage.load_issued_ids()] == ["A001", "A002"]


def test_researcher_accounts(client, admin):
    add = lambda body, who=admin: client.post("/api/admin/researchers", headers=who, json=body)
    assert add({"username": "vicky", "password": "short"}).status_code == 400
    assert add({"username": "Bad Name!", "password": "long-enough-1"}).status_code == 400
    assert add({"username": "ashley", "password": "long-enough-1"}).status_code == 400   # set in .env
    assert add({"username": "vicky", "password": "long-enough-1"}).status_code == 200
    vicky = basic("vicky", "long-enough-1")
    assert client.get("/admin", headers=vicky).status_code == 200
    assert client.get("/admin", headers=basic("vicky", "nope-nope-1")).status_code == 401
    accounts = {r["username"]: r for r in client.get("/api/admin/state", headers=vicky).get_json()["researchers"]}
    assert accounts["vicky"]["created_by"] == "admin" and accounts["admin"]["source"] == ".env"
    assert "long-enough-1" not in open(os.path.join(config.DATA_DIR, "researchers.json")).read()
    assert client.delete("/api/admin/researchers/vicky", headers=vicky).status_code == 400  # not yourself
    assert client.delete("/api/admin/researchers/admin", headers=vicky).status_code == 400  # .env login
    assert client.delete("/api/admin/researchers/vicky", headers=admin).status_code == 200
    assert client.get("/admin", headers=vicky).status_code == 401


# --- downloads and the weekly delete ---

def test_downloads(client, admin):
    client.post("/store", json=row(type="drawing", question="Figural Task 1", image=PNG))
    names = zipfile.ZipFile(io.BytesIO(client.get("/export/participant/C7.zip", headers=admin).data)).namelist()
    assert "C7/responses.csv" in names and any(n.startswith("C7/drawings/") for n in names)
    names = zipfile.ZipFile(io.BytesIO(client.get("/export/all.zip", headers=admin).data)).namelist()
    assert "data/informative.csv" in names and "data/participants/C7/responses.csv" in names
    assert client.get("/export/participant/Z9.zip", headers=admin).status_code == 404
    assert client.get("/participants/../informative.csv", headers=admin).status_code == 404


def test_delete_only_after_a_fresh_full_download(client, ashley):
    delete = lambda body: client.post("/api/admin/delete-data", headers=ashley, json=body)
    made = client.post("/api/admin/ids", headers=ashley, json={"group": "C", "count": 1}).get_json()["created"][0]
    token = login(client, "C001", made["password"])["token"]
    client.post("/store", json=row(user_id="C001", token=token))
    assert delete({"confirm": "DELETE"}).status_code == 409                  # nothing downloaded yet
    client.get("/export/all.zip", headers=ashley)
    assert delete({}).status_code == 400                                     # must type DELETE
    time.sleep(1.1)
    client.post("/store", json=row(user_id="C001", answer="paperweight", token=token))
    assert delete({"confirm": "DELETE"}).status_code == 409                  # new answers since download
    time.sleep(1.1)
    client.get("/export/all.zip", headers=ashley)
    assert delete({"confirm": "DELETE"}).status_code == 200
    assert not os.path.exists(os.path.join(config.DATA_DIR, "informative.csv"))
    assert os.listdir(os.path.join(config.DATA_DIR, "participants")) == []
    assert len(storage.load_issued_ids()) == 1                               # IDs are kept
    assert client.post("/store", json=row(user_id="C001", token=token)).status_code == 200


# --- dashboard grouping ---

def test_dashboard_blocks():
    rows = [dict(user_id="A001", time=f"t{i}", type=t, question=q, answer=a, score="", feedback="", duration_seconds=d)
            for i, (t, q, a, d) in enumerate([
                ("mood_pleasant", "Baseline (before starting)", "4", ""), ("mood_alert", "Baseline (before starting)", "3", ""),
                ("answer", "Brick.", "doorstop", "20"), ("answer", "Brick.", "step", "95"), ("answer", "Candle.", "light", "30"),
                ("mood_pleasant", "Check-in after verbal tasks", "5", ""), ("mood_alert", "Check-in after verbal tasks", "2", ""),
                ("drawing", "Figural Task 1", "participants/A001/drawings/x.png", "50")])]
    blocks = build_participant("A001", "control", rows)["tasks"]
    assert [b["kind"] for b in blocks] == ["checkin", "task", "task", "checkin", "task"]
    assert blocks[1]["duration_seconds"] == 95 and blocks[3]["mood_pleasant"] == "5"
