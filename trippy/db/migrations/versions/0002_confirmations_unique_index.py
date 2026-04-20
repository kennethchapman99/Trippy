"""Add partial unique index on confirmations(confirmation_code, vendor).

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-19
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate rows, keeping the one with the lowest id (first seen)
    op.execute(
        """
        DELETE FROM confirmations
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM confirmations
            WHERE confirmation_code NOT LIKE '%UNKNOWN%'
            GROUP BY confirmation_code, vendor
        )
        AND confirmation_code NOT LIKE '%UNKNOWN%'
        """
    )
    # Partial unique index: deduplicate real codes, allow multiple UNKNOWNs
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_confirmations_code_vendor
        ON confirmations (confirmation_code, vendor)
        WHERE confirmation_code NOT LIKE '%UNKNOWN%'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_confirmations_code_vendor")
