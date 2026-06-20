"""FastAPI backend: MQTT ingest -> derived store -> WebSocket push + REST commands.

Run via run_dev.py, or standalone against a broker:
    BROKER_HOST=localhost BROKER_PORT=1883 uv run uvicorn server.app:app
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path

import aiomqtt
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import contract as C
from . import content, persistence, registry, security
from .store import Store

log = logging.getLogger("r4.app")
BROKER_HOST = os.environ.get("BROKER_HOST", "localhost")
BROKER_PORT = int(os.environ.get("BROKER_PORT", "1883"))
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

store = Store()
clients: set[WebSocket] = set()
_mqtt: dict[str, aiomqtt.Client | None] = {"client": None}


async def _ingest(client: aiomqtt.Client) -> None:
    await client.subscribe(C.SUB_STATE)
    await client.subscribe(C.SUB_META)
    await client.subscribe(C.SUB_ANSWER)
    await client.subscribe(C.SUB_STATUS)
    async for m in client.messages:
        topic = m.topic.value
        dev = C.device_id_from_topic(topic)
        if not dev:
            continue
        leaf = topic.rsplit("/", 1)[-1]
        raw = m.payload.decode() if isinstance(m.payload, bytes) else str(m.payload)
        if leaf == "status":
            store.apply_status(dev, raw)
            continue
        try:
            p = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if leaf == "state":
            store.apply_state(dev, p)
        elif leaf == "meta":
            store.apply_meta(dev, p)
        elif leaf == "answer":
            store.apply_answer(dev, p)
            seat, grp = store.seat_group(dev)
            persistence.record_answer(
                dev, seat, grp, p.get("act") or "?", int(p.get("q") or 0),
                p.get("choice"), bool(p.get("correct")),
            )


async def _broadcast() -> None:
    while True:
        await store.wait_change(1.0)
        snap = json.dumps(store.snapshot())
        for ws in list(clients):
            try:
                await ws.send_text(snap)
            except Exception:
                clients.discard(ws)


async def _mqtt_supervisor() -> None:
    """Keep an MQTT connection up, with reconnect; run ingest while connected."""
    while True:
        try:
            async with aiomqtt.Client(BROKER_HOST, BROKER_PORT) as client:
                _mqtt["client"] = client
                log.info("MQTT connected %s:%s", BROKER_HOST, BROKER_PORT)
                await _ingest(client)
        except aiomqtt.MqttError as e:
            log.warning("MQTT error: %s — reconnect in 1s", e)
            _mqtt["client"] = None
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    persistence.init_db()
    tasks = [asyncio.create_task(_mqtt_supervisor()), asyncio.create_task(_broadcast())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="R4 Swarm — Phase 1", lifespan=lifespan)


def get_actor(authorization: str | None = Header(default=None)) -> str:
    """Resolve the teacher from a Bearer token. If AUTH_REQUIRED is off (dev),
    anonymous is allowed; if on, a valid token is mandatory."""
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    user = security.verify(token)
    if security.AUTH_REQUIRED and not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user or "anon"


@app.get("/api/state")
async def api_state() -> dict:
    return store.snapshot()


class Login(BaseModel):
    user: str
    password: str


@app.post("/api/login")
async def api_login(body: Login) -> dict:
    token = security.login(body.user, body.password)
    if not token:
        raise HTTPException(status_code=401, detail="invalid credentials")
    security.audit(body.user, "login", {})
    return {"ok": True, "token": token, "user": body.user}


class CmdTarget(BaseModel):
    type: str  # device | group | all
    id: str | None = None


class Cmd(BaseModel):
    target: CmdTarget
    cmd: str
    payload: dict = {}


@app.post("/api/cmd")
async def api_cmd(cmd: Cmd, actor: str = Depends(get_actor)) -> dict:
    security.audit(actor, "cmd", {"target": cmd.target.model_dump(), "cmd": cmd.cmd})
    client = _mqtt["client"]
    if client is None:
        return {"ok": False, "error": "mqtt not connected"}
    body = json.dumps(cmd.payload)
    topics: list[str] = []
    if cmd.target.type == "device" and cmd.target.id:
        topics = [C.t_cmd(cmd.target.id, cmd.cmd)]
    elif cmd.target.type == "group" and cmd.target.id:
        topics = [C.t_group_cmd(cmd.target.id, cmd.cmd)]
    elif cmd.target.type == "all":
        # fan out to every known device (Phase-1 simple broadcast)
        topics = [C.t_cmd(d["id"], cmd.cmd) for d in store.snapshot()["devices"]]
    for t in topics:
        await client.publish(t, body)
    return {"ok": True, "topics": topics}


# --- P8 reporting ---
@app.get("/api/report/activity")
async def api_report_activity(act: str) -> dict:
    return persistence.report_activity(act)


@app.get("/api/report/seats")
async def api_report_seats() -> list[dict]:
    return persistence.report_seats()


@app.get("/api/report/export.csv", response_class=PlainTextResponse)
async def api_report_export(actor: str = Depends(get_actor)) -> str:
    security.audit(actor, "export_csv", {})
    return persistence.export_csv()


# --- P7 content authoring ---
@app.get("/api/activities")
async def api_activities() -> list[dict]:
    return content.list_activities()


@app.post("/api/activities")
async def api_activities_upsert(activity: dict, actor: str = Depends(get_actor)) -> dict:
    security.audit(actor, "activity_upsert", {"id": activity.get("id")})
    return content.upsert_activity(activity)


# --- P9 registry ---
@app.get("/api/registry")
async def api_registry() -> dict:
    return {"classes": registry.list_classes(), "devices": registry.list_devices()}


# --- P6 roster (child<->seat), access-controlled, never in MQTT ---
@app.get("/api/roster")
async def api_roster(actor: str = Depends(get_actor)) -> dict:
    security.audit(actor, "roster_read", {})
    return security.get_roster()


class RosterEntry(BaseModel):
    seat_no: int
    child: str


@app.post("/api/roster")
async def api_roster_set(entry: RosterEntry, actor: str = Depends(get_actor)) -> dict:
    security.set_roster_entry(entry.seat_no, entry.child)
    security.audit(actor, "roster_set", {"seat_no": entry.seat_no})
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_text(json.dumps(store.snapshot()))
        while True:
            await ws.receive_text()  # ignore inbound; just detect disconnect
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


# Serve built frontend at / (if present). Mounted last so /api and /ws win.
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
