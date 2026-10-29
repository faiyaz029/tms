import enum
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index,
    Numeric, String, Text, Time, UniqueConstraint, select, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    staff = "staff"
    accountant = "accountant"
    shareholder = "shareholder"
    customer = "customer"


class FacilityType(str, enum.Enum):
    turf = "turf"
    pool = "pool"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, length=20), default=Role.customer
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def profile_complete(self) -> bool:
        return bool(self.phone and self.address)


class AuditLog(Base):
    """Append-only record of sensitive actions. Never update or delete rows."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_type: Mapped[FacilityType] = mapped_column(
        Enum(FacilityType, native_enum=False, length=12), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OperatingSchedule(Base):
    __tablename__ = "operating_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(nullable=False)
    open_time: Mapped[time] = mapped_column(Time(), nullable=False)
    close_time: Mapped[time] = mapped_column(Time(), nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SpecialDay(Base):
    __tablename__ = "special_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id"), index=True)
    date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time())
    close_time: Mapped[time | None] = mapped_column(Time())
    reason: Mapped[str | None] = mapped_column(String(160))


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(200))


class TurfPrice(Base):
    __tablename__ = "turf_prices"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_turf_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    weekday: Mapped[int | None] = mapped_column(nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time())
    end_time: Mapped[time | None] = mapped_column(Time())
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PoolSessionTemplate(Base):
    __tablename__ = "pool_session_templates"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_pool_template_capacity_positive"),
        CheckConstraint("price_per_person >= 0", name="ck_pool_template_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(nullable=False)
    start_time: Mapped[time] = mapped_column(Time(), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    price_per_person: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PoolSession(Base):
    __tablename__ = "pool_sessions"
    __table_args__ = (
        UniqueConstraint("facility_id", "date", "start_at", name="uq_pool_session_facility_date_start"),
        CheckConstraint("capacity > 0", name="ck_pool_session_capacity_positive"),
        CheckConstraint("price_per_person >= 0", name="ck_pool_session_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    price_per_person: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class CustomerContact(Base):
    __tablename__ = "customer_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    address: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)


class BookingChannel(str, enum.Enum):
    online = "online"
    phone = "phone"
    walk_in = "walk_in"


class BookingStatus(str, enum.Enum):
    draft = "draft"
    held = "held"
    confirmed = "confirmed"
    cancelled = "cancelled"
    expired = "expired"


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "(starts_at IS NOT NULL AND ends_at IS NOT NULL AND pool_session_id IS NULL "
            "AND participants IS NULL) OR "
            "(starts_at IS NULL AND ends_at IS NULL AND pool_session_id IS NOT NULL "
            "AND participants IS NOT NULL AND participants > 0)",
            name="ck_booking_facility_details",
        ),
        CheckConstraint("participants IS NULL OR participants > 0", name="ck_booking_participants_positive"),
        CheckConstraint("total_amount >= 0", name="ck_booking_total_nonnegative"),
        Index(
            "uq_bookings_ref",
            "ref",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), nullable=False)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False, index=True)
    channel: Mapped[BookingChannel] = mapped_column(
        Enum(BookingChannel, native_enum=False, length=12), nullable=False, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=12), nullable=False, index=True
    )
    customer_contact_id: Mapped[int] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BDT", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    pool_session_id: Mapped[int | None] = mapped_column(ForeignKey("pool_sessions.id"), index=True)
    participants: Mapped[int | None] = mapped_column()


class BookingEvent(Base):
    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    from_status: Mapped[BookingStatus | None] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=12)
    )
    to_status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=12), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    received = "received"
    verified = "verified"
    rejected = "rejected"
    failed = "failed"
    refunded = "refunded"


class PaymentMethod(Base):
    __tablename__ = "payment_methods"

    code: Mapped[str] = mapped_column(String(24), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_reference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index(
            "uq_payments_method_trx",
            "method",
            "trx_id",
            unique=True,
            postgresql_where=text("trx_id IS NOT NULL"),
            sqlite_where=text("trx_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[str] = mapped_column(
        ForeignKey("payment_methods.code"), nullable=False, index=True
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=12), nullable=False, index=True
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trx_id: Mapped[str | None] = mapped_column(String(120))
    sender_phone: Mapped[str | None] = mapped_column(String(20))
    bank_ref: Mapped[str | None] = mapped_column(String(120))
    sms_text: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    from_status: Mapped[PaymentStatus | None] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=12)
    )
    to_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=12), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)


class PaymentIntentStatus(str, enum.Enum):
    initiated = "initiated"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    abandoned = "abandoned"


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[PaymentIntentStatus] = mapped_column(
        Enum(PaymentIntentStatus, native_enum=False, length=12), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExpenseStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expense_amount_positive"),
        Index("uq_expenses_ref", "ref", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        ForeignKey("expense_categories.code"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(
        ForeignKey("payment_methods.code"), nullable=False, index=True
    )
    vendor: Mapped[str | None] = mapped_column(String(160))
    memo_no: Mapped[str | None] = mapped_column(String(120))
    has_physical_memo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trx_id: Mapped[str | None] = mapped_column(String(120))
    bank_ref: Mapped[str | None] = mapped_column(String(120))
    sms_text: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, native_enum=False, length=12), nullable=False, index=True
    )
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class ExpenseEvent(Base):
    __tablename__ = "expense_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)


class ReferenceCounter(Base):
    __tablename__ = "reference_counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date(), primary_key=True)
    value: Mapped[int] = mapped_column(nullable=False)


class DailyClosingStatus(str, enum.Enum):
    submitted = "submitted"
    reviewed = "reviewed"


class DailyClosing(Base):
    __tablename__ = "daily_closings"
    __table_args__ = (
        UniqueConstraint("business_date", "version", name="uq_daily_closing_date_version"),
        CheckConstraint("version > 0", name="ck_daily_closing_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date(), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[DailyClosingStatus] = mapped_column(
        Enum(DailyClosingStatus, native_enum=False, length=12), nullable=False, index=True
    )
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    difference_notes: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)


class Shareholder(Base):
    __tablename__ = "shareholders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    acquisition_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class Shareholding(Base):
    __tablename__ = "shareholdings"
    __table_args__ = (
        CheckConstraint("shares > 0", name="ck_shareholding_shares_positive"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_shareholding_dates_ordered",
        ),
        UniqueConstraint("shareholder_id", "effective_from", name="uq_shareholding_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shareholder_id: Mapped[int] = mapped_column(
        ForeignKey("shareholders.id"), nullable=False, index=True
    )
    shares: Mapped[int] = mapped_column(nullable=False)
    effective_from: Mapped[date] = mapped_column(Date(), nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date())


class EligibleShareSetting(Base):
    __tablename__ = "eligible_share_settings"
    __table_args__ = (
        CheckConstraint("year >= 2000", name="ck_eligible_share_year_valid"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_eligible_share_month_valid"),
        CheckConstraint("version > 0", name="ck_eligible_share_version_positive"),
        CheckConstraint("total_shares > 0", name="ck_eligible_share_total_positive"),
    )

    year: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    total_shares: Mapped[int] = mapped_column(nullable=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class ReportingPeriodStatus(str, enum.Enum):
    preliminary = "preliminary"
    under_review = "under_review"
    approved = "approved"
    reopened = "reopened"


class ReportingPeriod(Base):
    __tablename__ = "reporting_periods"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_reporting_period_year_month"),
        CheckConstraint("year >= 2000", name="ck_reporting_period_year_valid"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_reporting_period_month_valid"),
        CheckConstraint("version > 0", name="ck_reporting_period_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[ReportingPeriodStatus] = mapped_column(
        Enum(ReportingPeriodStatus, native_enum=False, length=16), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    review_note: Mapped[str | None] = mapped_column(Text)


class ReportChecklistItem(Base):
    __tablename__ = "report_checklist_items"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id", "version", "key",
            name="uq_report_checklist_period_version_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reporting_period_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_periods.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    key: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class DistributionDecision(Base):
    __tablename__ = "distribution_decisions"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id", "version",
            name="uq_distribution_decision_period_version",
        ),
        CheckConstraint("pool_amount >= 0", name="ck_distribution_pool_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reporting_period_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_periods.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    pool_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    retained_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReportSnapshot(Base):
    __tablename__ = "report_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "reporting_period_id", "version", name="uq_report_snapshot_period_version"
        ),
        CheckConstraint("total_shares > 0", name="ck_report_snapshot_total_shares_positive"),
        CheckConstraint("pool >= 0", name="ck_report_snapshot_pool_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reporting_period_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_periods.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    approved_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    calculation_basis: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    totals: Mapped[dict] = mapped_column(JSON, nullable=False)
    allocations: Mapped[list] = mapped_column(JSON, nullable=False)
    total_shares: Mapped[int] = mapped_column(nullable=False)
    pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    remainder: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    exception_reason: Mapped[str | None] = mapped_column(Text)


class ReportReopening(Base):
    __tablename__ = "report_reopenings"

    id: Mapped[int] = mapped_column(primary_key=True)
    reporting_period_id: Mapped[int] = mapped_column(
        ForeignKey("reporting_periods.id"), nullable=False, index=True
    )
    previous_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("report_snapshots.id"), nullable=False, index=True
    )
    previous_version: Mapped[int] = mapped_column(nullable=False)
    new_version: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BusinessSetting(Base):
    __tablename__ = "business_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

    @staticmethod
    def get(db, key: str, default: str | None = None) -> str | None:
        row = db.scalar(select(BusinessSetting).where(BusinessSetting.key == key))
        if row is None:
            return default
        return row.value

    @staticmethod
    def set(db, key: str, value: str) -> "BusinessSetting":
        row = db.scalar(select(BusinessSetting).where(BusinessSetting.key == key))
        if row is None:
            row = BusinessSetting(key=key, value=str(value))
            db.add(row)
        else:
            row.value = str(value)
        db.flush()
        return row

    @staticmethod
    def get_int(db, key: str, default: int) -> int:
        value = BusinessSetting.get(db, key)
        return int(value) if value is not None else default

    @staticmethod
    def get_bool(db, key: str, default: bool) -> bool:
        value = BusinessSetting.get(db, key)
        return str(value).lower() in {"1", "true", "yes", "y"} if value is not None else default


class ShareholderStatement(Base):
    __tablename__ = "shareholder_statements"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "shareholder_id", name="uq_statement_snapshot_shareholder"),
        Index("ix_shareholder_statements_shareholder_id", "shareholder_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("report_snapshots.id"), nullable=False)
    shareholder_id: Mapped[int] = mapped_column(ForeignKey("shareholders.id"), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class EmailDeliveryStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    previewed = "previewed"


class EmailDelivery(Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        Index("ix_email_deliveries_created_at", "created_at"),
        Index("ix_email_deliveries_status_created_at", "status", "created_at"),
        Index("ix_email_deliveries_statement_id", "statement_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int | None] = mapped_column(ForeignKey("shareholder_statements.id"))
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[EmailDeliveryStatus] = mapped_column(
        Enum(EmailDeliveryStatus, native_enum=False, length=12), nullable=False
    )
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_id: Mapped[str | None] = mapped_column(String(255))
    html_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PasswordResetRateBucket(Base):
    __tablename__ = "password_reset_rate_buckets"
    __table_args__ = (
        CheckConstraint("request_count > 0", name="ck_password_reset_bucket_count_positive"),
        Index("ix_password_reset_window_start", "window_start"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(nullable=False)
