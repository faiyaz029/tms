from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings
from ..models import (
    Booking, BookingEvent, BookingStatus, DailyClosing, DailyClosingStatus,
    Expense, ExpenseCategory, ExpenseEvent, ExpenseStatus, Payment, PaymentIntent,
    PaymentIntentStatus, PaymentMethod, PaymentStatus, ReferenceCounter, User,
)

UTC = timezone.utc
BUSINESS_TZ = ZoneInfo(settings.business_timezone)
EXPENSE_METHODS = {"cash", "bkash", "bank_transfer", "card", "other"}


def _next_counter(db: Session, name: str, day: date) -> int:
    dialect = db.bind.dialect.name if db.bind else ""
    values = {"name": name, "day": day, "value": 1}
    if dialect == "postgresql":
        statement = pg_insert(ReferenceCounter).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ReferenceCounter.name, ReferenceCounter.day],
            set_={"value": ReferenceCounter.value + 1},
        ).returning(ReferenceCounter.value)
        return int(db.scalar(statement))
    if dialect == "sqlite":
        statement = sqlite_insert(ReferenceCounter).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ReferenceCounter.name, ReferenceCounter.day],
            set_={"value": ReferenceCounter.value + 1},
        ).returning(ReferenceCounter.value)
        return int(db.scalar(statement))

    counter = db.get(ReferenceCounter, (name, day))
    if counter is None:
        db.add(ReferenceCounter(name=name, day=day, value=1))
        db.flush()
        return 1
    counter.value += 1
    db.flush()
    return counter.value


def _next_reference(db: Session, namespace: str, prefix: str, day: date) -> str:
    sequence = _next_counter(db, namespace, day)
    if sequence > 9999:
        raise HTTPException(409, f"{prefix} reference limit reached for the selected day")
    return f"{prefix}-{day:%y%m%d}-{sequence:04d}"


def _category(db: Session, code: str) -> ExpenseCategory:
    category = db.get(ExpenseCategory, code)
    if not category or not category.is_active:
        raise HTTPException(422, "Select an active expense category")
    return category


def _method(db: Session, code: str) -> PaymentMethod:
    method = db.get(PaymentMethod, code)
    if not method or not method.is_active or code not in EXPENSE_METHODS:
        raise HTTPException(422, "Select an active expense payment method")
    return method


def expense_snapshot(expense: Expense) -> dict:
    return {
        "ref": expense.ref,
        "expense_date": expense.expense_date.isoformat(),
        "payment_date": expense.payment_date.isoformat(),
        "category": expense.category,
        "description": expense.description,
        "amount": str(expense.amount),
        "method": expense.method,
        "vendor": expense.vendor,
        "memo_no": expense.memo_no,
        "has_physical_memo": expense.has_physical_memo,
        "trx_id": expense.trx_id,
        "bank_ref": expense.bank_ref,
        "sms_text": expense.sms_text,
        "entered_by": expense.entered_by,
        "status": expense.status.value,
        "approved_by": expense.approved_by,
        "approved_at": expense.approved_at.isoformat() if expense.approved_at else None,
        "rejection_reason": expense.rejection_reason,
        "notes": expense.notes,
    }


def create_expense(
    db: Session,
    actor: User,
    *,
    expense_date: date,
    payment_date: date,
    category: str,
    description: str,
    amount: Decimal,
    method: str,
    vendor: str | None = None,
    memo_no: str | None = None,
    has_physical_memo: bool = False,
    trx_id: str | None = None,
    bank_ref: str | None = None,
    sms_text: str | None = None,
    notes: str | None = None,
) -> Expense:
    _category(db, category)
    _method(db, method)
    if amount <= 0:
        raise HTTPException(422, "Expense amount must be greater than zero")
    reference_day = datetime.now(UTC).astimezone(BUSINESS_TZ).date()
    expense = Expense(
        ref=_next_reference(db, "expense", "EXP", reference_day),
        expense_date=expense_date,
        payment_date=payment_date,
        category=category,
        description=description,
        amount=amount,
        method=method,
        vendor=vendor,
        memo_no=memo_no,
        has_physical_memo=has_physical_memo,
        trx_id=trx_id,
        bank_ref=bank_ref,
        sms_text=sms_text,
        entered_by=actor.id,
        status=ExpenseStatus.pending,
        notes=notes,
    )
    db.add(expense)
    db.flush()
    after = expense_snapshot(expense)
    db.add(ExpenseEvent(
        expense_id=expense.id,
        actor_id=actor.id,
        action="created",
        after=after,
    ))
    record(db, actor, "expense.create", "expense", expense.ref, after=after)
    return expense


