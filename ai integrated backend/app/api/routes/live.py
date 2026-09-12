"""Live vessel-position WebSocket endpoint.

Dashboards connect here to receive real-time ship positions. Messages are the
same AISStream.io-style ``PositionReport`` envelopes the upstream feed emits;
they are parsed and persisted by the AIS worker, then broadcast through
``app.services.live.live_hub``.

    ws://localhost:8000/ws/live
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.live import live_hub

router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def live_positions(websocket: WebSocket) -> None:
    """Stream live vessel positions to a connected dashboard."""
    await live_hub.connect(websocket)
    try:
        # Keep the connection open; the hub pushes messages on its own.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await live_hub.disconnect(websocket)
    except Exception:
        await live_hub.disconnect(websocket)
        raise