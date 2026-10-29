import enum
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text, Time, select
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

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    weekday: Mapped[int | None] = mapped_column(nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time())
    end_time: Mapped[time | None] = mapped_column(Time())
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PoolSessionTemplate(Base):
    __tablename__ = "pool_session_templates"

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

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    price_per_person: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


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