def correct_expense(
    db: Session,
    expense: Expense,
    actor: User,
    values: dict,
    reason: str,
) -> Expense:
    before = expense_snapshot(expense)
    for field in ("category", "method"):
        if field in values and values[field] is not None:
            (_category if field == "category" else _method)(db, values[field])
    changed = {
        field: value
        for field, value in values.items()
        if getattr(expense, field) != value
    }
    if not changed:
        raise HTTPException(409, "The correction does not change any expense values")

    for field, value in changed.items():
        setattr(expense, field, value)
    if expense.status != ExpenseStatus.pending:
        expense.status = ExpenseStatus.pending
        expense.approved_by = None
        expense.approved_at = None
        expense.rejection_reason = None
    after = expense_snapshot(expense)
    db.add(ExpenseEvent(
        expense_id=expense.id,
        actor_id=actor.id,
        action="corrected",
        before=before,
        after=after,
        reason=reason,
    ))
    record(
        db, actor, "expense.correct", "expense", expense.ref,
        before=before, after=after, reason=reason,
    )
    db.flush()
    return expense


def approve_expense(db: Session, expense: Expense, actor: User) -> Expense:
    if expense.status != ExpenseStatus.pending:
        raise HTTPException(409, "Only pending expenses can be approved")
    if expense.entered_by == actor.id:
        raise HTTPException(409, "The person who entered an expense cannot approve it")
    before = expense_snapshot(expense)
    expense.status = ExpenseStatus.approved
    expense.approved_by = actor.id
    expense.approved_at = datetime.now(UTC)
    expense.rejection_reason = None
    after = expense_snapshot(expense)
    db.add(ExpenseEvent(
        expense_id=expense.id,
        actor_id=actor.id,
        action="approved",
        before=before,
        after=after,
    ))
    record(db, actor, "expense.approve", "expense", expense.ref, before, after)
    db.flush()
    return expense


def reject_expense(db: Session, expense: Expense, actor: User, reason: str) -> Expense:
    if expense.status != ExpenseStatus.pending:
        raise HTTPException(409, "Only pending expenses can be rejected")
    before = expense_snapshot(expense)
    expense.status = ExpenseStatus.rejected
    expense.rejection_reason = reason
    after = expense_snapshot(expense)
    db.add(ExpenseEvent(
        expense_id=expense.id,
        actor_id=actor.id,
        action="rejected",
        before=before,
        after=after,
        reason=reason,
    ))
    record(db, actor, "expense.reject", "expense", expense.ref, before, after, reason)
    db.flush()
    return expense


