"""One-command e2e: in-process MQTT broker + FastAPI backend + device simulator.

    uv run python run_dev.py

Then open http://localhost:8000  (serves the built frontend if frontend/dist exists;
otherwise use the Vite dev server: cd frontend && npm run dev).
"""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from server.app import app
from server.dev_broker import run_broker
from sim import simulate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# amqtt is very chatty; quiet it down.
for noisy in ("amqtt", "transitions", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def main() -> None:
    port = int(os.environ.get("PORT", "8077"))
    broker = await run_broker("0.0.0.0", 1883)
    await asyncio.sleep(0.5)  # let the broker bind before clients connect

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)

    tasks = [
        asyncio.create_task(server.serve(), name="uvicorn"),
        asyncio.create_task(simulate.run(), name="simulator"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        try:
            await broker.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
