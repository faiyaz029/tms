from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings
from ..models import (
    DailyClosing, DailyClosingStatus, DistributionDecision, EligibleShareSetting,
    Expense, ExpenseStatus, Payment, PaymentStatus, ReportChecklistItem,
    ReportReopening, ReportSnapshot, ReportingPeriod, ReportingPeriodStatus,
    Shareholder, Shareholding, User,
)

BUSINESS_TZ = ZoneInfo(settings.business_timezone)
UTC = timezone.utc
DEFAULT_ELIGIBLE_SHARES = 50
CHECKLIST = (
    ("payments_verified", "All received payments verified"),
    ("expenses_approved", "No pending expenses"),
    ("closings_reviewed", "Daily closings reviewed"),
    ("register_confirmed", "Shareholder register and total shares confirmed"),
    ("distribution_recorded", "Distribution pool recorded"),
)
CALCULATION_BASIS = (
    "Cash-receipt basis: verified payments are grouped by received time in Asia/Dhaka; "
    "approved expenses are grouped by payment date. Ownership uses holdings effective "
    "on the last day of the report month. Per-share amounts are rounded down to whole paisa."
)
CENT = Decimal("0.01")


def _month_range(year: int, month: int) -> tuple[date, date, datetime, datetime]:
    if year < 2000 or year >= 9999 or not 1 <= month <= 12:
        raise HTTPException(422, "Provide a valid reporting year and month")
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    start = datetime.combine(first, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)
    end = datetime.combine(next_month, time.min, tzinfo=BUSINESS_TZ).astimezone(UTC)
    return first, next_month - timedelta(days=1), start, end


def _checklist_rows(period: ReportingPeriod, db: Session) -> list[ReportChecklistItem]:
    return db.scalars(
        select(ReportChecklistItem)
        .where(
            ReportChecklistItem.reporting_period_id == period.id,
            ReportChecklistItem.version == period.version,
        )
        .order_by(ReportChecklistItem.id)
    ).all()


def _lock_open_reporting_periods(db: Session) -> None:
    db.scalars(
        select(ReportingPeriod.id)
        .where(ReportingPeriod.status != ReportingPeriodStatus.approved)
        .order_by(ReportingPeriod.id)
        .with_for_update()
    ).all()


def _ensure_period(
    db: Session,
    year: int,
    month: int,
    actor: User,
) -> ReportingPeriod:
    _month_range(year, month)
    period = db.scalar(
        select(ReportingPeriod)
        .where(ReportingPeriod.year == year, ReportingPeriod.month == month)
        .with_for_update()
    )
    if period is None:
        period = ReportingPeriod(
            year=year,
            month=month,
            status=ReportingPeriodStatus.preliminary,
            version=1,
        )
        db.add(period)
        db.flush()
        record(
            db, actor, "report.period_create", "reporting_period",
            f"{year:04d}-{month:02d}",
            after={"year": year, "month": month, "version": 1},
        )
    if not _checklist_rows(period, db):
        db.add_all([
            ReportChecklistItem(
                reporting_period_id=period.id,
                version=period.version,
                key=key,
                label=label,
                is_done=False,
            )
            for key, label in CHECKLIST
        ])
    setting = db.get(EligibleShareSetting, (year, month, period.version))
    if setting is None:
        db.add(EligibleShareSetting(
            year=year,
            month=month,
            version=period.version,
            total_shares=DEFAULT_ELIGIBLE_SHARES,
        ))
    db.flush()
    return period


def _period_setting(
    db: Session,
    period: ReportingPeriod | None,
    year: int,
    month: int,
) -> EligibleShareSetting | None:
    if not period:
        return None
    return db.get(EligibleShareSetting, (year, month, period.version))


