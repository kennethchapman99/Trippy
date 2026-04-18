"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column(
            "status",
            sa.Enum("dream", "planned", "booked", "lived", "cancelled", name="tripstatus"),
            nullable=False,
            server_default="planned",
        ),
        sa.Column("destination_summary", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", "start_date", name="uq_trip_name_start"),
    )

    op.create_table(
        "travelers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("passport_country", sa.String(3), nullable=True),
        sa.Column("passport_expiry", sa.Date, nullable=True),
        sa.Column("date_of_birth", sa.Date, nullable=True),
        sa.UniqueConstraint("trip_id", "name", name="uq_traveler_trip_name"),
    )

    op.create_table(
        "legs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=False),
        sa.Column(
            "leg_type",
            sa.Enum("flight", "train", "ferry", "bus", "car", "other", name="legtype"),
            nullable=False,
        ),
        sa.Column("carrier", sa.String(100), nullable=True),
        sa.Column("flight_number", sa.String(20), nullable=True),
        sa.Column("origin", sa.String(10), nullable=False),
        sa.Column("destination", sa.String(10), nullable=False),
        sa.Column("depart_at", sa.DateTime, nullable=True),
        sa.Column("arrive_at", sa.DateTime, nullable=True),
        sa.Column("cabin_class", sa.String(50), nullable=True),
        sa.Column("cost_cad", sa.Float, nullable=True),
        sa.Column("confirmation_code", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "stays",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=False),
        sa.Column(
            "stay_type",
            sa.Enum("hotel", "airbnb", "vrbo", "hostel", "house", "other", name="staytype"),
            nullable=False,
        ),
        sa.Column("property_name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("check_in", sa.Date, nullable=True),
        sa.Column("check_out", sa.Date, nullable=True),
        sa.Column("cost_cad", sa.Float, nullable=True),
        sa.Column("confirmation_code", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "confirmations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=True),
        sa.Column(
            "confirmation_type",
            sa.Enum(
                "flight", "hotel", "rental", "tour", "transfer", "other", name="confirmationtype"
            ),
            nullable=False,
        ),
        sa.Column("confirmation_code", sa.String(50), nullable=False),
        sa.Column("vendor", sa.String(200), nullable=True),
        sa.Column("raw_email_path", sa.String(500), nullable=True),
        sa.Column("extracted_data", sa.Text, nullable=True),
        sa.Column("linked_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "preferences",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("source_trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "visa_checks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id"), nullable=False),
        sa.Column("traveler_id", sa.Integer, sa.ForeignKey("travelers.id"), nullable=False),
        sa.Column("destination_country", sa.String(3), nullable=False),
        sa.Column("passport_country", sa.String(3), nullable=False),
        sa.Column("visa_required", sa.Boolean, nullable=True),
        sa.Column("visa_type", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("checked_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("data_source", sa.String(50), nullable=False, server_default="static"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("traveler_id", sa.Integer, sa.ForeignKey("travelers.id"), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("visa_checks")
    op.drop_table("preferences")
    op.drop_table("confirmations")
    op.drop_table("stays")
    op.drop_table("legs")
    op.drop_table("travelers")
    op.drop_table("trips")
