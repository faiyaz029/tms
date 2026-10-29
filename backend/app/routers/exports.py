import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import db as database
from ..audit import record
from ..db import get_db
from ..models import (
    Booking, BookingChannel, BookingStatus, CustomerContact, DailyClosing,
    Expense, Payment, PaymentStatus, PoolSession, ReportSnapshot, ReportingPeriod,
    User, Facility,
)
from ..permissions import require_permission
from ..services.exports import (
    booking_query, closing_query, expense_query, payment_query, report_snapshot_query,
)

router = APIRouter(tags=["exports"])


def _csv_row(values: list[object], untrusted_columns: set[int] | None = None) -> str:
    untrusted = untrusted_columns or set()
    safe_values = []
    for index, value in enumerate(values):
        rendered = "" if value is None else str(value)
        if index in untrusted and rendered.startswith(("=", "+", "-", "@", "\t", "\r")):
            rendered = "'" + rendered
        safe_values.append(rendered)
    buffer = StringIO(newline="")
    csv.writer(buffer, lineterminator="\r\n").writerow(safe_values)
    return buffer.getvalue()


def _bookings_csv(
    date_from: date | None,
    date_to: date | None,
    facility_id: int | None,
    channel: BookingChannel | None,
    status: BookingStatus | None,
    ref: str | None,
) -> Iterator[str]:
    with database.SessionLocal() as db:
        query = booking_query(date_from, date_to, facility_id, channel, status, ref)
        query = (
            query.add_columns(
                PoolSession.start_at,
                PoolSession.end_at,
                PoolSession.date,
                Facility.name,
                CustomerContact.name,
            )
            .join(Facility, Facility.id == Booking.facility_id)
            .outerjoin(CustomerContact, CustomerContact.id == Booking.customer_contact_id)
            .order_by(Booking.created_at.desc())
            .execution_options(yield_per=500)
        )
        yield _csv_row([
            "booking_ref", "facility", "channel", "status", "service_date",
            "service_start", "service_end", "participants", "total_amount",
            "currency", "customer_name", "created_at",
        ])
        for booking, pool_start, pool_end, pool_date, facility_name, customer_name in db.execute(query):
            start = pool_start or booking.starts_at
            end = pool_end or booking.ends_at
            service_date = pool_date.isoformat() if pool_date else start.date().isoformat() if start else ""
            yield _csv_row([
                booking.ref,
                facility_name,
                booking.channel.value,
                booking.status.value,
                service_date,
                start.isoformat() if start else "",
                end.isoformat() if end else "",
                booking.participants,
                booking.total_amount,
                booking.currency,
                customer_name,
                booking.created_at.isoformat(),
            ], {1, 10})


def _payments_csv(
    received_from: date | None,
    received_to: date | None,
    method: str | None,
    status: PaymentStatus | None,
) -> Iterator[str]:
    with database.SessionLocal() as db:
        query = (
            payment_query(received_from, received_to, method, status)
            .add_columns(Booking.ref)
            .join(Booking, Booking.id == Payment.booking_id)
            .order_by(Payment.recorded_at.desc())
            .execution_options(yield_per=500)
        )
        yield _csv_row([
            "payment_ref", "booking_ref", "amount", "currency", "method",
            "status", "received_at", "recorded_at", "verified_at",
        ])
        for payment, booking_ref in db.execute(query):
            yield _csv_row([
                payment.ref,
                booking_ref,
                payment.amount,
                payment.currency,
                "SIMULATED PAYMENT" if payment.method == "online_simulated" else payment.method,
                payment.status.value,
                payment.received_at.isoformat() if payment.received_at else "",
                payment.recorded_at.isoformat(),
                payment.verified_at.isoformat() if payment.verified_at else "",
            ])


def _expenses_csv(
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
) -> Iterator[str]:
    with database.SessionLocal() as db:
        query = (
            expense_query(
                ref, date_from, date_to, amount, category, vendor, method,
                trx_id, memo_no, status,
            )
            .order_by(Expense.created_at.desc())
            .execution_options(yield_per=500)
        )
        yield _csv_row([
            "expense_ref", "expense_date", "payment_date", "category",
            "description", "amount", "method", "vendor", "status", "approved_at",
        ])
        for expense in db.scalars(query):
            yield _csv_row([
                expense.ref,
                expense.expense_date.isoformat(),
                expense.payment_date.isoformat(),
                expense.category,
                expense.description,
                expense.amount,
                expense.method,
                expense.vendor,
                expense.status.value,
                expense.approved_at.isoformat() if expense.approved_at else "",
            ], {4, 7})


def _closings_csv(business_date: date | None) -> Iterator[str]:
    with database.SessionLocal() as db:
        query = (
            closing_query(business_date)
            .order_by(DailyClosing.business_date.desc(), DailyClosing.version.desc())
            .execution_options(yield_per=500)
        )
        yield _csv_row([
            "business_date", "version", "status", "received_collections",
            "verified_collections", "unverified_collections", "pending_expense_approvals",
            "submitted_at", "reviewed_at",
        ])
        for closing in db.scalars(query):
            totals = closing.totals
            collections = totals["collections_total"]
            pending = totals["pending_approvals"]
            yield _csv_row([
                closing.business_date.isoformat(),
                closing.version,
                closing.status.value,
                collections["received_amount"],
                collections["verified_amount"],
                collections["unverified_amount"],
                pending["amount"],
                closing.submitted_at.isoformat(),
                closing.reviewed_at.isoformat() if closing.reviewed_at else "",
            ])