def _report_calculation(
    db: Session,
    year: int,
    month: int,
    period: ReportingPeriod | None,
    lock_inputs: bool = False,
) -> dict:
    first, last, start, end = _month_range(year, month)
    payment_query = (
        select(Payment)
        .where(Payment.received_at >= start, Payment.received_at < end)
        .order_by(Payment.received_at, Payment.id)
    )
    if lock_inputs:
        payment_query = payment_query.with_for_update()
    payments = db.scalars(payment_query).all()
    verified_by_method: dict[str, dict[str, Decimal | int]] = {}
    payment_status_totals: dict[str, dict[str, dict[str, Decimal | int]]] = {}
    verified_collections = Decimal("0.00")
    unverified_payments = Decimal("0.00")
    payment_inputs = []
    for payment in payments:
        amount = Decimal(payment.amount)
        status_totals = payment_status_totals.setdefault(payment.status.value, {})
        status_method = status_totals.setdefault(
            payment.method, {"count": 0, "amount": Decimal("0.00")}
        )
        status_method["count"] += 1
        status_method["amount"] += amount
        if payment.status == PaymentStatus.verified:
            verified_collections += amount
            method_totals = verified_by_method.setdefault(
                payment.method, {"count": 0, "amount": Decimal("0.00")}
            )
            method_totals["count"] += 1
            method_totals["amount"] += amount
        elif payment.status in (PaymentStatus.received, PaymentStatus.pending):
            unverified_payments += amount
        payment_inputs.append({
            "ref": payment.ref,
            "amount": str(amount),
            "method": payment.method,
            "status": payment.status.value,
            "received_at": (
                (
                    payment.received_at.replace(tzinfo=UTC)
                    if payment.received_at.tzinfo is None
                    else payment.received_at
                ).astimezone(BUSINESS_TZ).isoformat()
                if payment.received_at else None
            ),
        })

    expense_query = (
        select(Expense)
        .where(
            Expense.payment_date >= first,
            Expense.payment_date <= last,
        )
        .order_by(Expense.payment_date, Expense.id)
    )
    if lock_inputs:
        expense_query = expense_query.with_for_update()
    expenses = db.scalars(expense_query).all()
    expense_totals: dict[str, dict[str, Decimal | int]] = {}
    expense_status_totals: dict[str, dict[str, dict[str, Decimal | int]]] = {}
    approved_expenses = Decimal("0.00")
    pending_expenses = Decimal("0.00")
    expense_inputs = []
    for expense in expenses:
        amount = Decimal(expense.amount)
        status = expense.status.value
        status_totals = expense_status_totals.setdefault(status, {})
        status_method = status_totals.setdefault(
            expense.method, {"count": 0, "amount": Decimal("0.00")}
        )
        status_method["count"] += 1
        status_method["amount"] += amount
        if expense.status == ExpenseStatus.approved:
            approved_expenses += amount
            method_totals = expense_totals.setdefault(
                expense.method, {"count": 0, "amount": Decimal("0.00")}
            )
            method_totals["count"] += 1
            method_totals["amount"] += amount
        elif expense.status == ExpenseStatus.pending:
            pending_expenses += amount
        expense_inputs.append({
            "ref": expense.ref,
            "payment_date": expense.payment_date.isoformat(),
            "category": expense.category,
            "description": expense.description,
            "amount": str(amount),
            "method": expense.method,
            "status": status,
        })

    closing_query = select(DailyClosing).where(
        DailyClosing.business_date >= first,
        DailyClosing.business_date <= last,
    )
    if lock_inputs:
        closing_query = closing_query.with_for_update()
    closings = db.scalars(closing_query).all()
    unresolved_closings = [
        {"business_date": closing.business_date.isoformat(), "version": closing.version}
        for closing in closings if closing.status == DailyClosingStatus.submitted
    ]
    setting = _period_setting(db, period, year, month)
    total_shares = setting.total_shares if setting else DEFAULT_ELIGIBLE_SHARES
    holding_query = (
        select(Shareholder, Shareholding)
        .join(Shareholding, Shareholding.shareholder_id == Shareholder.id)
        .where(
            Shareholding.effective_from <= last,
            or_(Shareholding.effective_to.is_(None), Shareholding.effective_to >= last),
        )
        .order_by(Shareholder.name, Shareholder.id)
    )
    if lock_inputs:
        holding_query = holding_query.with_for_update(of=Shareholding)
    month_end_holdings = db.execute(holding_query).all()
    shareholder_rows = [{
        "shareholder_id": shareholder.id,
        "name": shareholder.name,
        "shares": holding.shares,
    } for shareholder, holding in month_end_holdings]
    allocated_shares = sum(row["shares"] for row in shareholder_rows)
    decision = db.scalar(
        select(DistributionDecision).where(
            DistributionDecision.reporting_period_id == period.id,
            DistributionDecision.version == period.version,
        )
    ) if period else None
    pool = Decimal(decision.pool_amount) if decision else None
    retained = Decimal(decision.retained_amount) if decision else None
    per_share = (pool / Decimal(total_shares)).quantize(CENT, rounding=ROUND_DOWN) if pool is not None else None
    allocations = []
    distributed = Decimal("0.00")
    if per_share is not None:
        for holder in shareholder_rows:
            amount = per_share * holder["shares"]
            distributed += amount
            allocations.append({**holder, "amount": str(amount)})
    remainder = pool - distributed if pool is not None else None
    operating_result = verified_collections - approved_expenses
    amount_by_status_method = lambda rows: {
        status: {
            method: {
                "count": int(values["count"]),
                "amount": str(values["amount"]),
            }
            for method, values in methods.items()
        }
        for status, methods in rows.items()
    }
    return {
        "calculation_basis": CALCULATION_BASIS,
        "inputs": {
            "period_start": first.isoformat(),
            "period_end": last.isoformat(),
            "collections_basis": "Payment received_at in Asia/Dhaka",
            "expense_basis": "Expense payment_date",
            "ownership_effective_date": last.isoformat(),
            "payments": payment_inputs,
            "expenses": expense_inputs,
            "shareholders": shareholder_rows,
            "eligible_share_confirmation": {
                "total_shares": total_shares,
                "confirmed_by": setting.confirmed_by,
                "confirmed_at": setting.confirmed_at.isoformat() if setting and setting.confirmed_at else None,
                "reason": setting.reason,
            } if setting else {"total_shares": total_shares, "confirmed_by": None},
            "distribution_decision": {
                "pool_amount": str(decision.pool_amount),
                "retained_amount": str(decision.retained_amount),
                "reason": decision.reason,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at.isoformat(),
            } if decision else None,
        },
        "totals": {
            "verified_collections": {
                "amount": str(verified_collections),
                "by_method": {
                    method: {
                        "count": int(values["count"]),
                        "amount": str(values["amount"]),
                    }
                    for method, values in verified_by_method.items()
                },
            },
            "payments_by_status": amount_by_status_method(payment_status_totals),
            "unverified_payments": {
                "amount": str(unverified_payments),
                "count": sum(
                    int(values["count"])
                    for status in ("received", "pending")
                    for values in payment_status_totals.get(status, {}).values()
                ),
            },
            "approved_expenses": {
                "amount": str(approved_expenses),
                "by_method": {
                    method: {"count": int(values["count"]), "amount": str(values["amount"])}
                    for method, values in expense_totals.items()
                },
            },
            "expenses_by_status": amount_by_status_method(expense_status_totals),
            "pending_expenses": {
                "amount": str(pending_expenses),
                "count": sum(
                    int(values["count"])
                    for values in expense_status_totals.get("pending", {}).values()
                ),
            },
            "operating_result": str(operating_result),
            "eligible_shares": total_shares,
            "shareholder_shares_allocated": allocated_shares,
            "allocation_error": allocated_shares > total_shares,
            "per_share": str(per_share) if per_share is not None else None,
            "pool": str(pool) if pool is not None else None,
            "retained_amount": str(retained) if retained is not None else None,
            "remainder": str(remainder) if remainder is not None else None,
        },
        "allocations": allocations,
        "decision": {
            "pool_amount": str(decision.pool_amount),
            "retained_amount": str(decision.retained_amount),
            "reason": decision.reason,
            "decided_by": decision.decided_by,
            "decided_at": decision.decided_at.isoformat(),
        } if decision else None,
        "unresolved": {
            "received_payments": sum(
                int(values["count"])
                for status in ("received", "pending")
                for values in payment_status_totals.get(status, {}).values()
            ),
            "pending_expenses": sum(
                int(values["count"])
                for values in expense_status_totals.get("pending", {}).values()
            ),
            "daily_closings": unresolved_closings,
            "register_confirmed": bool(setting and setting.confirmed_by),
        },
    }


