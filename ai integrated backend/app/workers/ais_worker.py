"""AIS WebSocket worker.

Consumes AISStream.io-style ``PositionReport`` messages from a WebSocket feed
(default ``ws://localhost:8001/ais``, the mock AIS server) and persists them::

    WebSocket -> parse -> vessels (upsert) + ais_positions (insert)

Only AIS data is handled here: no oil-spill lookups, no attribution, no
satellite imagery. Run independently during development with::

    python -m app.workers.ais_worker

The worker reconnects automatically with exponential backoff and logs every
connection / disconnection / error. It is NOT wired into FastAPI startup yet.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import websockets

from app.config import settings
from app.database.connection import get_session_factory
from app.database.repositories import VesselRepository
from app.workers.ais_message import ParsedPosition, parse_position_report

logger = logging.getLogger(__name__)

RECONNECT_BASE = 1.0
RECONNECT_MAX = 30.0


class AISWorker:
    """Long-running consumer that streams AIS positions into Postgres."""

    def __init__(
        self,
        ws_url: Optional[str] = None,
        reconnect_base: float = RECONNECT_BASE,
        reconnect_max: float = RECONNECT_MAX,
    ):
        self.ws_url = ws_url or settings.ais_ws_url
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self._session_factory = get_session_factory()
        self._stop = asyncio.Event()
        self._backoff = reconnect_base
        self.position_count = 0
        self.vessel_count = 0
        self.connected = False

    async def stop(self) -> None:
        """Ask the worker to stop after the current connection ends."""
        self._stop.set()
        logger.info("stop requested")

    @property
    def running(self) -> bool:
        return not self._stop.is_set()

    async def _persist(self, parsed: ParsedPosition) -> None:
        """Upsert the vessel, then insert one position report."""
        timestamp = parsed.timestamp_utc
        with self._session_factory() as session:
            repo = VesselRepository(session)
            repo.upsert_vessel(
                parsed.mmsi,
                ship_name=parsed.ship_name,
                ship_type=parsed.ship_type,
            )
            repo.add_position(
                mmsi=parsed.mmsi,
                timestamp=timestamp,
                latitude=parsed.latitude,
                longitude=parsed.longitude,
                speed=parsed.speed,
                course=parsed.course,
                heading=parsed.heading,
            )
            session.commit()

    async def _consume(self, ws) -> None:
        """Read messages until the connection closes."""
        async for raw in ws:
            if self._stop.is_set():
                break
            parsed = parse_position_report(raw)
            if parsed is None:
                logger.debug("skipping non-PositionReport / unparseable message: %.80r", raw)
                continue
            try:
                await self._persist(parsed)
            except Exception:
                logger.exception("failed to persist message for mmsi=%s", parsed.mmsi)
                continue
            self.position_count += 1
            logger.info(
                "persisted mmsi=%d name=%s lat=%.5f lon=%.5f sog=%s cog=%s heading=%s @ %s "
                "(positions=%d)",
                parsed.mmsi,
                parsed.ship_name,
                parsed.latitude,
                parsed.longitude,
                parsed.speed,
                parsed.course,
                parsed.heading,
                parsed.timestamp_utc.isoformat(),
                self.position_count,
            )

    async def _wait(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass

    async def run_forever(self) -> None:
        """Connect, stream, and reconnect on failure until stopped."""
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.ws_url, ping_interval=20, open_timeout=10
                ) as ws:
                    self.connected = True
                    self._backoff = self.reconnect_base
                    logger.info("connected to %s", self.ws_url)
                    await self._consume(ws)
                    logger.warning("disconnected from %s", self.ws_url)
                    self.connected = False
            except asyncio.CancelledError:
                logger.info("worker cancelled")
                self.connected = False
                raise
            except Exception as exc:
                self.connected = False
                logger.error(
                    "connection error on %s: %s; reconnecting in %.1fs",
                    self.ws_url,
                    exc,
                    self._backoff,
                )

            if self._stop.is_set():
                break
            await self._wait(self._backoff)
            if not self._stop.is_set():
                self._backoff = min(self._backoff * 2, self.reconnect_max)

        logger.info("worker stopped")


async def run() -> None:
    worker = AISWorker()
    await worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass