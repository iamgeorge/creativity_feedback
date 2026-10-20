"""Offline tests: a temporary data folder, fixed logins, and no network calls."""
import base64

import pytest

from creativity import config, create_app, llm, scoring


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code, self.text = payload, status_code, str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RESEARCHER_LOGINS", {"admin": "test-pass", "ashley": "pw-a"})
    # The model says OK to everything unless a test replaces this.
    monkeypatch.setattr(llm, "_openai_chat", lambda prompt, images=(): "OK")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: FakeResponse({"results": [{"flagged": False}]}))
    monkeypatch.setattr(scoring.requests, "post",
                        lambda *a, **k: FakeResponse('{"scores": [{"originality": 1.25}]}'))
    return create_app(preload_drawing_model=False).test_client()


def basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def admin():
    return basic("admin", "test-pass")


@pytest.fixture
def ashley():
    return basic("ashley", "pw-a")