def _snapshot_output(db: Session, snapshot: ReportSnapshot) -> dict:
    approver = db.get(User, snapshot.approved_by)
    return {
        "id": snapshot.id,
        "version": snapshot.version,
        "created_at": snapshot.created_at.isoformat(),
        "approved_by": snapshot.approved_by,
        "approver_name": approver.full_name if approver else "Unknown",
        "calculation_basis": snapshot.calculation_basis,
        "inputs": snapshot.inputs,
        "totals": snapshot.totals,
        "allocations": snapshot.allocations,
        "total_shares": snapshot.total_shares,
        "pool": str(snapshot.pool),
        "remainder": str(snapshot.remainder),
        "exception_reason": snapshot.exception_reason,
    }


def report_detail(db: Session, year: int, month: int) -> dict:
    _month_range(year, month)
    period = db.scalar(
        select(ReportingPeriod).where(
            ReportingPeriod.year == year,
            ReportingPeriod.month == month,
        )
    )
    version = period.version if period else 1
    status = period.status if period else ReportingPeriodStatus.preliminary
    snapshots = db.scalars(
        select(ReportSnapshot)
        .where(ReportSnapshot.reporting_period_id == period.id)
        .order_by(ReportSnapshot.version.desc())
    ).all() if period else []
    current_snapshot = next(
        (snapshot for snapshot in snapshots if snapshot.version == version), None
    )
    if current_snapshot:
        calculation = {
            "calculation_basis": current_snapshot.calculation_basis,
            "inputs": current_snapshot.inputs,
            "totals": current_snapshot.totals,
            "allocations": current_snapshot.allocations,
            "decision": None,
        }
        decision = db.scalar(
            select(DistributionDecision).where(
                DistributionDecision.reporting_period_id == period.id,
                DistributionDecision.version == version,
            )
        )
        if decision:
            calculation["decision"] = {
                "pool_amount": str(decision.pool_amount),
                "retained_amount": str(decision.retained_amount),
                "reason": decision.reason,
                "decided_by": decision.decided_by,
                "decided_at": decision.decided_at.isoformat(),
            }
    else:
        calculation = _report_calculation(db, year, month, period)
    checklist = [{
        "key": item.key,
        "label": item.label,
        "is_done": item.is_done,
        "done_by": item.done_by,
        "done_at": item.done_at.isoformat() if item.done_at else None,
        "note": item.note,
    } for item in _checklist_rows(period, db)] if period else [
        {"key": key, "label": label, "is_done": False, "done_by": None,
         "done_at": None, "note": None}
        for key, label in CHECKLIST
    ]
    if current_snapshot:
        totals = calculation["totals"]
        unresolved = {
            "received_payments": 0,
            "pending_expenses": 0,
            "daily_closings": [],
            "register_confirmed": True,
        }
    else:
        totals = calculation["totals"]
        unresolved = calculation["unresolved"]
    history = [_snapshot_output(db, snapshot) for snapshot in snapshots]
    reopenings = db.scalars(
        select(ReportReopening)
        .where(ReportReopening.reporting_period_id == period.id)
        .order_by(ReportReopening.new_version.desc())
    ).all() if period else []
    return {
        "year": year,
        "month": month,
        "status": status.value,
        "stage": {
            ReportingPeriodStatus.preliminary: "Preliminary: Not Yet Reviewed",
            ReportingPeriodStatus.under_review: "Under Review",
            ReportingPeriodStatus.approved: "Approved / Final",
            ReportingPeriodStatus.reopened: "Preliminary: Reopened",
        }[status],
        "version": version,
        "review_note": period.review_note if period else None,
        "calculation_basis": calculation["calculation_basis"],
        "inputs": calculation["inputs"],
        "totals": totals,
        "allocations": calculation["allocations"],
        "checklist": checklist,
        "distribution": calculation["decision"],
        "unresolved": unresolved,
        "history": history,
        "reopenings": [{
            "previous_version": row.previous_version,
            "new_version": row.new_version,
            "previous_snapshot_id": row.previous_snapshot_id,
            "reason": row.reason,
            "authorized_by": row.authorized_by,
            "at": row.at.isoformat(),
        } for row in reopenings],
    }


