"""add oil_spills.geometry_geojson (spill geometry when available)

Stores the normalized GeoJSON Polygon produced by the GIS service for a
detected spill (only the metadata is persisted — the raw 0/1 mask is not).
Plain TEXT in a nullable column; a PostGIS geography column can replace it in a
later migration when PostGIS is available.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE oil_spills ADD COLUMN geometry_geojson TEXT;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE oil_spills DROP COLUMN geometry_geojson;")