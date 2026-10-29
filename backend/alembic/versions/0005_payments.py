"""add payment records and simulated payment intents

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_methods",
        sa.Column("code", sa.String(length=24), primary_key=True),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("requires_reference", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "payment_methods",
            sa.column("code", sa.String()),
            sa.column("label", sa.String()),
            sa.column("is_active", sa.Boolean()),
            sa.column("requires_reference", sa.Boolean()),
        ),
        [
            {"code": "cash", "label": "Cash", "is_active": True, "requires_reference": False},
            {"code": "bkash", "label": "bKash", "is_active": True, "requires_reference": True},
            {"code": "bank_transfer", "label": "Bank transfer", "is_active": True, "requires_reference": True},
            {"code": "card", "label": "Card", "is_active": True, "requires_reference": False},
            {"code": "other", "label": "Other", "is_active": True, "requires_reference": False},
            {"code": "online_simulated", "label": "Online (SIMULATED)", "is_active": True, "requires_reference": False},
        ],
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ref", sa.String(length=20), nullable=False, unique=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("method", sa.String(length=24), sa.ForeignKey("payment_methods.code"), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("trx_id", sa.String(length=120)),
        sa.Column("sender_phone", sa.String(length=20)),
        sa.Column("bank_ref", sa.String(length=120)),
        sa.Column("sms_text", sa.Text()),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("notes", sa.Text()),
        sa.Column("rejection_reason", sa.Text()),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
    )
    op.create_index("ix_payments_booking_id", "payments", ["booking_id"])
    op.create_index("ix_payments_received_at", "payments", ["received_at"])
    op.create_index(
        "uq_payments_method_trx",
        "payments",
        ["method", "trx_id"],
        unique=True,
        postgresql_where=sa.text("trx_id IS NOT NULL"),
        sqlite_where=sa.text("trx_id IS NOT NULL"),
    )
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("from_status", sa.String(length=12)),
        sa.Column("to_status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("data", sa.JSON()),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_payment_intents_booking_id", "payment_intents", ["booking_id"])
    op.execute(
        "INSERT INTO business_settings (key, value) "
        "VALUES ('require_different_verifier', 'true')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM business_settings WHERE key = 'require_different_verifier'")
    op.drop_index("ix_payment_intents_booking_id", table_name="payment_intents")
    op.drop_table("payment_intents")
    op.drop_index("ix_payment_events_payment_id", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index("uq_payments_method_trx", table_name="payments")
    op.drop_index("ix_payments_received_at", table_name="payments")
    op.drop_index("ix_payments_booking_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("payment_methods")
