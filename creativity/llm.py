"""OpenAI calls: group feedback, the violence filter, and the nonsense-answer check."""
import logging
import os
import re

import requests

from .config import (KEYBOARD_ROWS, NONSENSE_WORDS, OPENAI_MODEL, OPENAI_REASONING_EFFORT, OPENAI_URL,
                     PROMPT_MAP, SAFE_FALLBACK_FEEDBACK, UNSAFE_FEEDBACK_RE)

logger = logging.getLogger(__name__)


def load_prompt(prefix):
    path = PROMPT_MAP.get(prefix)
    if not path:
        raise ValueError(f"No prompt configured for prefix: {prefix}")
    with open(path, "r") as f:
        return f.read().strip()


def get_openai_api_key():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY in the server environment")
    return api_key


def generate_llm_feedback(prefix, question, answer, image=None, figure=None):
    """image: optional data URL of a figural-task drawing; figure: optional data
    URL of the blank figure it was drawn on. The same group prompt is used for
    drawings, with a note that the answer is a drawing."""
    prompt_text = load_prompt(prefix)
    if image is None:
        full_prompt = (
            f"{prompt_text}\n\n"
            "Provide one short feedback message for the participant.\n\n"
            f"Question: {question}\n"
            f"Answer: {answer}\n"
            "Feedback:"
        )
        images = []
    elif figure is None:
        full_prompt = (
            f"{prompt_text}\n\n"
            "This participant is now doing a figural task instead: they were shown an "
            "abstract figure and drew on it to turn it into a picture. The attached image "
            "is their drawing. Give feedback on the drawing in the same style.\n"
            "Provide one short feedback message for the participant.\n\n"
            f"Task: {question}\n"
            "Feedback:"
        )
        images = [image]
    else:
        full_prompt = (
            f"{prompt_text}\n\n"
            "This participant is now doing a figural task instead: they were shown an "
            "abstract figure and drew on it to turn it into a picture. The first image is "
            "the original figure; the second image is their drawing on top of it. Base your "
            "feedback on what they actually added to the figure, in the same style.\n"
            "Provide one short feedback message for the participant.\n\n"
            f"Task: {question}\n"
            "Feedback:"
        )
        images = [figure, image]

    # Code-level safety net on top of the prompt rules.
    for _ in range(2):
        feedback = _openai_chat(full_prompt, images)
        if feedback_is_safe(feedback):
            return feedback
        logger.warning("Unsafe feedback blocked: %r", feedback)
    return SAFE_FALLBACK_FEEDBACK[prefix]


def _openai_chat(prompt, images=()):
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    body = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": content}]}
    if OPENAI_REASONING_EFFORT:
        body["reasoning_effort"] = OPENAI_REASONING_EFFORT
    r = requests.post(OPENAI_URL, json=body, timeout=60,
                      headers={"Authorization": f"Bearer {get_openai_api_key()}"})
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if not text:
        raise RuntimeError("Empty response from OpenAI")
    return text


def feedback_is_safe(text):
    """False if the feedback mentions violence/weapons (word list) or OpenAI's
    moderation model flags it. A moderation outage doesn't block feedback."""
    if UNSAFE_FEEDBACK_RE.search(text):
        return False
    try:
        r = requests.post("https://api.openai.com/v1/moderations", timeout=15,
                          json={"model": "omni-moderation-latest", "input": text},
                          headers={"Authorization": f"Bearer {get_openai_api_key()}"})
        if r.status_code == 200:
            return not r.json()["results"][0]["flagged"]
        logger.warning("Moderation check failed: %s", r.status_code)
    except Exception:
        logger.exception("Moderation check failed")
    return True


def looks_like_gibberish(answer):
    """Cheap checks that need no model: empty filler, no real words, key mashing."""
    text = answer.strip().lower()
    letters = re.sub(r"[^a-z]", "", text)
    if len(letters) < 2 or text.strip(" .!?") in NONSENSE_WORDS:
        return True
    if len(set(letters)) <= 2 and len(letters) >= 4:        # "aaaa", "hahaha"
        return True
    words = re.findall(r"[a-z]+", text)
    if all(len(w) >= 4 and any(w in row or w[::-1] in row for row in KEYBOARD_ROWS) for w in words):
        return True                                          # "asdfgh", "qwer"
    no_vowel = [w for w in words if len(w) >= 4 and not re.search(r"[aeiouy]", w)]
    return len(no_vowel) == len(words)                       # "sdfg hjkl"


def is_meaningful_answer(item, answer):
    """Is this a genuine attempt at a use for the object? Odd, silly or
    impractical ideas count as meaningful; gibberish and filler do not.
    If the model check fails, the answer is given the benefit of the doubt."""
    if looks_like_gibberish(answer):
        return False
    prompt = (
        "A participant in a creativity study was asked to list uses for an everyday object.\n"
        f"Object / task: {item}\n"
        f"Their answer: {answer}\n\n"
        "Is the answer a genuine attempt at a use for the object? Unusual, silly, impractical or very "
        "short ideas are genuine attempts. It is NOT genuine only if it is gibberish, random characters, "
        "empty filler (like \"idk\" or \"nothing\"), or has nothing to do with using the object.\n"
        "Reply with exactly one word: OK or NONSENSE."
    )
    try:
        return "NONSENSE" not in _openai_chat(prompt).upper()
    except Exception:
        logger.exception("Meaningful-answer check failed")
        return True
