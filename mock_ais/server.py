"""Mock AIS WebSocket server.

Exposes the generated vessel positions as AISStream-style PositionReport
messages over a WebSocket, so the backend AIS consumer does not depend on
live data.

This server is ONLY an AIS data provider. The AOI only defines the
geographic region where the simulated vessels operate.

Currently NOT implemented: PostgreSQL and the real AISStream.io connection.
"""

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ais_messages import vessel_position_to_ais_message
from config import settings
from vessel_generator import generate_vessels

app = FastAPI(
    title="Mock AIS WebSocket Server",
    description="Standalone mock AIS data source for local development. "
    "Emulates the AISStream.io stream so the backend AIS consumer "
    "does not depend on live data.",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "mock-ais-server",
    }


async def _stream_random(cfg, websocket: WebSocket) -> None:
    vessels = generate_vessels(cfg)
    while True:
        for vessel in vessels:
            for position in vessel.positions:
                message = vessel_position_to_ais_message(vessel, position)
                await websocket.send_json(message.model_dump(mode="json"))
                await asyncio.sleep(cfg.update_interval)


async def _stream_scenario(cfg, websocket: WebSocket) -> None:
    vessels = generate_vessels(cfg)
    lengths = [len(v.positions) for v in vessels]
    tick = 0
    while True:
        for vessel, length in zip(vessels, lengths):
            position = vessel.positions[tick % length]
            message = vessel_position_to_ais_message(vessel, position)
            await websocket.send_json(message.model_dump(mode="json"))
        tick += 1
        await asyncio.sleep(cfg.update_interval)


async def _stream(cfg, websocket: WebSocket) -> None:
    if cfg.mode == "scenario":
        await _stream_scenario(cfg, websocket)
    else:
        await _stream_random(cfg, websocket)


@app.websocket("/ais")
async def ais_stream(websocket: WebSocket) -> None:
    """Stream PositionReport messages to a connected client."""
    await websocket.accept()

    try:
        await _stream(settings, websocket)
    except WebSocketDisconnect:
        # Client left; stop streaming for this connection.
        return
    except asyncio.CancelledError:
        # Connection closed while we were waiting on the interval.
        raise