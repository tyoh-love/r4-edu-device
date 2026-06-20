"""In-memory device store with DERIVED stuck/offline states and mastery aggregation.

Single-threaded asyncio use. `bump()` signals the WS broadcaster that something
changed so it can push a fresh snapshot.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from .contract import (
    OFFLINE_TIMEOUT_S,
    STATE_COLOR,
    STATE_PRIORITY,
    STUCK_THRESHOLD_MS,
    DeviceState,
    EffectiveState,
)

_DIGITS = re.compile(r"(\d+)\D*$")


def _seat_from_id(device_id: str) -> int:
    m = _DIGITS.search(device_id)
    return int(m.group(1)) if m else 0


@dataclass
class Device:
    id: str
    seat_no: int
    group: str = "A"
    seat_color: str = "#94a3b8"
    raw_state: str = DeviceState.idle.value
    act: str | None = None
    q: int | None = None
    since: float = field(default_factory=time.time)
    idle_ms: int = 0
    last_update: float = field(default_factory=time.time)
    last_answer: dict | None = None
    rssi: int | None = None
    uptime_s: int | None = None
    help_since: float | None = None
    lwt_offline: bool = False

    # --- derived ---
    def online(self, now: float) -> bool:
        return (not self.lwt_offline) and (now - self.last_update) <= OFFLINE_TIMEOUT_S

    def current_idle_ms(self, now: float) -> int:
        """idle_ms reported at last_update, extrapolated to now."""
        return int(self.idle_ms + max(0.0, now - self.last_update) * 1000)

    def effective_state(self, now: float) -> EffectiveState:
        if not self.online(now):
            return EffectiveState.offline
        if self.raw_state == DeviceState.help.value:
            return EffectiveState.help
        if (
            self.raw_state == DeviceState.working.value
            and self.current_idle_ms(now) > STUCK_THRESHOLD_MS
        ):
            return EffectiveState.stuck
        return EffectiveState(self.raw_state)


class Store:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._changed = asyncio.Event()

    # ---- mutations (called from the MQTT ingest loop) ----
    def _ensure(self, device_id: str) -> Device:
        d = self._devices.get(device_id)
        if d is None:
            d = Device(id=device_id, seat_no=_seat_from_id(device_id))
            self._devices[device_id] = d
        return d

    def apply_state(self, device_id: str, p: dict) -> None:
        d = self._ensure(device_id)
        now = time.time()
        new_state = p.get("st", d.raw_state)
        if new_state != d.raw_state:
            d.since = p.get("since", now)
            if new_state == DeviceState.help.value:
                d.help_since = now
            else:
                d.help_since = None
        d.raw_state = new_state
        d.act = p.get("act", d.act)
        d.q = p.get("q", d.q)
        d.idle_ms = int(p.get("idle_ms", 0))
        d.last_update = now
        d.lwt_offline = False
        self.bump()

    def apply_meta(self, device_id: str, p: dict) -> None:
        d = self._ensure(device_id)
        if "group_id" in p:
            d.group = str(p["group_id"])
        if "seat_color" in p:
            d.seat_color = str(p["seat_color"])
        if "seat_no" in p:
            d.seat_no = int(p["seat_no"])
        self.bump()

    def apply_answer(self, device_id: str, p: dict) -> None:
        d = self._ensure(device_id)
        d.last_answer = {"choice": p.get("choice"), "correct": bool(p.get("correct"))}
        if "act" in p:
            d.act = p["act"]
        if "q" in p:
            d.q = p["q"]
        d.last_update = time.time()
        self.bump()

    def apply_status(self, device_id: str, raw: str) -> None:
        """LWT/status topic: 'offline' marks the device down."""
        d = self._ensure(device_id)
        d.lwt_offline = raw.strip().strip('"') == "offline"
        self.bump()

    # ---- change signalling ----
    def bump(self) -> None:
        self._changed.set()

    async def wait_change(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            self._changed.clear()

    # ---- read ----
    def snapshot(self) -> dict:
        now = time.time()
        devs = sorted(self._devices.values(), key=lambda d: d.seat_no)
        out_devices = []
        counts = {s.value: 0 for s in EffectiveState}
        # mastery over devices that have answered the current activity
        acts = [d.act for d in devs if d.act]
        activity = max(set(acts), key=acts.count) if acts else None
        qs = [d.q for d in devs if d.q is not None]
        cur_q = max(qs) if qs else None
        n_answered = 0
        correct = 0
        for d in devs:
            eff = d.effective_state(now)
            counts[eff.value] += 1
            ans = d.last_answer
            if ans is not None and d.act == activity:
                n_answered += 1
                if ans.get("correct"):
                    correct += 1
            out_devices.append(
                {
                    "id": d.id,
                    "seat_no": d.seat_no,
                    "group": d.group,
                    "seat_color": d.seat_color,
                    "state": eff.value,
                    "raw_state": d.raw_state,
                    "color": STATE_COLOR[eff],
                    "act": d.act,
                    "q": d.q,
                    "last_answer": d.last_answer,
                    "rssi": d.rssi,
                    "uptime_s": d.uptime_s,
                    "since": d.since,
                    "stuck_for_s": (
                        round((d.current_idle_ms(now) - STUCK_THRESHOLD_MS) / 1000)
                        if eff == EffectiveState.stuck
                        else 0
                    ),
                    "help_for_s": (
                        round(now - d.help_since)
                        if eff == EffectiveState.help and d.help_since
                        else 0
                    ),
                    "online": d.online(now),
                }
            )
        # attention-first ordering for convenience (frontend may re-sort)
        out_devices.sort(key=lambda x: (STATE_PRIORITY[EffectiveState(x["state"])], x["seat_no"]))
        rate = round(correct / n_answered, 3) if n_answered else 0.0
        return {
            "type": "snapshot",
            "ts": now,
            "session": {"sid": "s1", "activity": activity, "q": cur_q},
            "counts": counts,
            "mastery": {"n": n_answered, "correct": correct, "rate": rate},
            "devices": out_devices,
        }
