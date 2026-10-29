from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record
from ..db import get_db
from ..models import (
    DailyClosing, Expense, ExpenseCategory, ExpenseEvent, User,
)
from ..permissions import require_permission
from ..schemas import (
    ClosingReviewIn, ClosingSubmitIn, ExpenseCategoryCreateIn,
    ExpenseCategoryUpdateIn, ExpenseCreateIn, ExpenseRejectIn, ExpenseUpdateIn,
)
from ..services.expenses import (
    approve_expense, closing_output, closing_totals, correct_expense,
    create_expense, expense_output, reject_expense, review_closing, submit_closing,
)
from ..services.exports import closing_query, expense_query

router = APIRouter(tags=["expenses and daily closing"])


@router.get("/expense-categories")
def list_categories(
    _: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ExpenseCategory).order_by(ExpenseCategory.label)
    ).all()
    return {"items": [{
        "code": row.code,
        "label": row.label,
        "is_active": row.is_active,
    } for row in rows]}


@router.post("/expense-categories", status_code=201)
def create_category(
    body: ExpenseCategoryCreateIn,
    actor: User = Depends(require_permission("expense.configure")),
    db: Session = Depends(get_db),
):
    if db.get(ExpenseCategory, body.code):
        raise HTTPException(409, "That expense category already exists")
    category = ExpenseCategory(code=body.code, label=body.label, is_active=True)
    db.add(category)
    record(
        db, actor, "expense_category.create", "expense_category", category.code,
        after={"code": category.code, "label": category.label, "is_active": True},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That expense category already exists") from exc
    return {"code": category.code, "label": category.label, "is_active": category.is_active}


@router.patch("/expense-categories/{code}")
def update_category(
    code: str,
    body: ExpenseCategoryUpdateIn,
    actor: User = Depends(require_permission("expense.configure")),
    db: Session = Depends(get_db),
):
    category = db.scalar(
        select(ExpenseCategory).where(ExpenseCategory.code == code).with_for_update()
    )
    if not category:
        raise HTTPException(404, "Expense category not found")
    before = {"code": category.code, "label": category.label, "is_active": category.is_active}
    values = body.model_dump(exclude_unset=True)
    if "label" in values:
        if values["label"] is None:
            raise HTTPException(422, "Category label cannot be cleared")
        category.label = values["label"]
    if "is_active" in values:
        if values["is_active"] is None:
            raise HTTPException(422, "Category active state is required")
        category.is_active = values["is_active"]
    after = {"code": category.code, "label": category.label, "is_active": category.is_active}
    record(
        db, actor, "expense_category.update", "expense_category", category.code,
        before=before, after=after,
    )
    db.commit()
    return after


@router.post("/expenses", status_code=201)
def add_expense(
    body: ExpenseCreateIn,
    actor: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    expense = create_expense(db, actor, **body.model_dump())
    db.commit()
    return expense_output(db, expense, include_events=True)


@router.get("/expenses")
def list_expenses(
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
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    query = expense_query(
        ref, date_from, date_to, amount, category, vendor, method, trx_id, memo_no, status,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    expenses = db.scalars(
        query.order_by(Expense.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {
        "items": [expense_output(db, expense) for expense in expenses],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/expenses/{expense_ref}")
def get_expense(
    expense_ref: str,
    _: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    expense = db.scalar(select(Expense).where(Expense.ref == expense_ref))
    if not expense:
        raise HTTPException(404, "Expense not found")
    return expense_output(db, expense, include_events=True)


@router.patch("/expenses/{expense_id}")
def edit_expense(
    expense_id: int,
    body: ExpenseUpdateIn,
    actor: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id).with_for_update()
    )
    if not expense:
        raise HTTPException(404, "Expense not found")
    values = body.model_dump(exclude_unset=True, exclude={"reason"})
    correct_expense(db, expense, actor, values, body.reason)
    db.commit()
    return expense_output(db, expense, include_events=True)


@router.post("/expenses/{expense_id}/approve")
def approve(
    expense_id: int,
    actor: User = Depends(require_permission("expense.approve")),
    db: Session = Depends(get_db),
):
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id).with_for_update()
    )
    if not expense:
        raise HTTPException(404, "Expense not found")
    approve_expense(db, expense, actor)
    db.commit()
    return expense_output(db, expense, include_events=True)


@router.post("/expenses/{expense_id}/reject")
def reject(
    expense_id: int,
    body: ExpenseRejectIn,
    actor: User = Depends(require_permission("expense.approve")),
    db: Session = Depends(get_db),
):
    expense = db.scalar(
        select(Expense).where(Expense.id == expense_id).with_for_update()
    )
    if not expense:
        raise HTTPException(404, "Expense not found")
    reject_expense(db, expense, actor, body.reason)
    db.commit()
    return expense_output(db, expense, include_events=True)


@router.get("/closings/totals")
def closing_preview(
    business_date: date,
    _: User = Depends(require_permission("closing.view")),
    db: Session = Depends(get_db),
):
    return closing_totals(db, business_date)


@router.post("/closings", status_code=201)
def add_closing(
    body: ClosingSubmitIn,
    actor: User = Depends(require_permission("closing.submit")),
    db: Session = Depends(get_db),
):
    try:
        closing = submit_closing(
            db, body.business_date, actor, body.notes, body.difference_notes,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return closing_output(closing)


@router.get("/closings")
def list_closings(
    business_date: date | None = Query(default=None, alias="date"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("closing.view")),
    db: Session = Depends(get_db),
):
    query = closing_query(business_date)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    closings = db.scalars(
        query.order_by(DailyClosing.business_date.desc(), DailyClosing.version.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {
        "items": [closing_output(closing) for closing in closings],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/closings/{closing_id}")
def get_closing(
    closing_id: int,
    _: User = Depends(require_permission("closing.view")),
    db: Session = Depends(get_db),
):
    closing = db.get(DailyClosing, closing_id)
    if not closing:
        raise HTTPException(404, "Daily closing not found")
    return closing_output(closing)


@router.post("/closings/{closing_id}/review")
def review(
    closing_id: int,
    body: ClosingReviewIn,
    actor: User = Depends(require_permission("closing.review")),
    db: Session = Depends(get_db),
):
    closing = db.scalar(
        select(DailyClosing).where(DailyClosing.id == closing_id).with_for_update()
    )
    if not closing:
        raise HTTPException(404, "Daily closing not found")
    review_closing(db, closing, actor, body.review_notes)
    db.commit()
    return closing_output(closing)


@router.get("/expenses/{expense_id}/events")
def expense_events(
    expense_id: int,
    _: User = Depends(require_permission("expense.enter")),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    events = db.scalars(
        select(ExpenseEvent)
        .where(ExpenseEvent.expense_id == expense_id)
        .order_by(ExpenseEvent.at)
    ).all()
    return {"items": [{
        "at": event.at.isoformat(),
        "actor_id": event.actor_id,
        "action": event.action,
        "before": event.before,
        "after": event.after,
        "reason": event.reason,
    } for event in events]}