def _reset_register_checklists(db: Session) -> None:
    rows = db.scalars(
        select(ReportChecklistItem)
        .join(ReportingPeriod, ReportingPeriod.id == ReportChecklistItem.reporting_period_id)
        .where(
            ReportChecklistItem.key == "register_confirmed",
            ReportChecklistItem.is_done.is_(True),
            ReportingPeriod.status != ReportingPeriodStatus.approved,
            ReportChecklistItem.version == ReportingPeriod.version,
        )
    ).all()
    for item in rows:
        item.is_done = False
        item.done_by = None
        item.done_at = None
        item.note = None


def create_shareholder(
    db: Session,
    actor: User,
    *,
    name: str,
    email: str,
    user_id: int | None,
    notes: str | None,
    acquisition_amount: Decimal | None,
    shares: int,
    effective_from: date,
    reason: str,
) -> Shareholder:
    _lock_open_reporting_periods(db)
    if user_id is not None:
        user = db.get(User, user_id)
        if not user or user.role.value != "shareholder":
            raise HTTPException(422, "Link only an existing shareholder account")
    holder = Shareholder(
        name=name,
        email=email.strip().lower(),
        user_id=user_id,
        notes=notes,
        acquisition_amount=acquisition_amount,
        is_active=True,
    )
    db.add(holder)
    db.flush()
    holding = Shareholding(
        shareholder_id=holder.id,
        shares=shares,
        effective_from=effective_from,
    )
    db.add(holding)
    _reset_register_checklists(db)
    record(
        db, actor, "shareholder.create", "shareholder", holder.id,
        after={
            "name": holder.name, "email": holder.email, "user_id": holder.user_id,
            "shares": shares, "effective_from": effective_from.isoformat(),
        },
        reason=reason,
    )
    db.flush()
    return holder


