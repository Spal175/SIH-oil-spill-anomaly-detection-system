"""persist spill metadata: crs, region_count and attribution evidence

Adds ``oil_spills.crs`` / ``oil_spills.region_count`` so the source CRS and the
number of detected regions survive in the database (they were previously only
surfaced in the analyze response) and ``attribution_results.evidence`` so the
human-readable evidence strings are readable from the read endpoints.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE oil_spills ADD COLUMN crs TEXT;")
    op.execute("ALTER TABLE oil_spills ADD COLUMN region_count INTEGER;")
    op.execute("ALTER TABLE attribution_results ADD COLUMN evidence TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE attribution_results DROP COLUMN evidence;")
    op.execute("ALTER TABLE oil_spills DROP COLUMN region_count;")
    op.execute("ALTER TABLE oil_spills DROP COLUMN crs;")