"""Originality scores: OpenScoring API for text, local OCSAI-D model for drawings."""
import json

import requests

from .config import MODEL, OCSAI_MODEL_DIR, OPENSCORE_URL, TASK

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

    r = requests.post(OPENSCORE_URL, data=params, headers=headers, timeout=120)

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
