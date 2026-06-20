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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import contract as C
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
    tasks = [asyncio.create_task(_mqtt_supervisor()), asyncio.create_task(_broadcast())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="R4 Swarm — Phase 1", lifespan=lifespan)


@app.get("/api/state")
async def api_state() -> dict:
    return store.snapshot()


class CmdTarget(BaseModel):
    type: str  # device | group | all
    id: str | None = None


class Cmd(BaseModel):
    target: CmdTarget
    cmd: str
    payload: dict = {}


@app.post("/api/cmd")
async def api_cmd(cmd: Cmd) -> dict:
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
