"""In-process WebSocket broadcast hub for live vessel positions.

The AIS worker (``app.workers.ais_worker``) parses every upstream
``PositionReport``, persists it, and fans out the same wire-format message to
every connected dashboard client on the ``/ws/live`` WebSocket endpoint.

The hub is process-local: the worker and the FastAPI lifespan run in the same
asyncio event loop, so ``await live_hub.broadcast(...)`` delivers directly to
the connected browser sockets. The worker stays functional on its own: when no
broadcaster is provided it simply skips the emit step.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class LiveHub:
    """Tracks connected WebSocket clients and broadcasts JSON payloads."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        logger.info("live client connected (total=%d)", self.client_count)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        logger.info("live client disconnected (total=%d)", self.client_count)

    async def broadcast(self, payload: Any) -> None:
        """Send a JSON-serializable payload to every connected client."""
        if not self._clients:
            return
        text = payload if isinstance(payload, str) else json.dumps(payload)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(text)
            except Exception:
                logger.debug("dropping stale live client", exc_info=True)
                await self.disconnect(ws)


# Module-level singleton shared by the worker and the WebSocket route.
live_hub = LiveHub()