def update_shareholder(
    db: Session,
    holder: Shareholder,
    actor: User,
    values: dict,
    reason: str,
) -> Shareholder:
    _lock_open_reporting_periods(db)
    before = {
        "name": holder.name, "email": holder.email, "user_id": holder.user_id,
        "is_active": holder.is_active, "notes": holder.notes,
        "acquisition_amount": str(holder.acquisition_amount) if holder.acquisition_amount is not None else None,
    }
    if values.get("user_id") is not None:
        user = db.get(User, values["user_id"])
        if not user or user.role.value != "shareholder":
            raise HTTPException(422, "Link only an existing shareholder account")
    for field, value in values.items():
        if field != "reason":
            if field == "email" and value is not None:
                value = value.strip().lower()
            setattr(holder, field, value)
    after = {
        "name": holder.name, "email": holder.email, "user_id": holder.user_id,
        "is_active": holder.is_active, "notes": holder.notes,
        "acquisition_amount": str(holder.acquisition_amount) if holder.acquisition_amount is not None else None,
    }
    _reset_register_checklists(db)
    record(
        db, actor, "shareholder.update", "shareholder", holder.id,
        before=before, after=after, reason=reason,
    )
    db.flush()
    return holder


def add_shareholding(
    db: Session,
    holder: Shareholder,
    actor: User,
    shares: int,
    effective_from: date,
    reason: str,
) -> Shareholding:
    _lock_open_reporting_periods(db)
    existing = db.scalars(
        select(Shareholding)
        .where(Shareholding.shareholder_id == holder.id)
        .order_by(Shareholding.effective_from)
        .with_for_update()
    ).all()
    if any(row.effective_from == effective_from for row in existing):
        raise HTTPException(409, "A shareholding already starts on this date")
    future = [row for row in existing if row.effective_from > effective_from]
    if future:
        raise HTTPException(409, "Shareholding changes must be entered in chronological order")
    previous = next(
        (
            row for row in reversed(existing)
            if row.effective_from < effective_from
            and (row.effective_to is None or row.effective_to >= effective_from)
        ),
        None,
    )
    if previous:
        previous_before = {
            "shares": previous.shares,
            "effective_from": previous.effective_from.isoformat(),
            "effective_to": previous.effective_to.isoformat() if previous.effective_to else None,
        }
        previous.effective_to = effective_from - timedelta(days=1)
        record(
            db, actor, "shareholding.close", "shareholding", previous.id,
            before=previous_before,
            after={**previous_before, "effective_to": previous.effective_to.isoformat()},
            reason=reason,
        )
    holding = Shareholding(
        shareholder_id=holder.id,
        shares=shares,
        effective_from=effective_from,
    )
    db.add(holding)
    db.flush()
    _reset_register_checklists(db)
    record(
        db, actor, "shareholding.create", "shareholder", holder.id,
        after={
            "shares": shares,
            "effective_from": effective_from.isoformat(),
            "previous_shareholding_id": previous.id if previous else None,
        },
        reason=reason,
    )
    return holding


def update_eligible_shares(
    db: Session,
    actor: User,
    year: int,
    month: int,
    total_shares: int,
    reason: str,
) -> EligibleShareSetting:
    period = _ensure_period(db, year, month, actor)
    setting = db.get(EligibleShareSetting, (year, month, period.version))
    previous = setting.total_shares
    setting.total_shares = total_shares
    setting.confirmed_by = actor.id
    setting.confirmed_at = datetime.now(UTC)
    setting.reason = reason
    item = db.scalar(
        select(ReportChecklistItem).where(
            ReportChecklistItem.reporting_period_id == period.id,
            ReportChecklistItem.version == period.version,
            ReportChecklistItem.key == "register_confirmed",
        )
    )
    item.is_done = True
    item.done_by = actor.id
    item.done_at = setting.confirmed_at
    item.note = reason
    record(
        db, actor, "report.eligible_shares", "eligible_share_setting",
        f"{year:04d}-{month:02d}-v{period.version}",
        before={"total_shares": previous},
        after={"total_shares": total_shares, "confirmed_by": actor.id},
        reason=reason,
    )
    return setting


