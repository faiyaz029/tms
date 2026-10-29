from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Booking, BookingStatus, CustomerContact, Payment, PaymentIntent, PaymentMethod,
    PaymentIntentStatus, PaymentStatus, User,
)
from ..permissions import has_permission, require_permission
from ..schemas import ManualPaymentIn, OnlinePaymentIn, PaymentRejectIn
from ..services.payments import (
    initiate_online_payment, payment_output, payment_receipt, record_manual_payment,
    reject_payment, renew_expired_hold, simulate_online_result, verify_payment,
)
from ..services.exports import payment_query

router = APIRouter(prefix="/payments", tags=["payments"])
booking_router = APIRouter(prefix="/bookings", tags=["payments"])


def _can_access_booking(db: Session, booking: Booking, user: User) -> bool:
    if has_permission(user.role, "payment.record"):
        return True
    contact = db.get(CustomerContact, booking.customer_contact_id)
    return bool(contact and contact.user_id == user.id)


def _commit_payment_or_conflict(db: Session, operation):
    try:
        result = operation()
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        database_error = str(exc.orig)
        if constraint == "uq_payments_method_trx" or (
            "payments.method, payments.trx_id" in database_error
        ):
            raise HTTPException(409, "This transaction reference has already been recorded") from exc
        if constraint == "payments_ref_key" or "payments.ref" in database_error:
            raise HTTPException(409, "Could not create a unique payment reference; please retry") from exc
        raise


@router.get("/methods")
def list_payment_methods(
    _: User = Depends(require_permission("payment.record")),
    db: Session = Depends(get_db),
):
    methods = db.scalars(
        select(PaymentMethod).where(
            PaymentMethod.is_active.is_(True),
            PaymentMethod.code != "online_simulated",
        ).order_by(PaymentMethod.label)
    ).all()
    return {"items": [{
        "code": method.code,
        "label": method.label,
        "requires_reference": method.requires_reference,
    } for method in methods]}


@router.post("/online/initiate")
def initiate_online(
    body: OnlinePaymentIn,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=120),
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == body.booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    try:
        intent, response = initiate_online_payment(db, booking, actor, idempotency_key)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        database_error = str(exc.orig)
        if constraint in {"payment_intents_idempotency_key_key", "payment_intents_idempotency_key"} or (
            "payment_intents.idempotency_key" in database_error
        ):
            existing = db.scalar(
                select(PaymentIntent).where(PaymentIntent.idempotency_key == idempotency_key)
            )
            if existing and existing.booking_id == body.booking_id:
                return {
                    "id": existing.id,
                    "booking_id": existing.booking_id,
                    **initiate_online_payment(db, booking, actor, idempotency_key)[1],
                }
            raise HTTPException(409, "This idempotency key was already used") from exc
        raise
    return {"id": intent.id, "booking_id": intent.booking_id, **response}


