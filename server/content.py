"""P7 — Content authoring / activity library (JSON-backed).

An activity is a sequence of questions. For non-readers each question/choice can
carry an icon + audio cue (P4) instead of text. Teachers create activities; the
dashboard's "활동 푸시" sends an activity id to the boards.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
STORE = DATA / "activities.json"

# Seeded defaults (non-reader friendly: icon + audio, minimal text).
_SEED = {
    "color-quiz": {
        "id": "color-quiz", "title": "색깔 퀴즈",
        "questions": [
            {"q": 1, "prompt_audio": "어떤 색이 빨강일까요?", "icon": "🎨",
             "choices": [{"icon": "🔴", "correct": True}, {"icon": "🔵"}, {"icon": "🟢"}, {"icon": "🟡"}]},
            {"q": 2, "prompt_audio": "어떤 색이 파랑일까요?", "icon": "🎨",
             "choices": [{"icon": "🔴"}, {"icon": "🔵", "correct": True}, {"icon": "🟢"}, {"icon": "🟡"}]},
        ],
    },
    "shapes-quiz": {
        "id": "shapes-quiz", "title": "모양 퀴즈",
        "questions": [
            {"q": 1, "prompt_audio": "동그라미는 무엇일까요?", "icon": "🔷",
             "choices": [{"icon": "⭕", "correct": True}, {"icon": "⬛"}, {"icon": "🔺"}, {"icon": "⭐"}]},
        ],
    },
}


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text())
    STORE.write_text(json.dumps(_SEED, ensure_ascii=False, indent=2))
    return dict(_SEED)


def list_activities() -> list[dict]:
    return list(_load().values())


def get_activity(act_id: str) -> dict | None:
    return _load().get(act_id)


def upsert_activity(activity: dict) -> dict:
    data = _load()
    aid = activity["id"]
    data[aid] = activity
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return activity
