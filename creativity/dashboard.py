"""Turns a participant's CSV rows into the blocks the dashboard shows."""
from .storage import _num_or_none


# Legacy fallback: older rows (before the "type" column existed) are told
# apart by their fixed question text instead.
LEGACY_MOOD_QUESTIONS = {
    "How pleasant did you feel during the task?": "mood_pleasant",
    "How alert or energized did you feel during the task?": "mood_alert",
}


def _row_type(row):
    t = (row.get("type") or "").strip()
    if t:
        return t
    return LEGACY_MOOD_QUESTIONS.get(row.get("question"), "answer")


def build_participant(user_id, group, rows):
    """Group one user's rows into blocks, in order:
    - kind "task": the answers/drawings for one question (new block whenever
      the question changes), with the time spent on it;
    - kind "checkin": a pair of mood ratings (before starting, after the
      first half, after all tasks).
    Older data had a check-in after every task, logged under that task's own
    question; those ratings are attached to the task block instead."""
    blocks = []
    task = None       # open task block
    checkin = None    # open check-in block (pleasant seen, waiting for alert)

    def new_block(kind, question):
        block = {"kind": kind, "question": question, "answers": [], "mood_pleasant": None,
                 "mood_alert": None, "duration_seconds": None}
        blocks.append(block)
        return block

    for row in rows:
        kind = _row_type(row)
        question = row.get("question")
        duration = _num_or_none(row.get("duration_seconds"))

        if kind in ("answer", "drawing", "drawing_unsubmitted"):
            if task is None or task["question"] != question:
                task = new_block("task", question)
            task["answers"].append({
                "time": row.get("time"),
                "type": kind,
                "answer": row.get("answer"),
                "score": _num_or_none(row.get("score")),
                "feedback": row.get("feedback") or None,
            })
            # duration_seconds = time on the task so far when the row was saved
            if duration is not None:
                task["duration_seconds"] = max(task["duration_seconds"] or 0, round(duration))
        elif kind in ("mood_pleasant", "mood_alert"):
            if task is not None and task["question"] == question:
                target = task                      # legacy per-task rating
                if duration is not None:
                    target["duration_seconds"] = round(duration)
            else:
                if checkin is None or checkin["question"] != question or checkin[kind] is not None:
                    checkin = new_block("checkin", question)
                target = checkin
            target[kind] = row.get("answer")
            if kind == "mood_alert":
                task = None

    all_times = [r.get("time") for r in rows if r.get("time")]
    return {
        "user_id": user_id,
        "group": group,
        "first_seen": min(all_times) if all_times else None,
        "last_seen": max(all_times) if all_times else None,
        "total_events": len(rows),
        "tasks": blocks,
    }
