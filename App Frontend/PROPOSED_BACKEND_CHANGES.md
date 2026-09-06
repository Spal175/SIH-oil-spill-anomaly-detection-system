# Backend additions needed for mobile push alerts

Reviewed the actual repo (`ai integrated backend/`). The detection pipeline
(`POST /oil-spills/analyze` → ML → GIS → DB) already works and already
persists everything the mobile app needs. Two things are missing for mobile
alerts to work, both small and additive — nothing in the existing pipeline
needs to change.

## 1. `GET /oil-spills` — list endpoint (for history backfill)

Right now the only read routes are `GET /oil-spills/{id}` (needs an exact id)
and `GET /oil-spills/{id}/vessels`. There's no way to ask "what spills
happened recently" — needed so the mobile app can show history from before
it was installed / the phone was off.

**`app/database/repositories.py`** — add to `OilSpillRepository`:
```python
def list_recent(self, since: Optional[datetime] = None, limit: int = 50) -> list[OilSpill]:
    stmt = select(OilSpill).order_by(OilSpill.detected_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(OilSpill.detected_at >= since)
    return list(self._session.execute(stmt).scalars())
```

**`app/services/oil_spill_analysis.py`** — add alongside `get_spill_detail`:
```python
def list_recent_spills(since: Optional[datetime] = None, limit: int = 50) -> list[dict]:
    with session_scope() as session:
        spills = OilSpillRepository(session).list_recent(since=since, limit=limit)
        return [
            {
                "id": s.id,
                "latitude": s.centroid_latitude,
                "longitude": s.centroid_longitude,
                "detected_at": s.detected_at,
                "confidence": s.confidence,
                "area": s.area,
                "region_count": None,  # region_count isn't persisted today — see note below
            }
            for s in spills
        ]
```
> Note: `region_count` currently only exists transiently in the GIS `geo`
> dict inside `analyze_tiff()` — it's never saved to the `OilSpill` row. If
> you want it in the list/mobile view, add a `region_count` column to the
> `OilSpill` model + a migration, and pass `geo.get("region_count")` into
> `repo.create(...)`. Not required for a working demo — just leave it `null`.

**`app/api/routes/oil_spills.py`** — add:
```python
from datetime import datetime
from fastapi import Query

@router.get("", response_model=list[SpillDetail])
async def list_spills(
    since: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    return list_recent_spills(since=since_dt, limit=limit)
```
(and add `list_recent_spills` to the existing import line from
`app.services.oil_spill_analysis`)

## 2. Device registration + push send

**New table** — `app/database/models.py`, add:
```python
class DeviceToken(Base):
    __tablename__ = "device_tokens"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```
Plus an Alembic migration for it (follow the pattern in
`alembic/versions/0002_spill_geometry.py`).

**New route** — `app/api/routes/devices.py`:
```python
from fastapi import APIRouter
from pydantic import BaseModel
from app.database.connection import session_scope
from app.database.models import DeviceToken
from sqlalchemy.dialects.postgresql import insert as pg_insert

router = APIRouter(prefix="/devices", tags=["devices"])

class DeviceRegisterRequest(BaseModel):
    token: str
    platform: str

@router.post("/register", status_code=204)
async def register_device(body: DeviceRegisterRequest) -> None:
    with session_scope() as session:
        stmt = pg_insert(DeviceToken).values(token=body.token, platform=body.platform)
        stmt = stmt.on_conflict_do_nothing(index_elements=[DeviceToken.token])
        session.execute(stmt)
```
Register it in `app/main.py`: `from app.api.routes import devices` and
`app.include_router(devices.router)`.

**Sending the push** — add to `requirements.txt`: `firebase-admin`. Then in
`app/services/oil_spill_analysis.py`, right after the existing
`spill = repo.create(...)` block inside `analyze_tiff()`, add a best-effort
push send (mirror the try/except pattern already used for attribution, so a
push failure never breaks the analyze response):

```python
def _notify_devices(spill) -> None:
    try:
        import firebase_admin
        from firebase_admin import messaging
        with session_scope() as session:
            tokens = [t.token for t in session.query(DeviceToken).all()]
        for token in tokens:
            messaging.send(messaging.Message(
                data={
                    "type": "oil_spill_alert",
                    "id": spill.id,
                    "latitude": str(spill.centroid_latitude),
                    "longitude": str(spill.centroid_longitude),
                    "detected_at": spill.detected_at.isoformat(),
                    "confidence": str(spill.confidence),
                    "area": str(spill.area),
                    "region_count": "",
                },
                token=token,
            ))
    except Exception:
        logger.exception("push notification failed for spill %s", spill.id)
```
Call `_notify_devices(spill)` right after the spill is persisted (before or
after attribution — doesn't matter, it's independent).

Needs a Firebase service-account JSON (from the same Firebase project the
mobile app is registered to — see the mobile app's README §3) and
`firebase_admin.initialize_app()` called once at startup in `app/main.py`'s
`lifespan`.

## Nothing else needs to change

`POST /oil-spills/analyze`, the ML/GIS pipeline, vessel attribution, and the
web dashboard's endpoints are untouched by any of this.