def update_checklist(
    db: Session,
    actor: User,
    year: int,
    month: int,
    key: str,
    is_done: bool,
    note: str | None,
) -> ReportChecklistItem:
    period = _ensure_period(db, year, month, actor)
    if period.status == ReportingPeriodStatus.approved:
        raise HTTPException(409, "An approved report must be reopened before changing its checklist")
    item = db.scalar(
        select(ReportChecklistItem).where(
            ReportChecklistItem.reporting_period_id == period.id,
            ReportChecklistItem.version == period.version,
            ReportChecklistItem.key == key,
        )
    )
    if not item:
        raise HTTPException(404, "Report checklist item not found")
    before = {"is_done": item.is_done, "note": item.note}
    item.is_done = is_done
    item.done_by = actor.id if is_done else None
    item.done_at = datetime.now(UTC) if is_done else None
    item.note = note.strip() if note and note.strip() else None
    record(
        db, actor, "report.checklist_update", "report_checklist_item", item.id,
        before=before,
        after={"is_done": item.is_done, "note": item.note},
        reason=item.note,
    )
    return item


def set_distribution(
    db: Session,
    actor: User,
    year: int,
    month: int,
    pool_amount: Decimal,
    reason: str,
) -> DistributionDecision:
    period = _ensure_period(db, year, month, actor)
    if period.status == ReportingPeriodStatus.approved:
        raise HTTPException(409, "An approved report must be reopened before changing its distribution")
    totals = _report_calculation(db, year, month, period)["totals"]
    retained = Decimal(totals["operating_result"]) - pool_amount
    decision = db.scalar(
        select(DistributionDecision)
        .where(
            DistributionDecision.reporting_period_id == period.id,
            DistributionDecision.version == period.version,
        )
        .with_for_update()
    )
    before = None
    if decision:
        before = {
            "pool_amount": str(decision.pool_amount),
            "retained_amount": str(decision.retained_amount),
            "reason": decision.reason,
        }
        decision.pool_amount = pool_amount
        decision.retained_amount = retained
        decision.reason = reason
        decision.decided_by = actor.id
        decision.decided_at = datetime.now(UTC)
    else:
        decision = DistributionDecision(
            reporting_period_id=period.id,
            version=period.version,
            pool_amount=pool_amount,
            retained_amount=retained,
            reason=reason,
            decided_by=actor.id,
        )
        db.add(decision)
        db.flush()
    item = db.scalar(
        select(ReportChecklistItem).where(
            ReportChecklistItem.reporting_period_id == period.id,
            ReportChecklistItem.version == period.version,
            ReportChecklistItem.key == "distribution_recorded",
        )
    )
    item.is_done = True
    item.done_by = actor.id
    item.done_at = decision.decided_at
    item.note = reason
    record(
        db, actor, "report.distribution", "distribution_decision", decision.id,
        before=before,
        after={
            "pool_amount": str(decision.pool_amount),
            "retained_amount": str(decision.retained_amount),
            "reason": decision.reason,
        },
        reason=reason,
    )
    return decision


def submit_for_review(
    db: Session,
    actor: User,
    year: int,
    month: int,
    note: str | None,
) -> ReportingPeriod:
    period = _ensure_period(db, year, month, actor)
    if period.status not in (
        ReportingPeriodStatus.preliminary, ReportingPeriodStatus.reopened,
    ):
        raise HTTPException(409, "Only a preliminary or reopened report can be submitted for review")
    before = {"status": period.status.value, "version": period.version}
    period.status = ReportingPeriodStatus.under_review
    period.review_note = note.strip() if note and note.strip() else None
    record(
        db, actor, "report.submit_review", "reporting_period",
        f"{year:04d}-{month:02d}",
        before=before,
        after={
            "status": period.status.value,
            "version": period.version,
            "review_note": period.review_note,
        },
    )
    return period


