from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings
from ..models import (
    Block, Booking, BookingChannel, BookingEvent, BookingStatus,
    BusinessSetting, CustomerContact, FacilityType, Payment, PaymentEvent,
    PaymentIntent, PaymentIntentStatus, PaymentMethod, PaymentStatus, PoolSession,
    User,
)
from ..payments.gateway import get_gateway
from .bookings import (
    _active_hold_minutes, _as_utc, _effective_hours, _expire_overlapping_pool_holds,
    _expire_overlapping_turf_holds, _facility, _transition, _validate_horizon,
    _validate_pool_session,
)

UTC = timezone.utc
BUSINESS_TZ = ZoneInfo(settings.business_timezone)
MANUAL_METHODS = {"cash", "bkash", "bank_transfer", "card", "other"}


def _next_payment_ref(db: Session, at: datetime) -> str:
    local_day = at.astimezone(BUSINESS_TZ).date()
    prefix = f"PAY-{local_day:%y%m%d}-"
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:payment_day))"),
            {"payment_day": f"payment-ref-{local_day.isoformat()}"},
        )
    latest = db.scalar(
        select(Payment.ref)
        .where(Payment.ref.like(f"{prefix}%"))
        .order_by(Payment.ref.desc())
        .limit(1)
    )
    sequence = int(latest.rsplit("-", 1)[1]) + 1 if latest else 1
    if sequence > 9999:
        raise HTTPException(409, "Payment reference limit reached for today")
    return f"{prefix}{sequence:04d}"


def _event(
    db: Session,
    payment: Payment,
    status: PaymentStatus,
    actor: User | None,
    reason: str | None,
    data: dict | None = None,
) -> None:
    db.add(PaymentEvent(
        payment_id=payment.id,
        actor_id=actor.id if actor else None,
        from_status=None,
        to_status=status,
        reason=reason,
        data=data,
    ))


def _transition_payment(
    db: Session,
    payment: Payment,
    status: PaymentStatus,
    actor: User | None,
    reason: str | None = None,
    data: dict | None = None,
) -> None:
    old_status = payment.status
    payment.status = status
    db.add(PaymentEvent(
        payment_id=payment.id,
        actor_id=actor.id if actor else None,
        from_status=old_status,
        to_status=status,
        reason=reason,
        data=data,
    ))


def _available_booking(db: Session, booking: Booking, require_active_hold: bool) -> None:
    if booking.status != BookingStatus.held:
        raise HTTPException(409, f"Booking is {booking.status.value}; it must be held")
    if require_active_hold and (
        booking.hold_expires_at is None
        or _as_utc(booking.hold_expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(409, "Booking hold has expired; extend it if the slot is still available")


def _active_payment_method(db: Session, method_code: str) -> PaymentMethod:
    method = db.get(PaymentMethod, method_code)
    if not method or not method.is_active or method_code not in MANUAL_METHODS:
        raise HTTPException(422, "Select an active manual payment method")
    return method


def _outstanding_amount(db: Session, booking: Booking) -> Decimal:
    received = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.booking_id == booking.id,
            Payment.status.in_([PaymentStatus.received, PaymentStatus.verified]),
        )
    )
    return booking.total_amount - Decimal(received or 0)


