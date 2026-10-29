from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record
from ..db import get_db
from ..deps import get_current_user, require_complete_profile
from ..models import (
    Booking, BookingChannel, BookingStatus, CustomerContact, PoolSession, User,
)
from ..permissions import has_permission, require_permission
from ..schemas import BookingActionIn, BookingSelection, ExtendHoldIn, StaffBookingIn
from ..security import normalize_bd_phone
from ..services.bookings import (
    booking_output, booking_outputs, create_booking, perform_booking_action,
)
from ..services.exports import booking_query
from ..services.payments import renew_expired_hold

router = APIRouter(prefix="/bookings", tags=["bookings"])
my_router = APIRouter(prefix="/my/bookings", tags=["bookings"])
BUSINESS_TZ = ZoneInfo("Asia/Dhaka")
UTC = timezone.utc


def _create_or_conflict(db: Session, **kwargs):
    try:
        booking = create_booking(db, **kwargs)
        db.commit()
        db.refresh(booking)
        return booking
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "ex_bookings_turf_interval":
            raise HTTPException(409, "That turf time is no longer available") from exc
        if constraint == "uq_bookings_ref":
            raise HTTPException(409, "Could not create a unique booking reference; please retry") from exc
        raise


@router.post("", status_code=201)
def create_online_booking(
    body: BookingSelection,
    actor: User = Depends(require_complete_profile),
    db: Session = Depends(get_db),
    permitted: User = Depends(require_permission("booking.create_self")),
):
    contact = db.scalar(select(CustomerContact).where(CustomerContact.user_id == actor.id))
    if contact is None:
        try:
            with db.begin_nested():
                contact = CustomerContact(
                    user_id=actor.id,
                    name=actor.full_name,
                    phone=actor.phone or "",
                    address=actor.address,
                )
                db.add(contact)
                db.flush()
        except IntegrityError:
            contact = db.scalar(select(CustomerContact).where(CustomerContact.user_id == actor.id))
            if contact is None:
                raise
        else:
            record(
                db, actor, "customer_contact.link", "customer_contact", contact.id,
                after={"user_id": actor.id, "phone": contact.phone},
            )
    booking = _create_or_conflict(
        db,
        actor=actor,
        channel=BookingChannel.online,
        facility_id=body.facility_id,
        starts_at=body.starts_at,
        pool_session_id=body.pool_session_id,
        participants=body.participants,
        contact=contact,
        notes=body.notes,
    )
    return booking_output(db, booking)


@router.post("/staff", status_code=201)
def create_staff_booking(
    body: StaffBookingIn,
    actor: User = Depends(require_permission("booking.create_for_customer")),
    db: Session = Depends(get_db),
):
    contact = db.scalar(select(CustomerContact).where(CustomerContact.phone == body.customer_phone))
    if contact is None:
        contact = CustomerContact(
            name=body.customer_name,
            phone=body.customer_phone,
            address=body.customer_address,
        )
        db.add(contact)
        db.flush()
        record(
            db, actor, "customer_contact.create", "customer_contact", contact.id,
            after={"name": contact.name, "phone": contact.phone, "address": contact.address},
        )
    else:
        before = {"name": contact.name, "phone": contact.phone, "address": contact.address}
        contact.name = body.customer_name
        if body.customer_address:
            contact.address = body.customer_address
        after = {"name": contact.name, "phone": contact.phone, "address": contact.address}
        if before != after:
            record(
                db, actor, "customer_contact.update", "customer_contact", contact.id,
                before=before, after=after,
            )
    booking = _create_or_conflict(
        db,
        actor=actor,
        channel=BookingChannel(body.channel),
        facility_id=body.facility_id,
        starts_at=body.starts_at,
        pool_session_id=body.pool_session_id,
        participants=body.participants,
        contact=contact,
        notes=body.notes,
    )
    return booking_output(db, booking)


@router.get("")
def list_bookings(
    date_from: date | None = None,
    date_to: date | None = None,
    facility_id: int | None = Query(default=None, gt=0),
    channel: BookingChannel | None = None,
    status: BookingStatus | None = None,
    ref: str | None = Query(default=None, max_length=20),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    query = booking_query(date_from, date_to, facility_id, channel, status, ref)
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Booking.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    items = booking_outputs(db, rows)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/contacts")
def find_customer_contact(
    phone: str = Query(min_length=1, max_length=20),
    actor: User = Depends(require_permission("booking.create_for_customer")),
    db: Session = Depends(get_db),
):
    try:
        normalized_phone = normalize_bd_phone(phone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    contact = db.scalar(select(CustomerContact).where(CustomerContact.phone == normalized_phone))
    if not contact:
        return {"found": False}
    return {
        "found": True,
        "name": contact.name,
        "phone": contact.phone,
        "address": contact.address,
    }


@router.get("/{ref}")
def get_booking(
    ref: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.ref == ref))
    if not booking:
        raise HTTPException(404, "Booking not found")
    if not has_permission(actor.role, "booking.manage") and not has_permission(actor.role, "payment.record"):
        contact = db.get(CustomerContact, booking.customer_contact_id)
        if not contact or contact.user_id != actor.id:
            raise HTTPException(403, "You cannot view this booking")
    return booking_output(db, booking, include_events=True)


@router.post("/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    body: BookingActionIn,
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    perform_booking_action(db, booking, actor, "cancel", body.reason)
    db.commit()
    return booking_output(db, booking)


@router.post("/{booking_id}/extend-hold")
def extend_booking_hold(
    booking_id: int,
    body: ExtendHoldIn,
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    perform_booking_action(db, booking, actor, "extend", body.reason, body.minutes)
    db.commit()
    return booking_output(db, booking)


@router.post("/{booking_id}/renew-hold")
def renew_booking_hold(
    booking_id: int,
    body: BookingActionIn,
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    try:
        renew_expired_hold(db, booking, actor, body.reason)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "ex_bookings_turf_interval":
            raise HTTPException(409, "The turf time is no longer available") from exc
        raise
    return booking_output(db, booking)


@router.post("/{booking_id}/release")
def release_booking_hold(
    booking_id: int,
    body: BookingActionIn,
    actor: User = Depends(require_permission("booking.manage")),
    db: Session = Depends(get_db),
):
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking:
        raise HTTPException(404, "Booking not found")
    perform_booking_action(db, booking, actor, "release", body.reason)
    db.commit()
    return booking_output(db, booking)


@my_router.get("")
def list_my_bookings(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    actor: User = Depends(require_permission("booking.create_self")),
    db: Session = Depends(get_db),
):
    contact = db.scalar(select(CustomerContact).where(CustomerContact.user_id == actor.id))
    if contact is None:
        return {"items": [], "total": 0, "page": page, "size": size}
    query = select(Booking).where(Booking.customer_contact_id == contact.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query
        .order_by(Booking.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"items": booking_outputs(db, rows, include_events=True),
            "total": total, "page": page, "size": size}