def _reports_csv(year: int | None, month: int | None) -> Iterator[str]:
    with database.SessionLocal() as db:
        query = (
            report_snapshot_query(year, month)
            .add_columns(User.full_name)
            .join(User, User.id == ReportSnapshot.approved_by)
            .order_by(ReportingPeriod.year.desc(), ReportingPeriod.month.desc(), ReportSnapshot.version.desc())
            .execution_options(yield_per=500)
        )
        yield _csv_row([
            "report_reference", "year", "month", "version", "approved_at",
            "approved_by", "verified_collections", "approved_expenses",
            "final_result", "distribution_pool", "eligible_shares", "remainder",
        ])
        for snapshot, period, approver_name in db.execute(query):
            totals = snapshot.totals
            yield _csv_row([
                f"RPT-{period.year:04d}{period.month:02d}-V{snapshot.version}",
                period.year,
                period.month,
                snapshot.version,
                snapshot.created_at.isoformat(),
                approver_name,
                totals["verified_collections"]["amount"],
                totals["approved_expenses"]["amount"],
                totals["operating_result"],
                snapshot.pool,
                snapshot.total_shares,
                snapshot.remainder,
            ], {5})


def _download(
    db: Session,
    actor: User,
    kind: str,
    filters: dict,
    content: Iterator[str],
):
    record(
        db, actor, "export.download", "export", kind,
        after={"filters": filters},
    )
    db.commit()
    return StreamingResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'},
    )


@router.get("/exports/bookings.csv")
def export_bookings(
    date_from: date | None = None,
    date_to: date | None = None,
    facility_id: int | None = Query(default=None, gt=0),
    channel: BookingChannel | None = None,
    status: BookingStatus | None = None,
    ref: str | None = Query(default=None, max_length=20),
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    booking_query(date_from, date_to, facility_id, channel, status, ref)
    filters = {
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "facility_id": facility_id,
        "channel": channel.value if channel else None,
        "status": status.value if status else None,
        "ref": ref,
    }
    return _download(
        db, actor, "bookings", filters,
        _bookings_csv(date_from, date_to, facility_id, channel, status, ref),
    )


@router.get("/exports/payments.csv")
def export_payments(
    received_from: date | None = None,
    received_to: date | None = None,
    method: str | None = None,
    status: PaymentStatus | None = None,
    actor: User = Depends(require_permission("payment.record")),
    db: Session = Depends(get_db),
):
    payment_query(received_from, received_to, method, status)
    filters = {
        "received_from": received_from.isoformat() if received_from else None,
        "received_to": received_to.isoformat() if received_to else None,
        "method": method,
        "status": status.value if status else None,
    }
    return _download(
        db, actor, "payments", filters,
        _payments_csv(received_from, received_to, method, status),
    )


@router.get("/exports/expenses.csv")
def export_expenses(
    ref: str | None = Query(default=None, max_length=20),
    date_from: date | None = None,
    date_to: date | None = None,
    amount: Decimal | None = Query(default=None, gt=0),
    category: str | None = Query(default=None, max_length=32),
    vendor: str | None = Query(default=None, max_length=160),
    method: str | None = Query(default=None, max_length=24),
    trx_id: str | None = Query(default=None, max_length=120),
    memo_no: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
    actor: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    expense_query(
        ref, date_from, date_to, amount, category, vendor, method,
        trx_id, memo_no, status,
    )
    filters = {
        "ref": ref,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "amount": str(amount) if amount is not None else None,
        "category": category,
        "vendor": vendor,
        "method": method,
        "trx_id": trx_id,
        "memo_no": memo_no,
        "status": status,
    }
    return _download(
        db, actor, "expenses", filters,
        _expenses_csv(
            ref, date_from, date_to, amount, category, vendor, method,
            trx_id, memo_no, status,
        ),
    )


@router.get("/exports/closings.csv")
def export_closings(
    business_date: date | None = Query(default=None, alias="date"),
    actor: User = Depends(require_permission("closing.view")),
    db: Session = Depends(get_db),
):
    filters = {"date": business_date.isoformat() if business_date else None}
    return _download(db, actor, "closings", filters, _closings_csv(business_date))


@router.get("/exports/reports.csv")
def export_reports(
    year: int | None = Query(default=None, ge=2000, lt=9999),
    month: int | None = Query(default=None, ge=1, le=12),
    actor: User = Depends(require_permission("report.view_full")),
    db: Session = Depends(get_db),
):
    report_snapshot_query(year, month)
    filters = {"year": year, "month": month}
    return _download(db, actor, "reports", filters, _reports_csv(year, month))
