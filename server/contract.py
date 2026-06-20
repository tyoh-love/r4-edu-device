"""MQTT/WS contract — the single source of truth shared by backend, simulator,
and (mirrored in) the frontend. Topics & payloads follow docs/README.md §6.

Keep this module dependency-light: it is imported by the broker, backend, and
simulator alike.
"""
from __future__ import annotations

from enum import Enum

SITE = "site1"  # single-site demo


# --- Device-reported states (firmware/simulator sets these) ---
class DeviceState(str, Enum):
    idle = "idle"
    working = "working"
    done = "done"
    help = "help"  # child pressed the help button (explicit)


# --- Effective states shown on the grid (backend may DERIVE stuck / offline) ---
class EffectiveState(str, Enum):
    idle = "idle"
    working = "working"
    stuck = "stuck"      # DERIVED by backend (no progress past threshold)
    done = "done"
    help = "help"
    offline = "offline"  # DERIVED from LWT / silence


# Tile sort priority: attention-needing first.
STATE_PRIORITY = {
    EffectiveState.help: 0,
    EffectiveState.stuck: 1,
    EffectiveState.working: 2,
    EffectiveState.idle: 3,
    EffectiveState.done: 4,
    EffectiveState.offline: 5,
}

# Tile colors (kept in sync with frontend; hex from docs/README palette).
STATE_COLOR = {
    EffectiveState.idle: "#e2e8f0",
    EffectiveState.working: "#93c5fd",
    EffectiveState.stuck: "#fef3c7",
    EffectiveState.done: "#a7f3d0",
    EffectiveState.help: "#fee2e2",
    EffectiveState.offline: "#f1f5f9",
}

# stuck is derived when a `working` device reports no input for this long.
STUCK_THRESHOLD_MS = 30_000
# a device with no `state` message for this long is treated as offline.
OFFLINE_TIMEOUT_S = 12.0


# --- Topic builders ---
def t_state(device_id: str) -> str:
    return f"edu/{SITE}/{device_id}/state"


def t_meta(device_id: str) -> str:
    return f"edu/{SITE}/{device_id}/meta"


def t_answer(device_id: str) -> str:
    return f"edu/{SITE}/{device_id}/answer"


def t_status(device_id: str) -> str:
    """LWT topic — broker publishes 'offline' here on ungraceful disconnect."""
    return f"edu/{SITE}/{device_id}/status"


def t_cmd(device_id: str, cmd: str) -> str:
    return f"edu/{SITE}/{device_id}/cmd/{cmd}"


def t_group_cmd(group_id: str, cmd: str) -> str:
    return f"edu/{SITE}/group/{group_id}/cmd/{cmd}"


def t_group_mastery(group_id: str) -> str:
    return f"edu/{SITE}/group/{group_id}/mastery"


# Wildcards the backend subscribes to.
SUB_STATE = f"edu/{SITE}/+/state"
SUB_META = f"edu/{SITE}/+/meta"
SUB_ANSWER = f"edu/{SITE}/+/answer"
SUB_STATUS = f"edu/{SITE}/+/status"


def device_id_from_topic(topic: str) -> str | None:
    """edu/site1/<id>/<leaf> -> <id>."""
    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == "edu" and parts[1] == SITE:
        return parts[2]
    return None
