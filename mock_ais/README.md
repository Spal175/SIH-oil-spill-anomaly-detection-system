# Mock AIS WebSocket Server

Standalone mock AIS data source for local development. It is a separate
service that behaves like an AISStream.io WebSocket feed so the backend AIS
consumer does not depend on live data.

The mock server is ONLY an AIS data provider. Its only geographic knowledge
is an Area of Interest (AOI) in which it spawns simulated vessels. It
produces:

    vessels → positions → AIS messages → WebSocket

## Structure

```
mock_ais/
├── server.py           FastAPI app (GET / health check, /ais WebSocket)
├── config.py           Loads environment / .env configuration
├── models.py           Vessel, VesselPosition, VesselTrajectory, AISMessage
├── ais_messages.py     Converts positions into AISStream-style messages
├── vessel_generator.py Trajectory-based vessel generation
├── scenarios/          Deterministic JSON scenarios (replayed in scenario mode)
│   └── demo_01.json    ~10 vessels with predetermined trajectories
├── vessels.json        Static seed vessels (mmsi, ship_name, ship_type)
├── test_client.py      WebSocket test client (ws://localhost:8001/ais)
├── requirements.txt    Python dependencies
├── .env.example        Example environment configuration
└── README.md           This file
```

## Setup

```bash
cd mock_ais
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # optional: config is loaded from .env
```

## Run the server

Open two terminals. In **Terminal 1** start the mock AIS server:

```bash
cd mock_ais
uvicorn server:app --host 0.0.0.0 --port 8001
```

In **Terminal 2** run the WebSocket test client:

```bash
cd mock_ais
python test_client.py
```

The client prints one summary line per PositionReport (MMSI, ship name,
latitude, longitude, speed, course, heading, timestamp). Add `--debug` to
also print the complete JSON message, and `--messages N` to stop after N
messages instead of streaming until Ctrl+C.

Check the health endpoint:

```bash
curl http://localhost:8001/
# {"status":"running","service":"mock-ais-server"}
```

Connect to the AIS stream:

```bash
ws ws://localhost:8001/ais
```

## Configuration (.env)

| Variable                       | Default | Description                                     |
| ------------------------------ | ------- | ----------------------------------------------- |
| `MOCK_HOST`                    | 0.0.0.0 | Bind host                                       |
| `MOCK_PORT`                    | 8001    | Bind port                                       |
| `MOCK_MODE`                    | scenario | scenario, inside or mixed                        |
| `MOCK_SCENARIO`                | demo_01 | Scenario name (only used when MOCK_MODE=scenario) |
| `MOCK_AOI_NORTH`               | 39.64   | AOI top latitude (positive = north)             |
| `MOCK_AOI_SOUTH`               | 37.73   | AOI bottom latitude                             |
| `MOCK_AOI_EAST`                | -8.13   | AOI right longitude (negative = west)           |
| `MOCK_AOI_WEST`                | -11.45  | AOI left longitude (negative = west)            |
| `MOCK_VESSEL_COUNT`            | 10      | Number of vessels to generate                  |
| `MOCK_UPDATE_INTERVAL`         | 2       | Seconds between position updates                |
| `MOCK_TRAJECTORY_POINTS`       | 25      | Number of positions per vessel trajectory       |
| `MOCK_TRAJECTORY_STEP_SECONDS` | 120     | Seconds between consecutive trajectory points   |
| `MOCK_COURSE_WANDER_DEG`       | 3       | Std-dev of the per-step heading noise (degrees) |
| `MOCK_TRAJECTORY_KINDS`        | straight,diagonal,slow,turn | Comma-separated trajectory kinds to cycle through |
| `MOCK_INITIAL_HEADING`         | unset   | Fixed initial course (auto per vessel if unset) |

> Remember western longitudes are negative: `8.13° W` is `-8.13`, not `+8.13`.
>
> `MOCK_TRAJECTORY_KINDS` is a comma-separated list; vessels alternate through
> the kinds in order, so with 10 vessels you get a mix of straight, diagonal,
> slow and turning traffic.

## Current status

Implemented:

- `GET /` health check.
- `config.py` loads all environment variables (with sensible defaults).
- `models.py` defines `Vessel`, `VesselPosition`, `VesselTrajectory`,
  `AISMessage` (with `MetaData` / `Message.PositionReport`).
- `ais_messages.py`: `vessel_position_to_ais_message()` converts a generated
  trajectory position into an AISStream-style `AISMessage`.