def approve_report(
    db: Session,
    actor: User,
    year: int,
    month: int,
    exception_reason: str | None,
) -> ReportSnapshot:
    period = db.scalar(
        select(ReportingPeriod)
        .where(ReportingPeriod.year == year, ReportingPeriod.month == month)
        .with_for_update()
    )
    if not period:
        raise HTTPException(404, "Report period not found")
    if period.status != ReportingPeriodStatus.under_review:
        raise HTTPException(409, "Only a report under review can be approved")
    calculation = _report_calculation(db, year, month, period, lock_inputs=True)
    decision = calculation["decision"]
    if not decision:
        raise HTTPException(409, "Record the distribution pool before approving this report")
    if calculation["totals"]["allocation_error"]:
        raise HTTPException(409, "Allocated shareholder shares exceed total eligible shares")
    if not calculation["allocations"]:
        raise HTTPException(409, "Add at least one shareholder holding before approving the report")
    checklist = _checklist_rows(period, db)
    incomplete = [item.label for item in checklist if not item.is_done]
    unresolved = calculation["unresolved"]
    if unresolved["received_payments"]:
        incomplete.append("Received payments awaiting verification")
    if unresolved["pending_expenses"]:
        incomplete.append("Pending expenses")
    if unresolved["daily_closings"]:
        incomplete.append("Submitted daily closings awaiting review")
    if not unresolved["register_confirmed"]:
        incomplete.append("Eligible share count has not been confirmed")
    if incomplete and not exception_reason:
        raise HTTPException(
            409,
            "Resolve the report checklist before approval or provide an owner exception: "
            + "; ".join(incomplete),
        )
    setting = _period_setting(db, period, year, month)
    if not setting:
        raise HTTPException(409, "Confirm the total eligible share count before approval")
    totals = calculation["totals"]
    snapshot_inputs = {
        **calculation["inputs"],
        "checklist": [{
            "key": item.key,
            "label": item.label,
            "is_done": item.is_done,
            "done_by": item.done_by,
            "done_at": item.done_at.isoformat() if item.done_at else None,
            "note": item.note,
        } for item in checklist],
        "unresolved_items": incomplete,
    }
    snapshot = ReportSnapshot(
        reporting_period_id=period.id,
        version=period.version,
        approved_by=actor.id,
        calculation_basis=calculation["calculation_basis"],
        inputs=snapshot_inputs,
        totals=totals,
        allocations=calculation["allocations"],
        total_shares=setting.total_shares,
        pool=Decimal(decision["pool_amount"]),
        remainder=Decimal(totals["remainder"]),
        exception_reason=exception_reason,
    )
    period.status = ReportingPeriodStatus.approved
    db.add(snapshot)
    db.flush()
    record(
        db, actor, "report.approve", "report_snapshot", snapshot.id,
        after={
            "period": f"{year:04d}-{month:02d}",
            "version": snapshot.version,
            "totals": snapshot.totals,
            "allocations": snapshot.allocations,
            "pool": str(snapshot.pool),
            "remainder": str(snapshot.remainder),
            "exception_reason": exception_reason,
        },
        reason=exception_reason,
    )
    return snapshot


def reopen_report(
    db: Session,
    actor: User,
    year: int,
    month: int,
    reason: str,
) -> ReportingPeriod:
    period = db.scalar(
        select(ReportingPeriod)
        .where(ReportingPeriod.year == year, ReportingPeriod.month == month)
        .with_for_update()
    )
    if not period or period.status != ReportingPeriodStatus.approved:
        raise HTTPException(409, "Only an approved report can be reopened")
    previous = db.scalar(
        select(ReportSnapshot)
        .where(
            ReportSnapshot.reporting_period_id == period.id,
            ReportSnapshot.version == period.version,
        )
    )
    if not previous:
        raise HTTPException(409, "Approved snapshot is missing")
    previous_version = period.version
    period.version += 1
    period.status = ReportingPeriodStatus.reopened
    period.review_note = None
    db.add(ReportReopening(
        reporting_period_id=period.id,
        previous_snapshot_id=previous.id,
        previous_version=previous_version,
        new_version=period.version,
        reason=reason,
        authorized_by=actor.id,
    ))
    prior_setting = _period_setting(db, period, year, month)
    db.add(EligibleShareSetting(
        year=year,
        month=month,
        version=period.version,
        total_shares=prior_setting.total_shares if prior_setting else DEFAULT_ELIGIBLE_SHARES,
        reason=f"Reopened: {reason}",
    ))
    db.add_all([
        ReportChecklistItem(
            reporting_period_id=period.id,
            version=period.version,
            key=key,
            label=label,
            is_done=False,
        )
        for key, label in CHECKLIST
    ])
    record(
        db, actor, "report.reopen", "reporting_period",
        f"{year:04d}-{month:02d}",
        before={"status": "approved", "version": previous_version, "snapshot_id": previous.id},
        after={"status": "reopened", "version": period.version},
        reason=reason,
    )
    db.flush()
    return period


