"""Device simulator — stands in for N Arduino R4 boards (no hardware needed).

Publishes retained `meta` + `state` (+ `answer`) per the contract, evolves each
board through realistic transitions, and reacts to teacher commands so the
command round-trip is visible end-to-end.

Run standalone:  BROKER_HOST=localhost uv run python -m sim.simulate
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time

import aiomqtt

from server import contract as C

BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "1883"))
N = int(os.environ.get("SIM_N", "15"))
ACTIVITY = "color-quiz"
SEAT_COLORS = ["#f59e0b", "#3b82f6", "#10b981", "#ef4444", "#8b5cf6", "#ec4899"]


class Board:
    def __init__(self, idx: int):
        self.idx = idx
        self.id = f"r4-{idx:04d}"
        self.group = "A" if idx <= N // 2 else "B"
        self.color = SEAT_COLORS[idx % len(SEAT_COLORS)]
        self.raw = "working"
        self.act = ACTIVITY
        self.q = 1
        self.since = time.time()
        self.last_input = time.time()
        self.paused = False
        self.stalled = False
        self.seq = 0
        self.fb_until = 0.0      # transient teacher-feedback marker (P4)
        self.fb_kind: str | None = None
        # Seed a varied initial snapshot so the grid is interesting immediately.
        if idx == 7:
            self.raw = "help"  # child raised hand
        elif idx in (4, 13):
            # persistently stalled: never makes input -> idle_ms climbs past the
            # 30s threshold -> backend DERIVES 'stuck'.
            self.stalled = True
            self.last_input = time.time() - 42
        elif idx in (3, 10):
            self.raw, self.q = "done", 5
        elif idx == 11:
            self.raw = "idle"

    def state_payload(self) -> dict:
        now = time.time()
        idle_ms = int(max(0.0, now - self.last_input) * 1000)
        self.seq += 1
        return {
            "st": self.raw,
            "act": self.act,
            "q": self.q,
            "since": self.since,
            "idle_ms": idle_ms,
            "seq": self.seq,
            "fb": self.fb_kind if now < self.fb_until else None,
        }

    def set_state(self, raw: str) -> None:
        if raw != self.raw:
            self.since = time.time()
        self.raw = raw

    def step(self) -> dict | None:
        """Advance the board one tick; return an answer payload if one was made."""
        if self.paused or self.raw in ("done", "help"):
            return None
        if self.stalled:
            # occasionally a long-stalled child escalates to pressing help
            if (time.time() - self.last_input) > 60 and random.random() < 0.15:
                self.set_state("help")
            return None  # no input -> stays 'working' with climbing idle_ms -> 'stuck'
        r = random.random()
        if self.raw == "idle":
            if r < 0.4:
                self.set_state("working")
                self.last_input = time.time()
            return None
        # working
        if r < 0.45:  # made an input / answered a question
            self.last_input = time.time()
            correct = random.random() < 0.72
            ans = {"choice": random.randint(1, 4), "correct": correct, "act": self.act, "q": self.q}
            self.q += 1
            if self.q > 5:
                self.set_state("done")
            return ans
        elif r < 0.52:  # stall (stops inputting -> idle_ms climbs -> 'stuck')
            pass
        elif r < 0.56 and (time.time() - self.last_input) > 25:
            self.set_state("help")  # stuck long enough -> child asks for help
        return None


def _apply_cmd(b: Board, cmd: str, payload: dict) -> None:
    """Apply one command to one board (device-, group-, or all-targeted)."""
    if cmd == "freeze":
        b.paused = True
    elif cmd == "resume":
        b.paused = False
        b.last_input = time.time()
    elif cmd == "push_activity":
        b.act = payload.get("act", "activity-2")
        b.q = 1
        b.paused = False
        b.stalled = False
        b.last_input = time.time()
        b.set_state("working")
    elif cmd == "pace":
        # pacing hint (segment/timer) — accepted; affects nothing visible yet
        pass
    elif cmd in ("feedback", "hint"):
        # child-facing nudge (LED/sound on real HW); mark transient for the grid
        b.fb_until = time.time() + 3.0
        b.fb_kind = cmd
        # teacher acknowledged a raised hand: clear help / nudge back to working
        if b.raw == "help":
            b.set_state("working")
            b.last_input = time.time()


async def _command_listener(client: aiomqtt.Client, boards: dict[str, Board]) -> None:
    await client.subscribe(f"edu/{C.SITE}/+/cmd/#")            # device commands
    await client.subscribe(f"edu/{C.SITE}/group/+/cmd/#")      # group commands
    async for m in client.messages:
        parts = m.topic.value.split("/")
        try:
            payload = json.loads(m.payload.decode()) if m.payload else {}
        except (ValueError, TypeError):
            payload = {}
        targets: list[Board] = []
        if len(parts) >= 6 and parts[2] == "group":
            gid, cmd = parts[3], parts[5]
            targets = [b for b in boards.values() if b.group == gid]
        elif len(parts) >= 5:
            dev_id, cmd = parts[2], parts[4]
            b = boards.get(dev_id)
            targets = [b] if b else []
        else:
            continue
        for b in targets:
            _apply_cmd(b, cmd, payload)
            # re-publish state so the dashboard reflects the reaction immediately
            await client.publish(C.t_state(b.id), json.dumps(b.state_payload()), retain=True)


async def run() -> None:
    boards = {f"r4-{i:04d}": Board(i) for i in range(1, N + 1)}
    async with aiomqtt.Client(BROKER_HOST, BROKER_PORT) as client:
        # retained meta + initial state
        for b in boards.values():
            await client.publish(
                C.t_meta(b.id),
                json.dumps({"group_id": b.group, "seat_color": b.color, "seat_no": b.idx}),
                retain=True,
            )
            await client.publish(C.t_state(b.id), json.dumps(b.state_payload()), retain=True)

        asyncio.create_task(_command_listener(client, boards))

        while True:
            for b in boards.values():
                ans = b.step()
                if ans is not None:
                    await client.publish(C.t_answer(b.id), json.dumps(ans))
                await client.publish(C.t_state(b.id), json.dumps(b.state_payload()), retain=True)
            await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(run())
