"""Settings and constants. Paths are relative to the project root.

DATA_DIR is read through this module at call time (`config.DATA_DIR`), so
tests and experiments can point it at a temporary folder."""
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCSAI_MODEL_DIR = os.path.join(BASE_DIR, "ocsai-d-large")
FIGURAL_DIR = os.path.join(BASE_DIR, "Figural")
# Storage layout (all under DATA_DIR):
#   <group>.csv                          every row for one group (control.csv, ...)
#   participants/<user_id>/responses.csv every row for one participant (same columns)
#   participants/<user_id>/drawings/     that participant's drawing PNGs
#   participant_ids.csv                  IDs issued on /admin
# Row type: "answer" | "drawing" | "drawing_unsubmitted" | "mood_pleasant" | "mood_alert"
# For drawing rows, "answer" is the PNG's path relative to DATA_DIR.
DATA_DIR = os.getenv("DATA_DIR") or os.path.join(BASE_DIR, "data")


OPENSCORE_URL = "https://openscoring.du.edu/llm"


MODEL = "ocsai1-4o"


TASK = "uses"


OPENAI_URL = "https://api.openai.com/v1/chat/completions"


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")


# Only for reasoning models (gpt-5.x); set OPENAI_REASONING_EFFORT= (empty) for gpt-4o/4.1.
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "low").strip()


OPENSCORING_API_KEY = os.getenv("OPENSCORING_API_KEY", "").strip()


# Storage layout (all under DATA_DIR):
#   <group>.csv                          every row for one group (control.csv, ...)
#   participants/<user_id>/responses.csv every row for one participant (same columns)
#   participants/<user_id>/drawings/     that participant's drawing PNGs
# type: "answer" | "drawing" | "drawing_unsubmitted" | "mood_pleasant" | "mood_alert"
# For drawing rows, "answer" is the PNG's path relative to DATA_DIR
# (e.g. "participants/C2/drawings/Figural_Task_1__20260925T101500123456Z.png").
CSV_HEADERS = ["user_id", "time", "type", "question", "answer", "score", "feedback", "duration_seconds"]


ROW_TYPES = {"answer", "drawing", "drawing_unsubmitted", "mood_pleasant", "mood_alert"}


USER_ID_RE = re.compile(r"[A-Ea-e][A-Za-z0-9_-]{1,39}")


# Login for the researcher-only pages (dashboard, data API, downloads, participant files).
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin").strip()


DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()


# Extra researcher logins, e.g. DASHBOARD_USERS=ashley:pw1,candace:pw2,vicky:pw3
RESEARCHER_LOGINS = {DASHBOARD_USERNAME: DASHBOARD_PASSWORD} if DASHBOARD_PASSWORD else {}
for _pair in os.getenv("DASHBOARD_USERS", "").split(","):
    _name, _, _pw = _pair.strip().partition(":")
    if _name and _pw:
        RESEARCHER_LOGINS[_name] = _pw


# Issued participant IDs (created on /admin). Once at least one ID has been
# issued, only issued IDs can log in or store data.
ID_HEADERS = ["user_id", "group", "created_by", "created_at", "password_hash"]
# Participant passwords: short, lowercase, no look-alike characters (0/o, 1/l/i).
PARTICIPANT_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PARTICIPANT_PASSWORD_LENGTH = 6
RESEARCHER_USERNAME_RE = re.compile(r"[a-z0-9_.-]{2,32}")
MIN_RESEARCHER_PASSWORD = 8


# A full download must be this recent (and newer than the last saved row)
# before the data can be deleted from the server.
DELETE_AFTER_EXPORT_SECONDS = 30 * 60


# Answers that aren't a real attempt get no score/feedback; the participant is
# asked to fix them, and the attempt is logged with this marker in "feedback".
NONSENSE_FLAG = "[flagged: not a meaningful answer]"


NONSENSE_MESSAGE = ("This doesn't look like a real use for the object, so there is no feedback for it. "
                    "Please change it to a meaningful answer and click “Get Feedback” again.")


NONSENSE_WORDS = {"idk", "dont know", "don't know", "i dont know", "i don't know", "nothing", "none", "no idea",
                  "na", "n/a", "asdf", "qwerty", "test", "abc", "blah", "lol", "whatever", "something", "stuff"}


KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


# Second line of defence after the prompt rules: feedback containing any of
# these is regenerated once, then replaced by a fixed safe message.
UNSAFE_FEEDBACK_RE = re.compile(
    r"\b(weapons?|guns?|knife|knives|stab|stabs|stabbed|stabbing|kill\w*|murder\w*|bombs?|poison\w*|strangl\w*|"
    r"suffocat\w*|explosives?|assault\w*|suicid\w*|bludgeon\w*|arson)\b",
    re.IGNORECASE)


SAFE_FALLBACK_FEEDBACK = {
    "c": "Try imagining the object in a completely different setting, like a museum, a garden, or a game.",
    "d": "Thanks for sharing! Keep exploring safe, imaginative possibilities. 🌟",
    "e": "That is not acceptable here. Come up with a safe, genuinely original idea instead.",
}


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


# Groups whose drawing feedback also gets the original blank figure, so the
# LLM can tell which lines the participant added.
SEND_FIGURE_PREFIXES = {"c"}
