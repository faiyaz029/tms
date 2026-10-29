from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from .models import Role
from .security import normalize_bd_phone


class PhoneAddr(BaseModel):
    phone: str
    address: str = Field(min_length=8, max_length=300)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_bd_phone(v)


class RegisterIn(PhoneAddr):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleIn(BaseModel):
    credential: str


class ProfileIn(PhoneAddr):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)


class StaffCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(min_length=2, max_length=120)
    role: Role
    phone: str | None = None
    address: str | None = None

    @field_validator("role")
    @classmethod
    def _not_customer(cls, v: Role) -> Role:
        if v == Role.customer:
            raise ValueError("Customers register themselves; create staff-type roles here")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return normalize_bd_phone(v) if v else v


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    phone: str | None
    address: str | None
    role: Role
    is_active: bool
    profile_complete: bool
    permissions: list[str]


class SettingUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=255)
    reason: str | None = Field(default=None, max_length=300)


class BookingSelection(BaseModel):
    facility_id: int = Field(gt=0)
    starts_at: datetime | None = None
    pool_session_id: int | None = Field(default=None, gt=0)
    participants: int | None = Field(default=None, gt=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _selection_shape(self):
        turf_selection = self.starts_at is not None
        pool_selection = self.pool_session_id is not None and self.participants is not None
        if turf_selection == pool_selection:
            raise ValueError("Provide either a turf start time or a pool session and participant count")
        if self.pool_session_id is not None and self.participants is None:
            raise ValueError("participants is required for a pool session")
        if self.participants is not None and self.pool_session_id is None:
            raise ValueError("pool_session_id is required when participants are provided")
        if self.starts_at is not None and self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        return self


class StaffBookingIn(BookingSelection):
    channel: Literal["phone", "walk_in"]
    customer_name: str = Field(min_length=2, max_length=120)
    customer_phone: str
    customer_address: str | None = Field(default=None, max_length=300)

    @field_validator("customer_phone")
    @classmethod
    def _customer_phone(cls, value: str) -> str:
        return normalize_bd_phone(value)


class BookingActionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ExtendHoldIn(BookingActionIn):
    minutes: int = Field(gt=0, le=1440)


class ManualPaymentIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(min_length=1, max_length=24)
    received_at: datetime
    trx_id: str | None = Field(default=None, max_length=120)
    sender_phone: str | None = Field(default=None, max_length=20)
    bank_ref: str | None = Field(default=None, max_length=120)
    sms_text: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("received_at")
    @classmethod
    def _received_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("received_at must include a timezone")
        return value

    @field_validator("sender_phone")
    @classmethod
    def _sender_phone(cls, value: str | None) -> str | None:
        return normalize_bd_phone(value) if value else value

    @field_validator("trx_id", "bank_ref")
    @classmethod
    def _trim_reference(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None


class PaymentRejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OnlinePaymentIn(BaseModel):
    booking_id: int = Field(gt=0)
