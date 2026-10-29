from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Shareholder, User
from ..permissions import require_permission
from ..schemas import (
    EligibleSharesUpdateIn, ReportApproveIn, ReportChecklistUpdateIn,
    ReportDistributionIn, ReportReviewSubmitIn, ReportReopenIn,
    ShareholderCreateIn, ShareholderUpdateIn, ShareholdingCreateIn,
)
from ..services.email import deliver_report_emails
from ..services.reports import (
    add_shareholding, approve_report, approved_expenses_for_period,
    approved_reports_for_user, create_shareholder, my_shareholding,
    reopen_report, report_detail, set_distribution, shareholder_register,
    shareholder_output, submit_for_review, update_checklist, update_eligible_shares,
    update_shareholder,
)

router = APIRouter(tags=["shareholders and reports"])
T = TypeVar("T")


def _commit(db: Session, operation: Callable[[], T]) -> T:
    try:
        result = operation()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        message = str(exc.orig).lower()
        if "unique" in message or "duplicate key" in message:
            raise HTTPException(
                409, "The shareholder or report record conflicts with existing data"
            ) from exc
        raise


@router.get("/reports/{year}/{month}")
def get_report(
    year: int,
    month: int,
    _: User = Depends(require_permission("report.view_full")),
    db: Session = Depends(get_db),
):
    return report_detail(db, year, month)


@router.post("/reports/{year}/{month}/submit-review")
def submit_report_for_review(
    year: int,
    month: int,
    body: ReportReviewSubmitIn,
    actor: User = Depends(require_permission("report.prepare")),
    db: Session = Depends(get_db),
):
    period = _commit(db, lambda: submit_for_review(db, actor, year, month, body.note))
    return report_detail(db, period.year, period.month)


@router.patch("/reports/{year}/{month}/checklist/{key}")
def change_report_checklist(
    year: int,
    month: int,
    key: str,
    body: ReportChecklistUpdateIn,
    actor: User = Depends(require_permission("report.prepare")),
    db: Session = Depends(get_db),
):
    _commit(
        db,
        lambda: update_checklist(db, actor, year, month, key, body.is_done, body.note),
    )
    return report_detail(db, year, month)


@router.post("/reports/{year}/{month}/eligible-shares")
def confirm_eligible_shares(
    year: int,
    month: int,
    body: EligibleSharesUpdateIn,
    actor: User = Depends(require_permission("report.prepare")),
    db: Session = Depends(get_db),
):
    _commit(
        db,
        lambda: update_eligible_shares(
            db, actor, year, month, body.total_shares, body.reason,
        ),
    )
    return report_detail(db, year, month)


@router.post("/distribution")
def record_distribution(
    body: ReportDistributionIn,
    actor: User = Depends(require_permission("report.prepare")),
    db: Session = Depends(get_db),
):
    _commit(
        db,
        lambda: set_distribution(
            db, actor, body.year, body.month, body.pool_amount, body.reason,
        ),
    )
    return report_detail(db, body.year, body.month)


@router.post("/reports/{year}/{month}/approve")
def approve_monthly_report(
    year: int,
    month: int,
    body: ReportApproveIn,
    background_tasks: BackgroundTasks,
    actor: User = Depends(require_permission("report.approve")),
    db: Session = Depends(get_db),
):
    snapshot = _commit(
        db,
        lambda: approve_report(db, actor, year, month, body.exception_reason),
    )
    background_tasks.add_task(deliver_report_emails, snapshot.id)
    return report_detail(db, year, month)


@router.post("/reports/{year}/{month}/reopen")
def reopen_monthly_report(
    year: int,
    month: int,
    body: ReportReopenIn,
    actor: User = Depends(require_permission("report.approve")),
    db: Session = Depends(get_db),
):
    period = _commit(
        db,
        lambda: reopen_report(db, actor, year, month, body.reason),
    )
    return report_detail(db, period.year, period.month)


@router.get("/reports/approved")
def list_approved_reports(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("report.view_approved")),
    db: Session = Depends(get_db),
):
    return approved_reports_for_user(db, actor, page, size)


@router.get("/reports/approved/{year}/{month}/expenses")
def list_approved_expenses(
    year: int,
    month: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("report.view_approved")),
    db: Session = Depends(get_db),
):
    return approved_expenses_for_period(db, year, month, page, size)


@router.get("/my/shareholding")
def get_my_shareholding(
    actor: User = Depends(require_permission("shareholder.view_self")),
    db: Session = Depends(get_db),
):
    return my_shareholding(db, actor)


@router.get("/shareholders")
def list_shareholders(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("shareholder.manage")),
    db: Session = Depends(get_db),
):
    return shareholder_register(db, page, size)


@router.post("/shareholders", status_code=201)
def add_shareholder(
    body: ShareholderCreateIn,
    actor: User = Depends(require_permission("shareholder.manage")),
    db: Session = Depends(get_db),
):
    holder = _commit(
        db,
        lambda: create_shareholder(
            db, actor, **body.model_dump(),
        ),
    )
    return shareholder_output(db, holder)


@router.patch("/shareholders/{shareholder_id}")
def edit_shareholder(
    shareholder_id: int,
    body: ShareholderUpdateIn,
    actor: User = Depends(require_permission("shareholder.manage")),
    db: Session = Depends(get_db),
):
    holder = db.scalar(
        select(Shareholder)
        .where(Shareholder.id == shareholder_id)
        .with_for_update()
    )
    if not holder:
        raise HTTPException(404, "Shareholder not found")
    updated = _commit(
        db,
        lambda: update_shareholder(
            db,
            holder,
            actor,
            body.model_dump(exclude_unset=True, exclude={"reason"}),
            body.reason,
        ),
    )
    return shareholder_output(db, updated)


@router.post("/shareholders/{shareholder_id}/holdings", status_code=201)
def add_holding(
    shareholder_id: int,
    body: ShareholdingCreateIn,
    actor: User = Depends(require_permission("shareholder.manage")),
    db: Session = Depends(get_db),
):
    holder = db.scalar(
        select(Shareholder)
        .where(Shareholder.id == shareholder_id)
        .with_for_update()
    )
    if not holder:
        raise HTTPException(404, "Shareholder not found")
    holding = _commit(
        db,
        lambda: add_shareholding(
            db, holder, actor, body.shares, body.effective_from, body.reason,
        ),
    )
    return {
        "id": holding.id,
        "shareholder_id": holder.id,
        "shares": holding.shares,
        "effective_from": holding.effective_from.isoformat(),
        "effective_to": holding.effective_to.isoformat() if holding.effective_to else None,
    }
