"""P6 — Security / PIPA helpers.

- Teacher token auth (opt-in via AUTH_REQUIRED=1 so the dev demo keeps working).
- Append-only audit log of privileged actions (PIPA 접속기록).
- Child<->seat roster kept OUT of MQTT, in an access-controlled local store
  (PIPA: device topics carry only seat_no/values, never child names).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
AUDIT = DATA / "audit.log"
ROSTER = DATA / "roster.json"  # seat_no -> child (access-controlled; gitignored)

AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED") == "1"
# demo accounts: "teacher:password"; override via TEACHERS env (comma-separated).
_TEACHERS = dict(
    pair.split(":", 1)
    for pair in os.environ.get("TEACHERS", "teacher:r4-demo").split(",")
    if ":" in pair
)
_SECRET = os.environ.get("AUTH_SECRET", "dev-secret-change-me").encode()


def _sign(user: str) -> str:
    mac = hmac.new(_SECRET, user.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{user}.{mac}"


def login(user: str, password: str) -> str | None:
    if _TEACHERS.get(user) == password:
        return _sign(user)
    return None


def verify(token: str | None) -> str | None:
    """Return the username if the token is valid, else None."""
    if not token:
        return None
    user, _, mac = token.partition(".")
    if user and hmac.compare_digest(_sign(user), token):
        return user
    return None


def audit(actor: str, action: str, detail: dict) -> None:
    rec = {"ts": time.time(), "actor": actor, "action": action, "detail": detail}
    with AUDIT.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- roster (child <-> seat), access-controlled, never published to MQTT ---
def get_roster() -> dict:
    if ROSTER.exists():
        return json.loads(ROSTER.read_text())
    return {}


def set_roster_entry(seat_no: int, child: str) -> None:
    r = get_roster()
    r[str(seat_no)] = child
    ROSTER.write_text(json.dumps(r, ensure_ascii=False, indent=2))
