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
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
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
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    weekday: Mapped[int] = mapped_column(nullable=False)
    open_time: Mapped[time] = mapped_column(Time(), nullable=False)
    close_time: Mapped[time] = mapped_column(Time(), nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SpecialDay(Base):
    __tablename__ = "special_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id"))
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    open_time: Mapped[time | None] = mapped_column(Time())
    close_time: Mapped[time | None] = mapped_column(Time())
    reason: Mapped[str | None] = mapped_column(String(160))


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))


class TurfPrice(Base):
    __tablename__ = "turf_prices"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_turf_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
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
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
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
    date: Mapped[date] = mapped_column(Date(), nullable=False)
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
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    channel: Mapped[BookingChannel] = mapped_column(
        Enum(BookingChannel, native_enum=False, length=12), nullable=False
    )
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=12), nullable=False
    )
    customer_contact_id: Mapped[int] = mapped_column(
        ForeignKey("customer_contacts.id"), nullable=False
    )
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="BDT", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pool_session_id: Mapped[int | None] = mapped_column(ForeignKey("pool_sessions.id"))
    participants: Mapped[int | None] = mapped_column()


class BookingEvent(Base):
    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
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
    method: Mapped[str] = mapped_column(ForeignKey("payment_methods.code"), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=12), nullable=False
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trx_id: Mapped[str | None] = mapped_column(String(120))
    sender_phone: Mapped[str | None] = mapped_column(String(20))
    bank_ref: Mapped[str | None] = mapped_column(String(120))
    sms_text: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
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
        Enum(PaymentIntentStatus, native_enum=False, length=12), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
