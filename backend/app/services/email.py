import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import db as database
from ..config import settings
from ..email import get_email_backend
from ..models import (
    EmailDelivery,
    EmailDeliveryStatus,
    BusinessSetting,
    PasswordResetRateBucket,
    PasswordResetToken,
    ReportSnapshot,
    Shareholder,
    ShareholderStatement,
    User,
    utcnow,
)

RESET_WINDOW_SECONDS = 15 * 60
RESET_MAX_REQUESTS = 5
RESET_TOKEN_MINUTES = 30


def statement_content(
    snapshot: ReportSnapshot,
    shareholder: Shareholder,
    business_name: str,
) -> dict:
    allocation = next(
        (
            row for row in snapshot.allocations
            if row["shareholder_id"] == shareholder.id
        ),
        None,
    )
    totals = snapshot.totals
    decision = snapshot.inputs["distribution_decision"]
    period = snapshot.inputs
    return {
        "business_name": business_name,
        "period": f"{period['period_start'][:7]}",
        "approved_at": snapshot.created_at.isoformat(),
        "report_reference": f"RPT-{period['period_start'][:7].replace('-', '')}-V{snapshot.version}",
        "calculation_basis": snapshot.calculation_basis,
        "collections": totals["verified_collections"]["amount"],
        "approved_expenses": totals["approved_expenses"]["amount"],
        "final_result": totals["operating_result"],
        "distribution_pool": str(snapshot.pool),
        "total_eligible_shares": snapshot.total_shares,
        "per_share": totals["per_share"],
        "shareholder_name": shareholder.name,
        "shareholder_shares": allocation["shares"] if allocation else 0,
        "calculated_allocation": allocation["amount"] if allocation else "0.00",
        "retained_amount": decision["retained_amount"],
        "payout_status": "calculated",
        "payout_note": "A calculated allocation is not confirmation of payment.",
        "approved_expense_items": [{
            "ref": row["ref"],
            "payment_date": row["payment_date"],
            "category": row["category"],
            "description": row["description"],
            "amount": row["amount"],
            "method": row["method"],
        } for row in period["expenses"] if row["status"] == "approved"],
        "exception_reason": snapshot.exception_reason,
    }


def create_statements(db: Session, snapshot: ReportSnapshot) -> list[ShareholderStatement]:
    shareholder_ids = {
        row["shareholder_id"] for row in snapshot.allocations
    }
    if not shareholder_ids:
        return []
    shareholders = db.scalars(
        select(Shareholder).where(Shareholder.id.in_(shareholder_ids))
    ).all()
    business_name = BusinessSetting.get(db, "business_name", settings.business_name)
    statements = []
    for shareholder in shareholders:
        content = statement_content(snapshot, shareholder, business_name or settings.business_name)
        statement = ShareholderStatement(
            snapshot_id=snapshot.id,
            shareholder_id=shareholder.id,
            content=content,
        )
        db.add(statement)
        db.flush()
        db.add(EmailDelivery(
            statement_id=statement.id,
            recipient=shareholder.email,
            subject=f"Your shareholder statement · {content['report_reference']}",
            kind="shareholder_statement",
            status=EmailDeliveryStatus.pending,
            html_body=render_statement(content),
        ))
        statements.append(statement)
    return statements


def render_statement(content: dict) -> str:
    fields = (
        ("Collections", content["collections"]),
        ("Approved expenses", content["approved_expenses"]),
        ("Final result", content["final_result"]),
        ("Distribution pool", content["distribution_pool"]),
        ("Eligible shares", content["total_eligible_shares"]),
        ("Amount per share", content["per_share"]),
        ("Your shares", content["shareholder_shares"]),
        ("Your calculated allocation", content["calculated_allocation"]),
        ("Retained amount", content["retained_amount"]),
        ("Payout status", content["payout_status"]),
    )
    rows = "".join(
        f"<tr><th align='left'>{escape(str(label))}</th>"
        f"<td>{escape(str(value if value is not None else '—'))}</td></tr>"
        for label, value in fields
    )
    name = escape(str(content["shareholder_name"]))
    business = escape(str(content["business_name"]))
    ref = escape(str(content["report_reference"]))
    note = escape(str(content["payout_note"]))
    return (
        "<!doctype html><html><body>"
        f"<h1>{business}</h1><h2>Shareholder statement · {ref}</h2>"
        f"<p>Prepared for {name} · period {escape(str(content['period']))}</p>"
        f"<table>{rows}</table><p>{note}</p>"
        "<p>Management information only; this is not a promise of dividends or proof of payment.</p>"
        "</body></html>"
    )


