from pydantic import BaseModel, EmailStr, Field, field_validator

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
