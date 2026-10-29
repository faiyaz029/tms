"""booking price and capacity checks

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_turf_price_nonnegative",
        "turf_prices",
        "price >= 0",
    )
    op.create_check_constraint(
        "ck_pool_template_capacity_positive",
        "pool_session_templates",
        "capacity > 0",
    )
    op.create_check_constraint(
        "ck_pool_template_price_nonnegative",
        "pool_session_templates",
        "price_per_person >= 0",
    )
    op.create_check_constraint(
        "ck_pool_session_capacity_positive",
        "pool_sessions",
        "capacity > 0",
    )
    op.create_check_constraint(
        "ck_pool_session_price_nonnegative",
        "pool_sessions",
        "price_per_person >= 0",
    )
    op.create_check_constraint(
        "ck_booking_total_nonnegative",
        "bookings",
        "total_amount >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_booking_total_nonnegative", "bookings", type_="check")
    op.drop_constraint("ck_pool_session_price_nonnegative", "pool_sessions", type_="check")
    op.drop_constraint("ck_pool_session_capacity_positive", "pool_sessions", type_="check")
    op.drop_constraint(
        "ck_pool_template_price_nonnegative",
        "pool_session_templates",
        type_="check",
    )
    op.drop_constraint(
        "ck_pool_template_capacity_positive",
        "pool_session_templates",
        type_="check",
    )
    op.drop_constraint("ck_turf_price_nonnegative", "turf_prices", type_="check")
