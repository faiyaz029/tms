"""phase 2 facilities and availability

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_type", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "operating_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=False),
        sa.Column("close_time", sa.Time(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "special_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id")),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("open_time", sa.Time()),
        sa.Column("close_time", sa.Time()),
        sa.Column("reason", sa.String(length=160)),
    )
    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=200)),
    )
    op.create_table(
        "turf_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("weekday", sa.Integer()),
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "pool_session_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("price_per_person", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "pool_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.Integer(), sa.ForeignKey("facilities.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("price_per_person", sa.Numeric(12, 2), nullable=False),
    )
    op.create_table(
        "business_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
    )
    op.create_index(op.f("ix_business_settings_key"), "business_settings", ["key"], unique=True)
    op.bulk_insert(
        sa.table(
            "facilities",
            sa.column("facility_type", sa.String),
            sa.column("name", sa.String),
            sa.column("is_active", sa.Boolean),
        ),
        [
            {"facility_type": "turf", "name": "Main Turf", "is_active": True},
            {"facility_type": "pool", "name": "Pool", "is_active": True},
        ],
    )
    op.bulk_insert(
        sa.table(
            "business_settings",
            sa.column("key", sa.String),
            sa.column("value", sa.String),
        ),
        [
            {"key": "booking_horizon_days", "value": "21"},
            {"key": "turf_slot_step_minutes", "value": "30"},
            {"key": "turf_duration_minutes", "value": "60"},
            {"key": "hold_minutes_online", "value": "10"},
            {"key": "hold_minutes_phone", "value": "30"},
            {"key": "business_name", "value": "Turf & Pool Manager"},
            {"key": "payment_instructions", "value": "Please pay using the approved method."},
        ],
    )
    op.bulk_insert(
        sa.table(
            "operating_schedules",
            sa.column("facility_id", sa.Integer),
            sa.column("weekday", sa.Integer),
            sa.column("open_time", sa.Time),
            sa.column("close_time", sa.Time),
            sa.column("is_closed", sa.Boolean),
        ),
        [
            {"facility_id": 1, "weekday": 0, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 1, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 2, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 3, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 4, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 5, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 1, "weekday": 6, "open_time": "11:00:00", "close_time": "21:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 0, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 1, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 2, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 3, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 4, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 5, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
            {"facility_id": 2, "weekday": 6, "open_time": "08:00:00", "close_time": "18:00:00", "is_closed": False},
        ],
    )
    op.bulk_insert(
        sa.table(
            "pool_session_templates",
            sa.column("facility_id", sa.Integer),
            sa.column("weekday", sa.Integer),
            sa.column("start_time", sa.Time),
            sa.column("end_time", sa.Time),
            sa.column("capacity", sa.Integer),
            sa.column("price_per_person", sa.Numeric(12, 2)),
            sa.column("is_active", sa.Boolean),
        ),
        [
            {"facility_id": 2, "weekday": 0, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 1, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 2, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 3, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 4, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 5, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
            {"facility_id": 2, "weekday": 6, "start_time": "09:00:00", "end_time": "10:30:00", "capacity": 10, "price_per_person": "250.00", "is_active": True},
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_business_settings_key"), table_name="business_settings")
    op.drop_table("pool_sessions")
    op.drop_table("pool_session_templates")
    op.drop_table("turf_prices")
    op.drop_table("blocks")
    op.drop_table("special_days")
    op.drop_table("operating_schedules")
    op.drop_table("business_settings")
    op.drop_table("facilities")
