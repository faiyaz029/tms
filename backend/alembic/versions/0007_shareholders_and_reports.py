"""add shareholders and monthly financial reports

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shareholders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("acquisition_amount", sa.Numeric(12, 2)),
    )
    op.create_table(
        "shareholdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shareholder_id", sa.Integer(), sa.ForeignKey("shareholders.id"), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.CheckConstraint("shares > 0", name="ck_shareholding_shares_positive"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_shareholding_dates_ordered",
        ),
        sa.UniqueConstraint("shareholder_id", "effective_from", name="uq_shareholding_start"),
    )
    op.create_index("ix_shareholdings_shareholder_id", "shareholdings", ["shareholder_id"])
    op.create_table(
        "eligible_share_settings",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("total_shares", sa.Integer(), nullable=False),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.CheckConstraint("year >= 2000", name="ck_eligible_share_year_valid"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_eligible_share_month_valid"),
        sa.CheckConstraint("version > 0", name="ck_eligible_share_version_positive"),
        sa.CheckConstraint("total_shares > 0", name="ck_eligible_share_total_positive"),
    )
    op.create_table(
        "reporting_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("review_note", sa.Text()),
        sa.UniqueConstraint("year", "month", name="uq_reporting_period_year_month"),
        sa.CheckConstraint("year >= 2000", name="ck_reporting_period_year_valid"),
        sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_reporting_period_month_valid"),
        sa.CheckConstraint("version > 0", name="ck_reporting_period_version_positive"),
    )
    op.create_table(
        "report_checklist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_period_id", sa.Integer(), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=48), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False),
        sa.Column("done_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint(
            "reporting_period_id", "version", "key",
            name="uq_report_checklist_period_version_key",
        ),
    )
    op.create_table(
        "distribution_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_period_id", sa.Integer(), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pool_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("retained_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "reporting_period_id", "version",
            name="uq_distribution_decision_period_version",
        ),
        sa.CheckConstraint("pool_amount >= 0", name="ck_distribution_pool_nonnegative"),
    )
    op.create_table(
        "report_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_period_id", sa.Integer(), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("calculation_basis", sa.Text(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column("allocations", sa.JSON(), nullable=False),
        sa.Column("total_shares", sa.Integer(), nullable=False),
        sa.Column("pool", sa.Numeric(12, 2), nullable=False),
        sa.Column("remainder", sa.Numeric(12, 2), nullable=False),
        sa.Column("exception_reason", sa.Text()),
        sa.UniqueConstraint(
            "reporting_period_id", "version", name="uq_report_snapshot_period_version"
        ),
        sa.CheckConstraint("total_shares > 0", name="ck_report_snapshot_total_shares_positive"),
        sa.CheckConstraint("pool >= 0", name="ck_report_snapshot_pool_nonnegative"),
    )
    op.create_table(
        "report_reopenings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporting_period_id", sa.Integer(), sa.ForeignKey("reporting_periods.id"), nullable=False),
        sa.Column("previous_snapshot_id", sa.Integer(), sa.ForeignKey("report_snapshots.id"), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authorized_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_financial_history_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Financial history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$ LANGUAGE plpgsql
        """)
        for table in ("report_snapshots", "audit_logs"):
            op.execute(f"""
                CREATE TRIGGER prevent_{table}_mutation
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION prevent_financial_history_mutation()
            """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("report_snapshots", "audit_logs"):
            op.execute(f"DROP TRIGGER IF EXISTS prevent_{table}_mutation ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_financial_history_mutation()")
    op.drop_table("report_reopenings")
    op.drop_table("report_snapshots")
    op.drop_table("distribution_decisions")
    op.drop_table("report_checklist_items")
    op.drop_table("reporting_periods")
    op.drop_table("eligible_share_settings")
    op.drop_index("ix_shareholdings_shareholder_id", table_name="shareholdings")
    op.drop_table("shareholdings")
    op.drop_table("shareholders")
