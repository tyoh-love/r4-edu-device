"""Pure-Python MQTT broker (amqtt) for zero-dependency local dev.

Production uses Mosquitto (see infra/docker-compose.yml); this lets the whole
e2e run with just `uv run python run_dev.py`, no Docker or system install.
"""
from __future__ import annotations

import asyncio
import logging

from amqtt.broker import Broker

log = logging.getLogger("r4.broker")


def _config(host: str, port: int) -> dict:
    # amqtt 0.11 typed-config schema: snake_case keys, ListenerType enum value.
    return {
        "listeners": {
            "default": {
                "type": "tcp",
                "bind": f"{host}:{port}",
                "max_connections": 500,
            }
        },
        "sys_interval": 0,
    }


async def run_broker(host: str = "0.0.0.0", port: int = 1883) -> Broker:
    broker = Broker(_config(host, port))
    await broker.start()
    log.info("dev broker listening on %s:%s", host, port)
    return broker
