"""booking records, hold events, and turf concurrency guard

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_pool_session_facility_date_start",
        "pool_sessions",
        ["facility_id", "date", "start_at"],
    )
    op.create_table(
        "customer_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True),
    )
    op.create_index("ix_customer_contacts_phone", "customer_contacts", ["phone"])
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref", sa.String(length=20), nullable=False),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("channel", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column(
            "customer_contact_id",
            sa.Integer(),
            sa.ForeignKey("customer_contacts.id"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True)),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("pool_session_id", sa.Integer(), sa.ForeignKey("pool_sessions.id")),
        sa.Column("participants", sa.Integer()),
        sa.CheckConstraint(
            "(starts_at IS NOT NULL AND ends_at IS NOT NULL AND pool_session_id IS NULL "
            "AND participants IS NULL) OR "
            "(starts_at IS NULL AND ends_at IS NULL AND pool_session_id IS NOT NULL "
            "AND participants IS NOT NULL AND participants > 0)",
            name="ck_booking_facility_details",
        ),
        sa.CheckConstraint(
            "participants IS NULL OR participants > 0",
            name="ck_booking_participants_positive",
        ),
        ExcludeConstraint(
            ("facility_id", "="),
            (sa.text("tstzrange(starts_at, ends_at, '[)')"), "&&"),
            where=sa.text(
                "starts_at IS NOT NULL AND status IN ('held', 'confirmed')"
            ),
            using="gist",
            name="ex_bookings_turf_interval",
        ),
    )
    op.create_index("uq_bookings_ref", "bookings", ["ref"], unique=True)
    op.create_index("ix_bookings_hold_expires_at", "bookings", ["hold_expires_at"])
    op.create_table(
        "booking_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("from_status", sa.String(length=12)),
        sa.Column("to_status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("data", sa.JSON()),
    )
    op.create_index("ix_booking_events_booking_id", "booking_events", ["booking_id"])

    op.execute(
        """
        INSERT INTO turf_prices (facility_id, weekday, start_time, end_time, price, is_active)
        SELECT id, NULL, NULL, NULL, 2000.00, TRUE
        FROM facilities
        WHERE facility_type = 'turf'
          AND NOT EXISTS (
              SELECT 1 FROM turf_prices WHERE facility_id = facilities.id AND is_active = TRUE
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM turf_prices
        WHERE weekday IS NULL AND start_time IS NULL AND end_time IS NULL AND price = 2000.00
          AND facility_id IN (SELECT id FROM facilities WHERE facility_type = 'turf')
        """
    )
    op.drop_index("ix_booking_events_booking_id", table_name="booking_events")
    op.drop_table("booking_events")
    op.drop_index("ix_bookings_hold_expires_at", table_name="bookings")
    op.drop_index("uq_bookings_ref", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("ix_customer_contacts_phone", table_name="customer_contacts")
    op.drop_table("customer_contacts")
    op.drop_constraint(
        "uq_pool_session_facility_date_start",
        "pool_sessions",
        type_="unique",
    )