def initiate_online_payment(
    db: Session,
    booking: Booking,
    actor: User,
    idempotency_key: str,
) -> tuple[PaymentIntent, dict]:
    if not idempotency_key or len(idempotency_key) > 120:
        raise HTTPException(422, "Idempotency-Key must be between 1 and 120 characters")
    contact = db.get(CustomerContact, booking.customer_contact_id)
    if (
        not contact
        or contact.user_id != actor.id
        or booking.channel != BookingChannel.online
    ):
        raise HTTPException(403, "Only the customer who made this online booking can pay for it")

    existing = db.scalar(
        select(PaymentIntent).where(PaymentIntent.idempotency_key == idempotency_key)
    )
    if existing:
        if existing.booking_id != booking.id:
            raise HTTPException(409, "This idempotency key was already used for another booking")
        initiation = get_gateway().initiate(existing.id, existing.amount)
        return existing, {
            "gateway_reference": initiation.reference,
            "gateway_label": initiation.label,
            "amount": str(existing.amount),
            "status": existing.status.value,
        }

    _available_booking(db, booking, require_active_hold=True)
    amount = _outstanding_amount(db, booking)
    if amount <= 0:
        raise HTTPException(409, "There is no outstanding booking balance to pay")
    existing_active = db.scalar(
        select(PaymentIntent.id).where(
            PaymentIntent.booking_id == booking.id,
            PaymentIntent.status == PaymentIntentStatus.initiated,
        )
    )
    if existing_active:
        raise HTTPException(409, "An online payment is already in progress for this booking")
    intent = PaymentIntent(
        booking_id=booking.id,
        amount=amount,
        status=PaymentIntentStatus.initiated,
        idempotency_key=idempotency_key,
    )
    db.add(intent)
    db.flush()
    initiation = get_gateway().initiate(intent.id, intent.amount)
    record(
        db, actor, "payment.intent_initiate", "payment_intent", intent.id,
        after={"booking_ref": booking.ref, "amount": str(intent.amount), "mode": "simulated"},
    )
    return intent, {
        "gateway_reference": initiation.reference,
        "gateway_label": initiation.label,
        "amount": str(intent.amount),
        "status": intent.status.value,
    }


def simulate_online_result(
    db: Session,
    intent: PaymentIntent,
    actor: User,
    result: str,
) -> tuple[PaymentIntent, Booking]:
    gateway = get_gateway()
    parsed_result = gateway.parse_result(result)
    booking = db.scalar(
        select(Booking).where(Booking.id == intent.booking_id).with_for_update()
    )
    if booking is None:
        raise HTTPException(404, "Booking not found")
    contact = db.get(CustomerContact, booking.customer_contact_id)
    if not contact or contact.user_id != actor.id:
        raise HTTPException(403, "You cannot complete this payment")

    intent = db.scalar(select(PaymentIntent).where(PaymentIntent.id == intent.id).with_for_update())
    if intent is None:
        raise HTTPException(404, "Payment intent not found")
    completed_results = {
        PaymentIntentStatus.succeeded: "success",
        PaymentIntentStatus.failed: "fail",
        PaymentIntentStatus.cancelled: "cancel",
    }
    if intent.status in completed_results:
        if completed_results[intent.status] == parsed_result:
            return intent, booking
        raise HTTPException(409, f"Payment intent is already {intent.status.value}")
    if intent.status != PaymentIntentStatus.initiated:
        raise HTTPException(409, f"Payment intent is already {intent.status.value}")

    now = datetime.now(UTC)
    if parsed_result == "success":
        _available_booking(db, booking, require_active_hold=True)
        if intent.amount != _outstanding_amount(db, booking):
            raise HTTPException(409, "The outstanding booking balance changed; restart checkout")
        verified_total = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.booking_id == booking.id,
                Payment.status == PaymentStatus.verified,
            )
        )
        total_after_payment = Decimal(verified_total or 0) + intent.amount
        if total_after_payment > booking.total_amount:
            raise HTTPException(409, "The simulated payment would exceed the booking total")
        if booking.pool_session_id:
            session = db.scalar(
                select(PoolSession).where(PoolSession.id == booking.pool_session_id).with_for_update()
            )
            if not session:
                raise HTTPException(409, "Pool session is no longer available")
            reserved = db.scalar(
                select(func.coalesce(func.sum(Booking.participants), 0)).where(
                    Booking.pool_session_id == session.id,
                    Booking.id != booking.id,
                    or_(
                        Booking.status == BookingStatus.confirmed,
                        (Booking.status == BookingStatus.held)
                        & (Booking.hold_expires_at > func.now()),
                    ),
                )
            )
            if int(reserved or 0) + int(booking.participants or 0) > session.capacity:
                raise HTTPException(409, "Pool capacity is no longer available")
        initiation = gateway.initiate(intent.id, intent.amount)
        payment = Payment(
            ref=_next_payment_ref(db, now),
            booking_id=booking.id,
            amount=intent.amount,
            currency=booking.currency,
            method="online_simulated",
            status=PaymentStatus.verified,
            received_at=now,
            verified_at=now,
            recorded_by=actor.id,
            verified_by=actor.id,
            trx_id=initiation.reference,
            notes="SIMULATED PAYMENT",
        )
        db.add(payment)
        db.flush()
        _event(db, payment, PaymentStatus.verified, actor, "Simulated payment succeeded",
               {"label": "SIMULATED PAYMENT", "intent_id": intent.id})
        intent.status = PaymentIntentStatus.succeeded
        intent.completed_at = now
        if total_after_payment == booking.total_amount:
            _transition(db, booking, BookingStatus.confirmed, actor, "Simulated payment succeeded",
                        {"payment_ref": payment.ref, "verified_total": str(total_after_payment)})
        record(
            db, actor, "payment.simulated_success", "payment", payment.ref,
            after={"amount": str(payment.amount), "booking_ref": booking.ref,
                   "label": "SIMULATED PAYMENT"},
        )
    else:
        payment_status = (
            PaymentIntentStatus.failed
            if parsed_result == "fail"
            else PaymentIntentStatus.cancelled
        )
        intent.status = payment_status
        intent.completed_at = now
        payment = Payment(
            ref=_next_payment_ref(db, now),
            booking_id=booking.id,
            amount=intent.amount,
            currency=booking.currency,
            method="online_simulated",
            status=PaymentStatus.failed,
            recorded_by=actor.id,
            notes=f"SIMULATED PAYMENT {parsed_result.upper()}",
        )
        db.add(payment)
        db.flush()
        _event(db, payment, PaymentStatus.failed, actor, f"Simulated payment {parsed_result}",
               {"label": "SIMULATED PAYMENT", "intent_id": intent.id})
        record(
            db, actor, f"payment.simulated_{parsed_result}", "payment", payment.ref,
            after={"booking_ref": booking.ref, "status": PaymentStatus.failed.value},
        )
    db.flush()
    return intent, booking


