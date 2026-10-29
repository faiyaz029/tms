from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record
from ..db import get_db
from ..models import EmailDelivery, EmailDeliveryStatus, Shareholder, ShareholderStatement, User
from ..permissions import require_permission
from ..services.email import deliver_email

router = APIRouter(tags=["statements and email"])


def _statement_output(statement: ShareholderStatement) -> dict:
    return {
        "id": statement.id,
        "snapshot_id": statement.snapshot_id,
        "generated_at": statement.generated_at.isoformat(),
        "content": statement.content,
    }


@router.get("/statements/mine")
def my_statements(
    actor: User = Depends(require_permission("shareholder.view_self")),
    db: Session = Depends(get_db),
):
    statements = db.scalars(
        select(ShareholderStatement)
        .join(Shareholder, Shareholder.id == ShareholderStatement.shareholder_id)
        .where(Shareholder.user_id == actor.id)
        .order_by(ShareholderStatement.generated_at.desc(), ShareholderStatement.id.desc())
    ).all()
    return {"items": [_statement_output(statement) for statement in statements]}


@router.get("/statements/{statement_id}")
def get_my_statement(
    statement_id: int,
    actor: User = Depends(require_permission("shareholder.view_self")),
    db: Session = Depends(get_db),
):
    statement = db.scalar(
        select(ShareholderStatement)
        .join(Shareholder, Shareholder.id == ShareholderStatement.shareholder_id)
        .where(
            ShareholderStatement.id == statement_id,
            Shareholder.user_id == actor.id,
        )
    )
    if not statement:
        raise HTTPException(404, "Statement not found")
    return _statement_output(statement)


@router.get("/emails")
def list_email_deliveries(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("email.manage")),
    db: Session = Depends(get_db),
):
    query = select(EmailDelivery)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    deliveries = db.scalars(
        query.order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {
        "items": [{
            "id": delivery.id,
            "statement_id": delivery.statement_id,
            "recipient": delivery.recipient,
            "subject": delivery.subject,
            "kind": delivery.kind,
            "status": delivery.status.value,
            "attempts": delivery.attempts,
            "last_error": delivery.last_error,
            "provider_id": delivery.provider_id,
            "created_at": delivery.created_at.isoformat(),
            "updated_at": delivery.updated_at.isoformat(),
        } for delivery in deliveries],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/emails/{delivery_id}/preview")
def preview_email(
    delivery_id: int,
    _: User = Depends(require_permission("email.manage")),
    db: Session = Depends(get_db),
):
    delivery = db.get(EmailDelivery, delivery_id)
    if not delivery or not delivery.html_body:
        raise HTTPException(404, "Rendered email preview not found")
    return Response(
        delivery.html_body,
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/emails/{delivery_id}/retry", status_code=202)
def retry_email(
    delivery_id: int,
    background_tasks: BackgroundTasks,
    actor: User = Depends(require_permission("email.manage")),
    db: Session = Depends(get_db),
):
    delivery = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery_id)
        .with_for_update()
    )
    if not delivery:
        raise HTTPException(404, "Email delivery not found")
    if delivery.status != EmailDeliveryStatus.failed:
        raise HTTPException(409, "Only failed email deliveries can be retried")
    before = {"status": delivery.status.value, "attempts": delivery.attempts}
    delivery.status = EmailDeliveryStatus.pending
    delivery.last_error = None
    record(
        db, actor, "email.retry", "email_delivery", delivery.id,
        before=before,
        after={"status": delivery.status.value, "attempts": delivery.attempts},
    )
    db.commit()
    background_tasks.add_task(deliver_email, delivery.id)
    return {"id": delivery.id, "status": EmailDeliveryStatus.pending.value}