@router.post("/online/{intent_id}/simulate/{result}")
def simulate_payment(
    intent_id: int,
    result: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    intent = db.get(PaymentIntent, intent_id)
    if not intent:
        raise HTTPException(404, "Payment intent not found")
    try:
        intent, booking = simulate_online_result(db, intent, actor, result)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        database_error = str(exc.orig)
        if constraint in {"uq_payments_method_trx", "payments_ref_key"} or any(
            field in database_error
            for field in ("payments.method, payments.trx_id", "payments.ref")
        ):
            raise HTTPException(409, "This simulated payment has already been applied") from exc
        raise
    return {
        "intent_id": intent.id,
        "intent_status": intent.status.value,
        "booking_ref": booking.ref,
        "booking_status": booking.status.value,
        "label": "SIMULATED PAYMENT",
    }


@booking_router.post("/{booking_id}/payments", status_code=201)
def add_manual_payment(
    booking_id: int,
    body: ManualPaymentIn,
    actor: User = Depends(require_permission("payment.record")),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    payment = _commit_payment_or_conflict(
        db,
        lambda: record_manual_payment(
            db, booking, actor,
            amount=body.amount,
            method_code=body.method,
            received_at=body.received_at,
            trx_id=body.trx_id,
            sender_phone=body.sender_phone,
            bank_ref=body.bank_ref,
            sms_text=body.sms_text,
            notes=body.notes,
        ),
    )
    return payment_output(payment, booking.ref)


@router.post("/{payment_id}/verify")
def verify(
    payment_id: int,
    actor: User = Depends(require_permission("payment.verify")),
    db: Session = Depends(get_db),
):
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment:
        raise HTTPException(404, "Payment not found")
    booking = verify_payment(db, payment, actor)
    db.commit()
    return {
        "payment": payment_output(payment, booking.ref),
        "booking_ref": booking.ref,
        "booking_status": booking.status.value,
    }


@router.post("/{payment_id}/reject")
def reject(
    payment_id: int,
    body: PaymentRejectIn,
    actor: User = Depends(require_permission("payment.verify")),
    db: Session = Depends(get_db),
):
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment:
        raise HTTPException(404, "Payment not found")
    reject_payment(db, payment, actor, body.reason)
    db.commit()
    booking = db.get(Booking, payment.booking_id)
    return payment_output(payment, booking.ref if booking else None)


@router.get("")
def list_payments(
    received_from: date | None = None,
    received_to: date | None = None,
    method: str | None = None,
    status: PaymentStatus | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_permission("payment.record")),
    db: Session = Depends(get_db),
):
    query = payment_query(received_from, received_to, method, status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    payments = db.scalars(
        query.order_by(Payment.recorded_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    booking_refs = {
        booking_id: booking_ref
        for booking_id, booking_ref in db.execute(
            select(Booking.id, Booking.ref).where(
                Booking.id.in_({payment.booking_id for payment in payments})
            )
        )
    } if payments else {}
    return {"items": [
        payment_output(payment, booking_refs.get(payment.booking_id))
        for payment in payments
    ],
            "total": total, "page": page, "size": size}


@router.get("/booking/{booking_ref}")
def booking_payments(
    booking_ref: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.ref == booking_ref))
    if not booking:
        raise HTTPException(404, "Booking not found")
    if not _can_access_booking(db, booking, actor):
        raise HTTPException(403, "You cannot view payments for this booking")
    payments = db.scalars(
        select(Payment).where(Payment.booking_id == booking.id).order_by(Payment.recorded_at)
    ).all()
    active_intent = db.scalar(
        select(PaymentIntent).where(
            PaymentIntent.booking_id == booking.id,
            PaymentIntent.status == PaymentIntentStatus.initiated,
        ).order_by(PaymentIntent.created_at.desc())
    )
    return {
        "items": [payment_output(payment, booking.ref) for payment in payments],
        "active_intent": ({
            "id": active_intent.id,
            "amount": str(active_intent.amount),
            "status": active_intent.status.value,
            "label": "SIMULATED PAYMENT",
        } if active_intent else None),
    }


@router.get("/{payment_ref}/receipt")
def receipt(
    payment_ref: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = db.scalar(select(Payment).where(Payment.ref == payment_ref))
    if not payment:
        raise HTTPException(404, "Payment not found")
    booking = db.get(Booking, payment.booking_id)
    if not booking or not _can_access_booking(db, booking, actor):
        raise HTTPException(403, "You cannot view this payment receipt")
    if payment.status != PaymentStatus.verified:
        raise HTTPException(409, "A receipt is available only for verified payments")
    return payment_receipt(db, payment)


@router.get("/{payment_id}")
def payment_detail(
    payment_id: int,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")
    booking = db.get(Booking, payment.booking_id)
    if not booking or not _can_access_booking(db, booking, actor):
        raise HTTPException(403, "You cannot view this payment")
    return payment_output(payment, booking.ref if booking else None)
