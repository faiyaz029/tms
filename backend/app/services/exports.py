from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from ..config import settings
from ..models import (
    Booking, BookingChannel, BookingStatus, DailyClosing, Expense, Payment,
    PaymentStatus, PoolSession, ReportSnapshot, ReportingPeriod,
)

BUSINESS_TZ = ZoneInfo(settings.business_timezone)
UTC = timezone.utc


def booking_query(
    date_from: date | None,
    date_to: date | None,
    facility_id: int | None,
    channel: BookingChannel | None,
    status: BookingStatus | None,
    ref: str | None,
):
    query = select(Booking).outerjoin(PoolSession, Booking.pool_session_id == PoolSession.id)
    if facility_id:
        query = query.where(Booking.facility_id == facility_id)
    if channel:
        query = query.where(Booking.channel == channel)
    if status:
        query = query.where(Booking.status == status)
    if ref:
        query = query.where(Booking.ref.ilike(f"%{ref}%"))
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    if date_from or date_to:
        turf_bounds = []
        pool_bounds = []
        if date_from:
            start_bound = datetime.combine(
                date_from, time.min, tzinfo=BUSINESS_TZ,
            ).astimezone(UTC)
            turf_bounds.append(Booking.starts_at >= start_bound)
            pool_bounds.append(PoolSession.date >= date_from)
        if date_to:
            end_bound = datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ,
            ).astimezone(UTC)
            turf_bounds.append(Booking.starts_at < end_bound)
            pool_bounds.append(PoolSession.date <= date_to)
        query = query.where(or_(and_(*turf_bounds), and_(*pool_bounds)))
    return query


def payment_query(
    received_from: date | None,
    received_to: date | None,
    method: str | None,
    status: PaymentStatus | None,
):
    if received_from and received_to and received_from > received_to:
        raise HTTPException(422, "received_from must be on or before received_to")
    query = select(Payment)
    if received_from:
        lower = datetime.combine(
            received_from, time.min, tzinfo=BUSINESS_TZ,
        ).astimezone(UTC)
        query = query.where(Payment.received_at >= lower)
    if received_to:
        upper = datetime.combine(
            received_to + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ,
        ).astimezone(UTC)
        query = query.where(Payment.received_at < upper)
    if method:
        query = query.where(Payment.method == method)
    if status:
        query = query.where(Payment.status == status)
    return query


def expense_query(
    ref: str | None,
    date_from: date | None,
    date_to: date | None,
    amount: Decimal | None,
    category: str | None,
    vendor: str | None,
    method: str | None,
    trx_id: str | None,
    memo_no: str | None,
    status: str | None,
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    query = select(Expense)
    if date_from:
        query = query.where(Expense.expense_date >= date_from)
    if date_to:
        query = query.where(Expense.expense_date <= date_to)
    if ref:
        query = query.where(Expense.ref.ilike(f"%{ref.strip()}%"))
    if amount is not None:
        query = query.where(Expense.amount == amount)
    if category:
        query = query.where(Expense.category == category.strip().lower())
    if vendor:
        query = query.where(Expense.vendor.ilike(f"%{vendor.strip()}%"))
    if method:
        query = query.where(Expense.method == method.strip().lower())
    if trx_id:
        query = query.where(Expense.trx_id.ilike(f"%{trx_id.strip()}%"))
    if memo_no:
        query = query.where(Expense.memo_no.ilike(f"%{memo_no.strip()}%"))
    if status:
        query = query.where(Expense.status == status)
    return query


def closing_query(business_date: date | None):
    query = select(DailyClosing)
    if business_date:
        query = query.where(DailyClosing.business_date == business_date)
    return query


def report_snapshot_query(year: int | None, month: int | None):
    if month is not None and (year is None or not 1 <= month <= 12):
        raise HTTPException(422, "A valid year is required with the report month")
    if year is not None and (year < 2000 or year >= 9999):
        raise HTTPException(422, "Provide a valid reporting year")
    query = (
        select(ReportSnapshot, ReportingPeriod)
        .join(ReportingPeriod, ReportingPeriod.id == ReportSnapshot.reporting_period_id)
    )
    if year is not None:
        query = query.where(ReportingPeriod.year == year)
    if month is not None:
        query = query.where(ReportingPeriod.month == month)
    return query
