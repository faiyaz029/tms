"""add statements, email deliveries and password resets

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.bulk_insert(
        sa.table(
            "business_settings",
            sa.column("key", sa.String()),
            sa.column("value", sa.String()),
        ),
        [{"key": "email_demo_failure_pending", "value": "true"}],
    )
    op.create_table(
        "shareholder_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("report_snapshots.id"), nullable=False),
        sa.Column("shareholder_id", sa.Integer(), sa.ForeignKey("shareholders.id"), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "shareholder_id", name="uq_statement_snapshot_shareholder"),
    )
    op.create_index(
        "ix_shareholder_statements_shareholder_id",
        "shareholder_statements",
        ["shareholder_id"],
    )
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("shareholder_statements.id")),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("provider_id", sa.String(length=255)),
        sa.Column("html_body", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_deliveries_created_at", "email_deliveries", ["created_at"])
    op.create_index(
        "ix_email_deliveries_status_created_at", "email_deliveries", ["status", "created_at"]
    )
    op.create_index("ix_email_deliveries_statement_id", "email_deliveries", ["statement_id"])
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_table(
        "password_reset_rate_buckets",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("request_count > 0", name="ck_password_reset_bucket_count_positive"),
    )
    op.create_index(
        "ix_password_reset_window_start",
        "password_reset_rate_buckets",
        ["window_start"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE TRIGGER prevent_shareholder_statements_mutation
            BEFORE UPDATE OR DELETE ON shareholder_statements
            FOR EACH ROW EXECUTE FUNCTION prevent_financial_history_mutation()
        """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS prevent_shareholder_statements_mutation ON shareholder_statements"
        )
    op.drop_index("ix_password_reset_window_start", table_name="password_reset_rate_buckets")
    op.drop_table("password_reset_rate_buckets")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_email_deliveries_status_created_at", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_created_at", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_statement_id", table_name="email_deliveries")
    op.drop_table("email_deliveries")
    op.drop_index(
        "ix_shareholder_statements_shareholder_id",
        table_name="shareholder_statements",
    )
    op.drop_table("shareholder_statements")
    op.execute(
        "DELETE FROM business_settings WHERE key = 'email_demo_failure_pending'"
    )
