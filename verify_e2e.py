"""End-to-end verification in ONE process (so localhost is reachable):
start broker + backend + simulator, then check the store, the WebSocket push,
a REST command round-trip, and capture a Playwright screenshot of the dashboard.

    uv run --with playwright python verify_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request

import uvicorn
import websockets

from server.app import app, store
from server.dev_broker import run_broker
from sim import simulate

SHOT = os.environ.get("SHOT", "/tmp/whos-stuck-live.png")
PORT = int(os.environ.get("PORT", "8077"))
BASE = f"http://127.0.0.1:{PORT}"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def _post_cmd(body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/cmd",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=5))


async def main() -> int:
    broker = await run_broker("127.0.0.1", 1883)
    await asyncio.sleep(0.4)
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    srv = asyncio.create_task(server.serve())
    sim = asyncio.create_task(simulate.run())
    await asyncio.sleep(7)  # let the simulator populate + a few ticks

    # 1) ingest pipeline (broker -> backend store)
    snap = store.snapshot()
    check("ingest: 15 devices", len(snap["devices"]) == 15, f"got {len(snap['devices'])}")
    check("derive: help present", snap["counts"]["help"] >= 1, str(snap["counts"]))
    check("derive: stuck present", snap["counts"]["stuck"] >= 1, str(snap["counts"]))
    check("derive: done present", snap["counts"]["done"] >= 1, str(snap["counts"]))
    check("mastery computed", snap["mastery"]["n"] >= 1, str(snap["mastery"]))

    # 2) WebSocket end-to-end (FastAPI WS server)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
        check("ws: snapshot received", msg.get("type") == "snapshot", str(msg["counts"]))
    except Exception as e:  # noqa
        check("ws: snapshot received", False, repr(e))

    # 3) Playwright screenshot of the served dashboard (capture while help is visible)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page(viewport={"width": 1400, "height": 820})
            await pg.goto(BASE, wait_until="networkidle")
            await asyncio.sleep(2.5)  # let WS deliver + render
            await pg.screenshot(path=SHOT, full_page=True)
            await b.close()
        check("screenshot captured", os.path.exists(SHOT), SHOT)
    except Exception as e:  # noqa
        check("screenshot captured", False, repr(e))

    # 4) REST command round-trip: send feedback to a help board -> sim clears help
    help_before = [d["id"] for d in store.snapshot()["devices"] if d["state"] == "help"]
    if help_before:
        target = help_before[0]
        try:
            r = await asyncio.to_thread(
                _post_cmd,
                {"target": {"type": "device", "id": target}, "cmd": "feedback",
                 "payload": {"led": "green", "blink": 2, "sound": "chime", "ms": 800}},
            )
            await asyncio.sleep(3)  # let sim react + republish state
            still = any(d["id"] == target and d["state"] == "help" for d in store.snapshot()["devices"])
            check("cmd round-trip (feedback clears help)", (r.get("ok") and not still),
                  f"target={target} topics={r.get('topics')} still_help={still}")
        except Exception as e:  # noqa
            check("cmd round-trip (feedback clears help)", False, repr(e))
    else:
        check("cmd round-trip (feedback clears help)", False, "no help device to target")

    srv.cancel(); sim.cancel()
    try:
        await broker.shutdown()
    except Exception:
        pass

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