def closing_totals(db: Session, business_date: date) -> dict:
    start = datetime.combine(business_date, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)
    end = datetime.combine(
        business_date + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ,
    ).astimezone(UTC)

    booking_created = db.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.created_at >= start,
            Booking.created_at < end,
        )
    ) or 0
    booking_events = db.execute(
        select(BookingEvent.to_status, func.count())
        .where(
            BookingEvent.at >= start,
            BookingEvent.at < end,
            BookingEvent.to_status.in_([BookingStatus.cancelled, BookingStatus.expired]),
        )
        .group_by(BookingEvent.to_status)
    ).all()
    booking_changes = {status: count for status, count in booking_events}

    payment_rows = db.execute(
        select(
            Payment.method,
            Payment.status,
            func.count(),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(
            Payment.received_at >= start,
            Payment.received_at < end,
            Payment.status.in_([PaymentStatus.received, PaymentStatus.verified]),
        )
        .group_by(Payment.method, Payment.status)
    ).all()
    collections_by_method: dict[str, dict[str, str | int]] = {}
    for method, status, count, amount in payment_rows:
        totals = collections_by_method.setdefault(
            method,
            {"count": 0, "received_amount": Decimal("0.00"),
             "verified_amount": Decimal("0.00"), "unverified_amount": Decimal("0.00")},
        )
        totals["count"] += count
        if status == PaymentStatus.verified:
            totals["verified_amount"] += Decimal(amount)
        else:
            totals["unverified_amount"] += Decimal(amount)
    collections_total = {
        "count": sum(int(values["count"]) for values in collections_by_method.values()),
        "received_amount": Decimal("0.00"),
        "verified_amount": Decimal("0.00"),
        "unverified_amount": Decimal("0.00"),
    }
    for values in collections_by_method.values():
        values["received_amount"] = (
            Decimal(values["verified_amount"]) + Decimal(values["unverified_amount"])
        )
        for field in ("received_amount", "verified_amount", "unverified_amount"):
            collections_total[field] += Decimal(values[field])
    collections_by_method = {
        method: {
            **values,
            "received_amount": str(values["received_amount"]),
            "verified_amount": str(values["verified_amount"]),
            "unverified_amount": str(values["unverified_amount"]),
        }
        for method, values in collections_by_method.items()
    }
    collections_total = {
        **collections_total,
        "received_amount": str(collections_total["received_amount"]),
        "verified_amount": str(collections_total["verified_amount"]),
        "unverified_amount": str(collections_total["unverified_amount"]),
    }

    expense_rows = db.execute(
        select(
            Expense.method,
            func.count(),
            func.coalesce(func.sum(Expense.amount), 0),
        )
        .where(
            Expense.payment_date == business_date,
            Expense.status == ExpenseStatus.approved,
        )
        .group_by(Expense.method)
    ).all()
    expenses_by_method = {
        method: {"count": count, "amount": str(Decimal(amount))}
        for method, count, amount in expense_rows
    }
    pending_verification_rows = db.execute(
        select(
            Payment.method,
            func.count(),
            func.coalesce(func.sum(Payment.amount), 0),
        )
        .where(Payment.status == PaymentStatus.received)
        .group_by(Payment.method)
    ).all()
    pending_verifications = {
        "count": sum(count for _, count, _ in pending_verification_rows),
        "amount": str(sum((Decimal(amount) for _, _, amount in pending_verification_rows), Decimal("0.00"))),
        "by_method": {
            method: {"count": count, "amount": str(Decimal(amount))}
            for method, count, amount in pending_verification_rows
        },
    }
    pending_approval_count, pending_approval_amount = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Expense.amount), 0),
        ).where(Expense.status == ExpenseStatus.pending)
    ).one()

    return {
        "business_date": business_date.isoformat(),
        "calculated_at": datetime.now(UTC).isoformat(),
        "bookings": {
            "created": int(booking_created),
            "cancelled": int(booking_changes.get(BookingStatus.cancelled, 0)),
            "expired": int(booking_changes.get(BookingStatus.expired, 0)),
        },
        "collections_by_method": collections_by_method,
        "collections_total": collections_total,
        "expenses_by_method": expenses_by_method,
        "pending_verifications": pending_verifications,
        "pending_approvals": {
            "count": int(pending_approval_count),
            "amount": str(Decimal(pending_approval_amount)),
        },
    }