def record_manual_payment(
    db: Session,
    booking: Booking,
    actor: User,
    *,
    amount: Decimal,
    method_code: str,
    received_at: datetime,
    trx_id: str | None = None,
    sender_phone: str | None = None,
    bank_ref: str | None = None,
    sms_text: str | None = None,
    notes: str | None = None,
) -> Payment:
    _available_booking(db, booking, require_active_hold=True)
    method = _active_payment_method(db, method_code)
    active_intent = db.scalar(
        select(PaymentIntent.id).where(
            PaymentIntent.booking_id == booking.id,
            PaymentIntent.status == PaymentIntentStatus.initiated,
        )
    )
    if active_intent:
        raise HTTPException(409, "Complete or cancel the online payment before recording a manual payment")
    if amount <= 0:
        raise HTTPException(422, "Payment amount must be greater than zero")
    if amount > _outstanding_amount(db, booking):
        raise HTTPException(409, "Payment exceeds the outstanding booking balance")
    if received_at.tzinfo is None:
        raise HTTPException(422, "received_at must include a timezone")
    trx_id = trx_id.strip() if trx_id else None
    bank_ref = bank_ref.strip() if bank_ref else None
    if method.requires_reference and not (trx_id or bank_ref):
        raise HTTPException(422, "This payment method requires a transaction or bank reference")
    now = datetime.now(UTC)
    payment = Payment(
        ref=_next_payment_ref(db, now),
        booking_id=booking.id,
        amount=amount,
        currency=booking.currency,
        method=method.code,
        status=PaymentStatus.received,
        received_at=received_at.astimezone(UTC),
        trx_id=trx_id,
        sender_phone=sender_phone,
        bank_ref=bank_ref,
        sms_text=sms_text,
        recorded_by=actor.id,
        notes=notes,
    )
    db.add(payment)
    db.flush()
    _event(db, payment, PaymentStatus.received, actor, "Payment recorded")
    record(
        db, actor, "payment.record", "payment", payment.ref,
        after={"booking_ref": booking.ref, "amount": str(amount),
               "method": method.code, "received_at": received_at.astimezone(UTC).isoformat()},
    )
    return payment


