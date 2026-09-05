"""initial schema: vessels, ais_positions, oil_spills, attribution_results

Plain PostgreSQL design: spatial queries use latitude/longitude columns plus the
``haversine_km`` SQL function, so no PostGIS extension is required. A PostGIS
``geography(Point, 4326)`` geometry can be added in a follow-up migration if
spatial workloads grow.

AIS and oil-spill data are kept in separate tables; ``attribution_results`` links
a spill to candidate vessels via spatial + temporal query results.

Revision ID: 0001
Revises:
Create Date: 2026-09-05
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


HAVERSINE_FN = """
CREATE FUNCTION haversine_km(
    a_lat double precision, a_lon double precision,
    b_lat double precision, b_lon double precision
) RETURNS double precision
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
RETURN (
    6371.0088 * 2.0 * asin(
        sqrt(
            power(sin(radians((b_lat - a_lat) / 2.0)), 2)
            + cos(radians(a_lat)) * cos(radians(b_lat))
              * power(sin(radians((b_lon - a_lon) / 2.0)), 2)
        )
    )
);
"""


def upgrade() -> None:
    op.execute(HAVERSINE_FN)

    op.execute(
        """
        CREATE TABLE vessels (
            id          BIGSERIAL PRIMARY KEY,
            mmsi        BIGINT NOT NULL CONSTRAINT uq_vessels_mmsi UNIQUE,
            ship_name   VARCHAR(128),
            ship_type   INTEGER,
            imo         VARCHAR(16),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE ais_positions (
            id         BIGSERIAL PRIMARY KEY,
            mmsi       BIGINT NOT NULL REFERENCES vessels(mmsi) ON DELETE CASCADE,
            timestamp  TIMESTAMPTZ NOT NULL,
            latitude   DOUBLE PRECISION NOT NULL,
            longitude  DOUBLE PRECISION NOT NULL,
            speed      DOUBLE PRECISION,
            course     DOUBLE PRECISION,
            heading    DOUBLE PRECISION
        );
        CREATE INDEX ix_ais_positions_mmsi
            ON ais_positions (mmsi);
        CREATE INDEX ix_ais_positions_timestamp
            ON ais_positions (timestamp);
        CREATE INDEX ix_ais_positions_mmsi_timestamp
            ON ais_positions (mmsi, timestamp);
        CREATE INDEX ix_ais_positions_lat_lon
            ON ais_positions (latitude, longitude);
        """
    )

    op.execute(
        """
        CREATE TABLE oil_spills (
            id                  VARCHAR(36) PRIMARY KEY,
            detected_at         TIMESTAMPTZ NOT NULL,
            centroid_latitude   DOUBLE PRECISION NOT NULL,
            centroid_longitude  DOUBLE PRECISION NOT NULL,
            area                DOUBLE PRECISION,
            confidence          DOUBLE PRECISION,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_oil_spills_detected_at
            ON oil_spills (detected_at);
        CREATE INDEX ix_oil_spills_centroid_lat_lon
            ON oil_spills (centroid_latitude, centroid_longitude);
        """
    )

    op.execute(
        """
        CREATE TABLE attribution_results (
            id                       BIGSERIAL PRIMARY KEY,
            spill_id                 VARCHAR(36) NOT NULL
                                     REFERENCES oil_spills(id) ON DELETE CASCADE,
            mmsi                     BIGINT NOT NULL
                                     REFERENCES vessels(mmsi) ON DELETE CASCADE,
            distance_km              DOUBLE PRECISION,
            time_difference_minutes  DOUBLE PRECISION,
            score                    DOUBLE PRECISION,
            rank                     INTEGER,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_attribution_results_spill_id
            ON attribution_results (spill_id);
        CREATE INDEX ix_attribution_results_mmsi
            ON attribution_results (mmsi);
        CREATE INDEX ix_attribution_results_spill_id_rank
            ON attribution_results (spill_id, rank);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attribution_results;")
    op.execute("DROP TABLE IF EXISTS oil_spills;")
    op.execute("DROP TABLE IF EXISTS ais_positions;")
    op.execute("DROP TABLE IF EXISTS vessels;")
    op.execute("DROP FUNCTION IF EXISTS haversine_km(double precision, double precision, double precision, double precision);")