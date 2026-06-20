"""P9 — Multi-class device registry & enrollment (JSON-backed).

Maps each device (chip id) to a class/room, group, seat, and seat color. Lets one
backend serve multiple classes and gives zero-touch enrollment: an unknown device
that connects is auto-assigned the next free seat in a default class.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
STORE = DATA / "registry.json"

SEAT_COLORS = ["#f59e0b", "#3b82f6", "#10b981", "#ef4444", "#8b5cf6", "#ec4899"]
DEFAULT_CLASS = "sunflower"  # 햇님반


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"classes": {DEFAULT_CLASS: {"id": DEFAULT_CLASS, "title": "햇님반"}}, "devices": {}}


def _save(d: dict) -> None:
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def list_classes() -> list[dict]:
    return list(_load()["classes"].values())


def list_devices() -> dict:
    return _load()["devices"]


def enroll(device_id: str, class_id: str = DEFAULT_CLASS) -> dict:
    """Return the device's registry record, auto-assigning a seat if new."""
    d = _load()
    if device_id in d["devices"]:
        return d["devices"][device_id]
    used = {r["seat_no"] for r in d["devices"].values() if r.get("class_id") == class_id}
    seat = next(i for i in range(1, 1000) if i not in used)
    rec = {
        "device_id": device_id,
        "class_id": class_id,
        "group": "A" if seat % 2 else "B",
        "seat_no": seat,
        "seat_color": SEAT_COLORS[(seat - 1) % len(SEAT_COLORS)],
    }
    d["devices"][device_id] = rec
    d["classes"].setdefault(class_id, {"id": class_id, "title": class_id})
    _save(d)
    return rec
