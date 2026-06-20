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


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=5))


def _post_cmd(body: dict) -> dict:
    return _post("/api/cmd", body)


def _get(path: str):
    return json.load(urllib.request.urlopen(f"{BASE}{path}", timeout=5))


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

    # 5) P2–P9 capabilities
    snap2 = store.snapshot()
    check("P2 groups in snapshot", len(snap2.get("groups", [])) >= 2,
          str([g["id"] for g in snap2.get("groups", [])]))
    check("P3 mastery_by_q in snapshot", len(snap2.get("mastery_by_q", [])) >= 1,
          str(snap2.get("mastery_by_q")))
    try:
        rep = await asyncio.to_thread(_get, "/api/report/activity?act=color-quiz")
        check("P8 report endpoint", bool(rep.get("by_question")), str(rep)[:80])
    except Exception as e:  # noqa
        check("P8 report endpoint", False, repr(e))
    try:
        acts = await asyncio.to_thread(_get, "/api/activities")
        check("P7 activities endpoint", len(acts) >= 2, str([a["id"] for a in acts]))
    except Exception as e:  # noqa
        check("P7 activities endpoint", False, repr(e))
    try:
        lg = await asyncio.to_thread(_post, "/api/login", {"user": "teacher", "password": "r4-demo"})
        check("P6 login issues token", bool(lg.get("token")), "")
    except Exception as e:  # noqa
        check("P6 login issues token", False, repr(e))
    try:
        gr = await asyncio.to_thread(
            _post_cmd, {"target": {"type": "group", "id": "A"}, "cmd": "freeze", "payload": {"freeze": True}})
        check("P2 group command routes", gr.get("ok") and gr.get("topics"), str(gr.get("topics")))
    except Exception as e:  # noqa
        check("P2 group command routes", False, repr(e))

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