- `vessel_generator.py`:
  - geographic utilities: `haversine_km`, `is_inside_aoi`,
    `random_point_in_aoi`, `destination_point`
  - `generate_vessels()` returning vessels, each carrying an ordered
    `VesselTrajectory` of position reports (see modes below).
  - validation that trajectories are geographically sensible: coordinates in
    range, strictly increasing timestamps, no unrealistically large jumps,
    unique MMSIs, and (mostly) inside the configured AOI.
- WebSocket streaming over `/ais`: accepts a client, generates the fake
  vessels, converts every trajectory position into an `AISMessage`, sends it
  as JSON and loops forever. In `scenario` mode all vessels are advanced
  together every `MOCK_UPDATE_INTERVAL` seconds (a multi-vessel "tick"); in
  `inside`/`mixed` mode positions are streamed point-by-point. Client
  disconnections are handled gracefully.

Not implemented yet (next stage):

- PostgreSQL persistence and the production AISStream.io connection.

## Testing the generator

Run the unit tests:

```bash
python -m unittest -v test_vessel_generator
python -m unittest -v test_ais_messages
python -m unittest -v test_trajectory_kinds
```

Print vessels for the currently configured settings:

```bash
python vessel_generator.py          # uses MOCK_MODE / MOCK_SCENARIO / MOCK_VESSEL_COUNT from .env
```

## Generation modes

| Mode       | Behaviour                                                          |
| ---------- | ------------------------------------------------------------------ |
| `scenario` | deterministic: loads `scenarios/<MOCK_SCENARIO>.json` and replays its predetermined vessel trajectories in a loop |
| `mixed`    | random vessels operate inside the AOI with a mix of trajectory kinds |
| `inside`   | same as `mixed` (alias)                                             |

### Deterministic scenarios (`MOCK_MODE=scenario`)

With `MOCK_MODE=scenario` the server ignores the random generator and replays
the vessels stored in `scenarios/<MOCK_SCENARIO>.json` (default
`scenarios/demo_01.json`). The demo scenario ships ~10 vessels (a product
tanker, cargo, tugs, a ferry, a freighter, a fishing vessel, a coaster and a
high-speed craft) inside the AOI, each with a `mmsi`, `ship_name`,
`ship_type`, an optional `speed_kn`, and a fixed `trajectory` (an ordered
list of `[latitude, longitude]` positions). Every `MOCK_UPDATE_INTERVAL`
seconds the server advances every vessel to its next point, broadcasts one
`PositionReport` per vessel, and loops the trajectories indefinitely.

The scenario only describes normal maritime traffic. Nothing in the mock
server associates any vessel or location with pollution, satellite imagery or
any downstream detection — those steps live in the backend application, not
in this data provider.

A simple way to make the situation reproducible: reserve a segment of one
vessel's route so the backend can use it as a known crossing location. In
`demo_01.json`, `DEMO TANKER A` passes within ~0.8 km of `(38.50, -9.50)`
(the point encoded in the demo GeoTIFF `demo_01_oil_spill.tif`), reaching its
closest approach at exactly `09:58:00Z` — 12 minutes before the TIFF's
embedded acquisition/detection time `2026-09-05T10:10:00Z`. Those reproducible
timestamps come from the scenario's top-level `start_time` field.

Scenarios may declare a fixed `start_time` (ISO-8601 UTC) at the top level of
the JSON file. When present, every vessel's position timestamps are anchored
to that instant (instead of the wall-clock "now"), so the whole scenario is
deterministic and can be aligned with a downstream oil-spill detection time.
Scenarios without `start_time` keep the previous behaviour (timestamps start
at the current UTC time).

With `MOCK_UPDATE_INTERVAL=2` the tanker re-crosses its route about every half
minute and every vessel fully restarts its loop within about a minute, so the
whole scenario repeats from the start continuously.

### Trajectory kinds

Every vessel is assigned one trajectory kind in rotation (see
`MOCK_TRAJECTORY_KINDS`), giving several independent vessels with different
starts, headings, speeds and path shapes:

| Kind       | Behaviour                                                        |
| ---------- | ---------------------------------------------------------------- |
| `straight` | steady course across the AOI with almost no heading wander       |
| `diagonal` | corner-to-corner crossing on a diagonal bearing                  |
| `slow`     | low speed (fishing/tug/other) on an easy, fairly straight course |
| `turn`     | heading changes gradually (bounded arc) roughly toward the AOI centre, kept mostly inside |