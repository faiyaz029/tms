"""add expense tracking and versioned daily closings

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "expense_categories",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "expense_categories",
            sa.column("code", sa.String()),
            sa.column("label", sa.String()),
            sa.column("is_active", sa.Boolean()),
        ),
        [
            {"code": "electricity", "label": "Electricity", "is_active": True},
            {"code": "cleaning", "label": "Cleaning", "is_active": True},
            {"code": "maintenance", "label": "Maintenance", "is_active": True},
            {"code": "supplies", "label": "Supplies", "is_active": True},
            {"code": "salary", "label": "Salary", "is_active": True},
            {"code": "other", "label": "Other", "is_active": True},
        ],
    )
    op.create_table(
        "reference_counters",
        sa.Column("name", sa.String(length=32), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref", sa.String(length=20), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=32), sa.ForeignKey("expense_categories.code"), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(length=24), sa.ForeignKey("payment_methods.code"), nullable=False),
        sa.Column("vendor", sa.String(length=160)),
        sa.Column("memo_no", sa.String(length=120)),
        sa.Column("has_physical_memo", sa.Boolean(), nullable=False),
        sa.Column("trx_id", sa.String(length=120)),
        sa.Column("bank_ref", sa.String(length=120)),
        sa.Column("sms_text", sa.Text()),
        sa.Column("entered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
    )
    op.create_index("uq_expenses_ref", "expenses", ["ref"], unique=True)
    op.create_index("ix_expenses_expense_date", "expenses", ["expense_date"])
    op.create_index("ix_expenses_payment_date", "expenses", ["payment_date"])
    op.create_table(
        "expense_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("expenses.id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("before", sa.JSON()),
        sa.Column("after", sa.JSON()),
        sa.Column("reason", sa.Text()),
    )
    op.create_index("ix_expense_events_expense_id", "expense_events", ["expense_id"])
    op.create_table(
        "daily_closings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("difference_notes", sa.Text()),
        sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_notes", sa.Text()),
        sa.UniqueConstraint("business_date", "version", name="uq_daily_closing_date_version"),
        sa.CheckConstraint("version > 0", name="ck_daily_closing_version_positive"),
    )
    op.create_index("ix_daily_closings_business_date", "daily_closings", ["business_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_closings_business_date", table_name="daily_closings")
    op.drop_table("daily_closings")
    op.drop_index("ix_expense_events_expense_id", table_name="expense_events")
    op.drop_table("expense_events")
    op.drop_index("ix_expenses_payment_date", table_name="expenses")
    op.drop_index("ix_expenses_expense_date", table_name="expenses")
    op.drop_index("uq_expenses_ref", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("reference_counters")
    op.drop_table("expense_categories")