def deliver_with_session(db: Session, delivery_id: int) -> EmailDelivery | None:
    delivery = db.scalar(
        select(EmailDelivery)
        .where(EmailDelivery.id == delivery_id)
        .with_for_update()
    )
    if not delivery or delivery.status not in (
        EmailDeliveryStatus.pending,
        EmailDeliveryStatus.failed,
    ):
        return delivery

    delivery.attempts += 1
    delivery.last_error = None
    try:
        if _consume_demo_failure(db, delivery):
            delivery.status = EmailDeliveryStatus.failed
            delivery.provider_id = None
            delivery.last_error = "Simulated one-time demo failure"
        else:
            result = get_email_backend().send(
                delivery.recipient,
                delivery.subject,
                delivery.html_body or "",
            )
            delivery.status = result.status
            delivery.provider_id = result.provider_id
    except Exception as exc:
        delivery.status = EmailDeliveryStatus.failed
        delivery.provider_id = None
        delivery.last_error = f"Email backend failed ({type(exc).__name__})"
    delivery.updated_at = utcnow()
    db.commit()
    db.refresh(delivery)
    return delivery


def _consume_demo_failure(db: Session, delivery: EmailDelivery) -> bool:
    if (
        settings.email_backend != "outbox"
        or not settings.email_simulate_failure_once
        or delivery.kind != "shareholder_statement"
    ):
        return False
    flag = db.scalar(
        select(BusinessSetting)
        .where(BusinessSetting.key == "email_demo_failure_pending")
        .with_for_update()
    )
    if not flag:
        raise RuntimeError("The demo email failure setting is missing")
    if flag.value.lower() != "true":
        return False
    flag.value = "false"
    return True


def deliver_email(delivery_id: int) -> None:
    with database.SessionLocal() as db:
        deliver_with_session(db, delivery_id)


def deliver_report_emails(snapshot_id: int) -> None:
    with database.SessionLocal() as db:
        delivery_ids = db.scalars(
            select(EmailDelivery.id)
            .join(ShareholderStatement, EmailDelivery.statement_id == ShareholderStatement.id)
            .where(ShareholderStatement.snapshot_id == snapshot_id)
            .order_by(EmailDelivery.id)
        ).all()
    for delivery_id in delivery_ids:
        deliver_email(delivery_id)


def issue_password_reset(email: str) -> None:
    with database.SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
        if not user:
            return
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now.replace(microsecond=0) + timedelta(minutes=RESET_TOKEN_MINUTES),
        )
        db.add(reset)
        base_url = settings.frontend_origin.rstrip("/")
        link = f"{base_url}/reset-password?token={raw_token}"
        body = (
            "<!doctype html><html><body><h1>Password reset</h1>"
            "<p>Use this link within 30 minutes to set a new password:</p>"
            f"<p><a href='{escape(link, quote=True)}'>Reset password</a></p>"
            "<p>If you did not request this, you can ignore this email.</p></body></html>"
        )
        delivery = EmailDelivery(
            recipient=user.email,
            subject="Reset your Turf & Pool Manager password",
            kind="password_reset",
            status=EmailDeliveryStatus.pending,
            html_body=body,
        )
        db.add(delivery)
        db.commit()
        deliver_with_session(db, delivery.id)


def rate_limit_reset_request(db: Session, key_hash: str, now: datetime) -> bool:
    window_start = now.replace(
        minute=(now.minute // 15) * 15,
        second=0,
        microsecond=0,
    )
    dialect = db.bind.dialect.name if db.bind else ""
    values = {
        "key_hash": key_hash,
        "window_start": window_start,
        "request_count": 1,
    }
    db.execute(delete(PasswordResetRateBucket).where(
        PasswordResetRateBucket.window_start < now - timedelta(days=1)
    ))
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(f"Password reset rate limiting is unsupported for {dialect}")
    statement = insert(PasswordResetRateBucket).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[
            PasswordResetRateBucket.key_hash,
            PasswordResetRateBucket.window_start,
        ],
        set_={
            "request_count": PasswordResetRateBucket.request_count + 1,
        },
    ).returning(PasswordResetRateBucket.request_count)
    count = int(db.scalar(statement))
    return count <= RESET_MAX_REQUESTS
