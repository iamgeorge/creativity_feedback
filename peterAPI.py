import requests

BASE_URL = "https://openscoring.du.edu"


def score_answers(item: str, answers: list[str], *, model: str = "ocsai1-4o", api_key: str | None = None):
    """
    Scores answers for an item (e.g., AUT "uses" task).
    Sends CSV rows: item,response
    Returns JSON from /llm.
    """
    # Build CSV text: each row is prompt,response
    # Quotes protect commas inside responses.
    input_csv = "\n".join(
        [f'"{item}","{a.replace(chr(34), chr(34)*2)}"' for a in answers])

    headers = {"Accept": "application/json"}
    if api_key:
        # optional :contentReference[oaicite:1]{index=1}
        headers["X-API-KEY"] = api_key

    params = {
        # most advanced: ocsai1-4o :contentReference[oaicite:2]{index=2}
        "model": model,
        # default task is "uses" for AUT-style prompts :contentReference[oaicite:3]{index=3}
        "task": "uses",
        "input": input_csv,  # send all rows in one string separated by \n
    }

    r = requests.post(f"{BASE_URL}/llm", params=params,
                      headers=headers, timeout=120)

    # Helpful error if something goes wrong
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}\n{r.text[:500]}")

    # If server ever returns non-JSON, this makes it obvious
    try:
        return r.json()
    except Exception:
        raise RuntimeError(
            f"Expected JSON but got:\nContent-Type: {r.headers.get('Content-Type')}\n{r.text[:500]}")


if __name__ == "__main__":
    item = "hammer"
    answers = [
        "crack open a coconut",
        "use it as a paperweight",
        "tap-test pottery for cracks",
    ]

    result = score_answers(item, answers, model="ocsai1-4o")
    print(result)

    # Often the JSON includes something like result['scores']['originality'] (depends on API response format)
    # So you can try:
    # print(result["scores"]["originality"])