def shareholder_register(db: Session) -> list[dict]:
    holders = db.scalars(select(Shareholder).order_by(Shareholder.name, Shareholder.id)).all()
    output = []
    for holder in holders:
        holdings = db.scalars(
            select(Shareholding)
            .where(Shareholding.shareholder_id == holder.id)
            .order_by(Shareholding.effective_from.desc())
        ).all()
        linked_user = db.get(User, holder.user_id) if holder.user_id else None
        output.append({
            "id": holder.id,
            "name": holder.name,
            "email": holder.email,
            "user_id": holder.user_id,
            "linked_user_name": linked_user.full_name if linked_user else None,
            "is_active": holder.is_active,
            "notes": holder.notes,
            "acquisition_amount": str(holder.acquisition_amount) if holder.acquisition_amount is not None else None,
            "holdings": [{
                "id": row.id,
                "shares": row.shares,
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
            } for row in holdings],
        })
    return output


def my_shareholding(db: Session, user: User) -> dict:
    holder = db.scalar(select(Shareholder).where(Shareholder.user_id == user.id))
    if not holder:
        raise HTTPException(404, "No shareholder register entry is linked to this account")
    holdings = db.scalars(
        select(Shareholding)
        .where(Shareholding.shareholder_id == holder.id)
        .order_by(Shareholding.effective_from.desc())
    ).all()
    today = datetime.now(UTC).astimezone(BUSINESS_TZ).date()
    current = next(
        (
            row for row in holdings
            if row.effective_from <= today
            and (row.effective_to is None or row.effective_to >= today)
        ),
        None,
    )
    return {
        "name": holder.name,
        "is_active": holder.is_active,
        "current_shares": current.shares if current else 0,
        "holdings": [{
            "shares": row.shares,
            "effective_from": row.effective_from.isoformat(),
            "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        } for row in holdings],
    }


def approved_reports_for_user(db: Session, user: User) -> list[dict]:
    holder = db.scalar(select(Shareholder).where(Shareholder.user_id == user.id)) if user.role.value == "shareholder" else None
    if user.role.value == "shareholder" and not holder:
        raise HTTPException(404, "No shareholder register entry is linked to this account")
    snapshots = db.execute(
        select(ReportSnapshot, ReportingPeriod)
        .join(ReportingPeriod, ReportingPeriod.id == ReportSnapshot.reporting_period_id)
        .order_by(ReportingPeriod.year.desc(), ReportingPeriod.month.desc(), ReportSnapshot.version.desc())
    ).all()
    seen_periods: set[int] = set()
    output = []
    for snapshot, period in snapshots:
        if period.id in seen_periods:
            continue
        seen_periods.add(period.id)
        row = _snapshot_output(db, snapshot)
        row.update({
            "year": period.year,
            "month": period.month,
            "status": "approved" if (
                period.status == ReportingPeriodStatus.approved
                and snapshot.version == period.version
            ) else "previously_approved",
            "period_status": period.status.value,
        })
        if holder:
            own = next(
                (
                    allocation for allocation in snapshot.allocations
                    if allocation["shareholder_id"] == holder.id
                ),
                None,
            )
            row.pop("inputs", None)
            row.pop("allocations", None)
            row["my_allocation"] = own
        output.append(row)
    return output


def approved_expenses_for_period(db: Session, year: int, month: int) -> list[dict]:
    period = db.scalar(
        select(ReportingPeriod).where(
            ReportingPeriod.year == year,
            ReportingPeriod.month == month,
        )
    )
    if not period:
        raise HTTPException(404, "No approved report exists for this period")
    snapshot = db.scalar(
        select(ReportSnapshot)
        .where(ReportSnapshot.reporting_period_id == period.id)
        .order_by(ReportSnapshot.version.desc())
        .limit(1)
    )
    if not snapshot:
        raise HTTPException(404, "No approved report exists for this period")
    return [
        expense for expense in snapshot.inputs.get("expenses", [])
        if expense["status"] == ExpenseStatus.approved.value
    ]
