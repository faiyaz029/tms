import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import (
    Booking, BookingChannel, BookingStatus, BusinessSetting, DailyClosing,
    DailyClosingStatus, EmailDelivery, Expense, ExpenseStatus, Payment,
    PaymentStatus, PoolSession, ReportSnapshot, ReportingPeriod,
    ReportingPeriodStatus, Role, Shareholder, ShareholderStatement,
    Shareholding, User,
)
from app.seed import seed_demo


def test_seed_builds_repeatable_role_complete_demo_data(db, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "demo")

    seed_demo(db)

    assert db.scalar(select(func.count()).select_from(User)) == 12
    assert {user.role for user in db.scalars(select(User)).all()} == set(Role)
    assert db.scalar(select(func.count()).select_from(Booking)) >= 6
    assert {booking.channel for booking in db.scalars(select(Booking)).all()} == set(BookingChannel)
    assert {booking.status for booking in db.scalars(select(Booking)).all()} >= {
        BookingStatus.confirmed,
        BookingStatus.held,
        BookingStatus.cancelled,
        BookingStatus.expired,
    }
    assert {payment.status for payment in db.scalars(select(Payment)).all()} == {
        PaymentStatus.verified,
        PaymentStatus.received,
        PaymentStatus.rejected,
    }
    assert {expense.status for expense in db.scalars(select(Expense)).all()} == {
        ExpenseStatus.approved,
        ExpenseStatus.pending,
        ExpenseStatus.rejected,
    }
    assert db.scalar(select(func.count()).select_from(PoolSession)) == 30
    assert db.scalar(select(func.count()).select_from(Shareholder)) == 5
    assert db.scalar(select(func.sum(Shareholding.shares))) == 50
    assert db.scalar(select(func.count()).select_from(ShareholderStatement)) == 5
    assert db.scalar(select(func.count()).select_from(EmailDelivery)) == 5
    assert db.scalar(select(func.count()).select_from(ReportSnapshot)) == 1
    assert db.scalar(select(func.count()).select_from(ReportingPeriod)) == 2
    assert db.scalar(select(func.count()).select_from(DailyClosing)) == 1
    assert db.scalar(select(DailyClosing.status)) == DailyClosingStatus.reviewed
    assert db.scalar(
        select(ReportingPeriod.status)
        .where(ReportingPeriod.status == ReportingPeriodStatus.preliminary)
    ) == ReportingPeriodStatus.preliminary
    assert BusinessSetting.get(db, "email_demo_failure_pending") == "true"

    received_then_verified = db.scalar(
        select(Payment).where(Payment.ref == "PAY-DEMO-0001")
    )
    assert received_then_verified.status == PaymentStatus.verified
    assert received_then_verified.received_at.month != received_then_verified.verified_at.month

    with pytest.raises(RuntimeError, match="already exists"):
        seed_demo(db)

    seed_demo(db, reset=True)
    assert db.scalar(select(func.count()).select_from(User)) == 12
    assert db.scalar(select(func.count()).select_from(ReportSnapshot)) == 1


def test_seed_refuses_production_environment(db, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")

    with pytest.raises(RuntimeError, match="development or demo"):
        seed_demo(db)

    assert db.scalar(select(func.count()).select_from(User)) == 0