def submit_closing(
    db: Session,
    business_date: date,
    actor: User,
    notes: str | None,
    difference_notes: str | None,
) -> DailyClosing:
    version = _next_counter(db, "closing", business_date)
    latest = db.scalar(
        select(DailyClosing)
        .where(DailyClosing.business_date == business_date)
        .order_by(DailyClosing.version.desc())
        .limit(1)
        .with_for_update()
    )
    if latest and latest.status == DailyClosingStatus.submitted:
        raise HTTPException(409, "Review the latest closing before submitting a correction version")
    closing = DailyClosing(
        business_date=business_date,
        version=version,
        status=DailyClosingStatus.submitted,
        totals=closing_totals(db, business_date),
        notes=notes,
        difference_notes=difference_notes,
        submitted_by=actor.id,
    )
    db.add(closing)
    db.flush()
    record(
        db, actor, "closing.submit", "daily_closing", closing.id,
        after={
            "business_date": business_date.isoformat(),
            "version": version,
            "status": closing.status.value,
            "totals": closing.totals,
            "notes": notes,
            "difference_notes": difference_notes,
        },
    )
    return closing


def review_closing(
    db: Session,
    closing: DailyClosing,
    actor: User,
    review_notes: str | None,
) -> DailyClosing:
    if closing.status != DailyClosingStatus.submitted:
        raise HTTPException(409, "Only submitted closings can be reviewed")
    latest_id = db.scalar(
        select(DailyClosing.id)
        .where(DailyClosing.business_date == closing.business_date)
        .order_by(DailyClosing.version.desc())
        .limit(1)
    )
    if latest_id != closing.id:
        raise HTTPException(409, "Only the latest closing version can be reviewed")
    closing.status = DailyClosingStatus.reviewed
    closing.reviewed_by = actor.id
    closing.reviewed_at = datetime.now(UTC)
    closing.review_notes = review_notes
    record(
        db, actor, "closing.review", "daily_closing", closing.id,
        before={"status": DailyClosingStatus.submitted.value},
        after={
            "status": closing.status.value,
            "reviewed_at": closing.reviewed_at.isoformat(),
            "review_notes": review_notes,
        },
    )
    db.flush()
    return closing


def _expense_output(expense: Expense, category_label: str) -> dict:
    return {
        **expense_snapshot(expense),
        "id": expense.id,
        "category_label": category_label,
        "created_at": expense.created_at.isoformat(),
    }


def expense_outputs(db: Session, expenses: list[Expense]) -> list[dict]:
    rows = list(expenses)
    if not rows:
        return []
    category_codes = {expense.category for expense in rows}
    categories = {
        category.code: category.label
        for category in db.scalars(
            select(ExpenseCategory).where(ExpenseCategory.code.in_(category_codes))
        )
    }
    return [
        _expense_output(expense, categories.get(expense.category, expense.category))
        for expense in rows
    ]


def expense_output(db: Session, expense: Expense, include_events: bool = False) -> dict:
    category = db.get(ExpenseCategory, expense.category)
    result = _expense_output(
        expense,
        category.label if category else expense.category,
    )
    if include_events:
        events = db.scalars(
            select(ExpenseEvent)
            .where(ExpenseEvent.expense_id == expense.id)
            .order_by(ExpenseEvent.at)
        ).all()
        result["events"] = [{
            "at": event.at.isoformat(),
            "actor_id": event.actor_id,
            "action": event.action,
            "before": event.before,
            "after": event.after,
            "reason": event.reason,
        } for event in events]
    return result


def closing_output(closing: DailyClosing) -> dict:
    return {
        "id": closing.id,
        "business_date": closing.business_date.isoformat(),
        "version": closing.version,
        "status": closing.status.value,
        "totals": closing.totals,
        "notes": closing.notes,
        "difference_notes": closing.difference_notes,
        "submitted_by": closing.submitted_by,
        "submitted_at": closing.submitted_at.isoformat(),
        "reviewed_by": closing.reviewed_by,
        "reviewed_at": closing.reviewed_at.isoformat() if closing.reviewed_at else None,
        "review_notes": closing.review_notes,
    }