def renew_expired_hold(
    db: Session,
    booking: Booking,
    actor: User,
    reason: str,
) -> None:
    now = datetime.now(UTC)
    if booking.status == BookingStatus.held:
        if booking.hold_expires_at and _as_utc(booking.hold_expires_at) > now:
            raise HTTPException(409, "This booking hold has not expired")
        _transition(db, booking, BookingStatus.expired, None, "Hold expired")
        db.flush()
    if booking.status != BookingStatus.expired:
        raise HTTPException(409, "Only expired bookings can have their hold renewed")

    if booking.pool_session_id:
        session = db.scalar(
            select(PoolSession)
            .where(PoolSession.id == booking.pool_session_id)
            .with_for_update()
        )
        if not session:
            raise HTTPException(409, "Pool session is no longer available")
        _validate_pool_session(db, session)
        _expire_overlapping_pool_holds(db, session.id)
        reserved = db.scalar(
            select(func.coalesce(func.sum(Booking.participants), 0)).where(
                Booking.pool_session_id == session.id,
                Booking.id != booking.id,
                or_(
                    Booking.status == BookingStatus.confirmed,
                    (Booking.status == BookingStatus.held)
                    & (Booking.hold_expires_at > func.now()),
                ),
            )
        )
        if int(reserved or 0) + int(booking.participants or 0) > session.capacity:
            raise HTTPException(409, "Pool capacity is no longer available")
    else:
        _facility(db, booking.facility_id, FacilityType.turf)
        if booking.starts_at is None or booking.ends_at is None:
            raise HTTPException(409, "Booking time is incomplete")
        start = _as_utc(booking.starts_at)
        end = _as_utc(booking.ends_at)
        if start <= now:
            raise HTTPException(409, "The booking time has already passed")
        _validate_horizon(start.astimezone(BUSINESS_TZ).date(), db)
        day = start.astimezone(BUSINESS_TZ).date()
        opening, closing = _effective_hours(db, booking.facility_id, day)
        local_start = start.astimezone(BUSINESS_TZ)
        local_end = end.astimezone(BUSINESS_TZ)
        if local_start.time().replace(tzinfo=None) < opening or local_end.time().replace(tzinfo=None) > closing:
            raise HTTPException(409, "The booking is outside operating hours")
        blocked = db.scalar(
            select(func.count()).select_from(Block).where(
                Block.facility_id == booking.facility_id,
                Block.starts_at < end,
                Block.ends_at > start,
            )
        )
        if blocked:
            raise HTTPException(409, "The booking time is blocked")
        _expire_overlapping_turf_holds(db, booking.facility_id, start, end)
        overlap = db.scalar(
            select(Booking.id).where(
                Booking.facility_id == booking.facility_id,
                Booking.id != booking.id,
                Booking.status.in_([BookingStatus.held, BookingStatus.confirmed]),
                Booking.starts_at < end,
                Booking.ends_at > start,
            ).limit(1)
        )
        if overlap:
            raise HTTPException(409, "The turf time is no longer available")

    expiry = now + timedelta(minutes=_active_hold_minutes(db, booking.channel))
    booking.hold_expires_at = expiry
    before_status = booking.status
    booking.status = BookingStatus.held
    db.add(BookingEvent(
        booking_id=booking.id,
        actor_id=actor.id,
        from_status=before_status,
        to_status=BookingStatus.held,
        reason=reason,
        data={"hold_expires_at": expiry.isoformat(), "renewed": True},
    ))
    record(
        db, actor, "booking.renew_expired_hold", "booking", booking.ref,
        before={"status": before_status.value},
        after={"status": BookingStatus.held.value, "hold_expires_at": expiry.isoformat()},
        reason=reason,
    )
    db.flush()


