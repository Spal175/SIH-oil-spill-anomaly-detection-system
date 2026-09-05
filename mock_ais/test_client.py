"""WebSocket test client for the mock AIS server.

Connects to ws://localhost:8001/ais and prints every PositionReport received.
Pass --debug to print the complete JSON message alongside the summary line.

Usage:
    python test_client.py                          # stream until Ctrl+C
    python test_client.py --debug                  # also print full JSON
    python test_client.py --messages 20            # stop after 20 messages
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone

import websockets

URI = "ws://localhost:8001/ais"


def _print_report(message: dict, debug: bool) -> None:
    meta = message["MetaData"]
    report = message["Message"]["PositionReport"]
    timestamp = datetime.fromtimestamp(report["Timestamp"], tz=timezone.utc)

    print(
        f"MMSI={report['UserID']}  ship={meta['ShipName']!r:<20}  "
        f"lat={report['Latitude']:>9.5f}  lon={report['Longitude']:>10.5f}\n"
        f"    speed={report['Sog']:>5.1f} kn  course={report['Cog']:>6.1f} deg  "
        f"heading={report['TrueHeading']:>3} deg  "
        f"ts={report['Timestamp']} ({timestamp:%Y-%m-%d %H:%M:%S}Z)"
    )
    if debug:
        print(json.dumps(message, indent=2))


async def receive(uri: str, debug: bool, limit: int | None) -> None:
    """Connect and stream PositionReports until interrupted or `limit` seen."""
    count = 0
    print(f"Connecting to {uri} ...")
    async with websockets.connect(uri) as ws:
        print(f"Connected. Streaming PositionReports (Ctrl+C to stop).\n")
        try:
            async for raw in ws:
                message = json.loads(raw)
                _print_report(message, debug=debug)
                count += 1
                if limit is not None and count >= limit:
                    print(f"\nStopped after {count} message(s).")
                    break
        except websockets.ConnectionClosed:
            print("\nConnection closed by server.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print PositionReports streamed by the mock AIS server.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print the complete JSON message below the summary line",
    )
    parser.add_argument(
        "--messages",
        type=int,
        default=None,
        help="stop after N messages (default: stream until Ctrl+C)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(receive(URI, debug=args.debug, limit=args.messages))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()