def verify_payment(db: Session, payment: Payment, actor: User) -> Booking:
    if payment.status != PaymentStatus.received:
        raise HTTPException(409, "Only received payments can be verified")
    booking = db.scalar(select(Booking).where(Booking.id == payment.booking_id).with_for_update())
    if booking is None:
        raise HTTPException(404, "Booking not found")
    _available_booking(db, booking, require_active_hold=False)
    if actor.id == payment.recorded_by and BusinessSetting.get_bool(
        db, "require_different_verifier", True
    ):
        raise HTTPException(409, "A different authorized person must verify this payment")
    verified_total = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.booking_id == booking.id,
            Payment.status == PaymentStatus.verified,
        )
    )
    total_after_verification = Decimal(verified_total or 0) + payment.amount
    if total_after_verification > booking.total_amount:
        raise HTTPException(409, "Verified payments would exceed the booking total")
    if total_after_verification == booking.total_amount:
        if (
            booking.hold_expires_at is None
            or _as_utc(booking.hold_expires_at) <= datetime.now(UTC)
        ):
            raise HTTPException(
                409,
                "The booking hold has expired; extend it if the slot is still available before verifying the final payment",
            )
    now = datetime.now(UTC)
    payment.status = PaymentStatus.verified
    payment.verified_at = now
    payment.verified_by = actor.id
    _transition_payment(db, payment, PaymentStatus.verified, actor, "Payment verified")
    if total_after_verification == booking.total_amount:
        _transition(
            db, booking, BookingStatus.confirmed, actor,
            "Full booking amount paid and verified",
            {"payment_ref": payment.ref, "verified_total": str(total_after_verification)},
        )
    record(
        db, actor, "payment.verify", "payment", payment.ref,
        before={"status": PaymentStatus.received.value},
        after={"status": PaymentStatus.verified.value, "verified_at": now.isoformat()},
    )
    db.flush()
    return booking


def reject_payment(db: Session, payment: Payment, actor: User, reason: str) -> None:
    if payment.status != PaymentStatus.received:
        raise HTTPException(409, "Only received payments can be rejected")
    payment.rejection_reason = reason
    _transition_payment(db, payment, PaymentStatus.rejected, actor, reason)
    record(
        db, actor, "payment.reject", "payment", payment.ref,
        before={"status": PaymentStatus.received.value},
        after={"status": PaymentStatus.rejected.value},
        reason=reason,
    )


def payment_output(payment: Payment, booking_ref: str | None = None) -> dict:
    return {
        "id": payment.id,
        "ref": payment.ref,
        "booking_id": payment.booking_id,
        "booking_ref": booking_ref,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "method": payment.method,
        "status": payment.status.value,
        "received_at": _as_utc(payment.received_at).isoformat() if payment.received_at else None,
        "recorded_at": _as_utc(payment.recorded_at).isoformat(),
        "verified_at": _as_utc(payment.verified_at).isoformat() if payment.verified_at else None,
        "trx_id": payment.trx_id,
        "sender_phone": payment.sender_phone,
        "bank_ref": payment.bank_ref,
        "recorded_by": payment.recorded_by,
        "verified_by": payment.verified_by,
        "notes": payment.notes,
        "rejection_reason": payment.rejection_reason,
    }


def payment_receipt(db: Session, payment: Payment) -> dict:
    booking = db.get(Booking, payment.booking_id)
    if booking is None:
        raise HTTPException(404, "Booking not found")
    contact = db.get(CustomerContact, booking.customer_contact_id)
    return {
        **payment_output(payment, booking.ref),
        "booking_ref": booking.ref,
        "customer_name": contact.name if contact else "",
        "label": "SIMULATED PAYMENT" if payment.method == "online_simulated" else None,
        "notice": (
            "This is a simulated payment record, not a real money transfer."
            if payment.method == "online_simulated"
            else "Payment receipt"
        ),
    }
