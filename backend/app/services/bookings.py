from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings
from ..models import (
    AuditLog, Block, Booking, BookingChannel, BookingEvent, BookingStatus,
    BusinessSetting, CustomerContact, Facility, FacilityType, OperatingSchedule,
    PoolSession, SpecialDay, User,
)
from .availability import turf_price

TZ = ZoneInfo(settings.business_timezone)
UTC = timezone.utc
TRANSITIONS = {
    BookingStatus.draft: {BookingStatus.held, BookingStatus.cancelled},
    BookingStatus.held: {BookingStatus.confirmed, BookingStatus.cancelled, BookingStatus.expired},
    BookingStatus.confirmed: {BookingStatus.cancelled},
    BookingStatus.cancelled: set(),
    BookingStatus.expired: set(),
}


def _transition(
    db: Session,
    booking: Booking,
    to_status: BookingStatus,
    actor: User | None,
    reason: str | None,
    data: dict | None = None,
) -> None:
    if to_status not in TRANSITIONS[booking.status]:
        raise HTTPException(409, f"Cannot change booking from {booking.status.value} to {to_status.value}")
    before = booking.status
    booking.status = to_status
    if to_status != BookingStatus.held:
        booking.hold_expires_at = None
    db.add(BookingEvent(
        booking_id=booking.id,
        actor_id=actor.id if actor else None,
        from_status=before,
        to_status=to_status,
        reason=reason,
        data=data,
    ))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _record_expirations(db: Session, bookings: list[Booking]) -> None:
    for booking in bookings:
        _transition(db, booking, BookingStatus.expired, None, "Hold expired")


def expire_holds(db: Session, at: datetime | None = None) -> int:
    """Expire every elapsed hold; safe to call repeatedly from multiple workers."""
    expiry_filter = Booking.hold_expires_at <= at if at else Booking.hold_expires_at <= func.now()
    rows = db.scalars(
        select(Booking).where(
            Booking.status == BookingStatus.held,
            expiry_filter,
        ).with_for_update(skip_locked=True)
    ).all()
    _record_expirations(db, rows)
    db.commit()
    return len(rows)


def _lock_reference_day(db: Session, day: date) -> None:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:booking_day))"),
                   {"booking_day": f"booking-ref-{day.isoformat()}"})


def _next_reference(db: Session, now: datetime) -> str:
    local_day = now.astimezone(TZ).date()
    _lock_reference_day(db, local_day)
    prefix = f"BK-{local_day:%y%m%d}-"
    latest = db.scalar(
        select(Booking.ref)
        .where(Booking.ref.like(f"{prefix}%"))
        .order_by(Booking.ref.desc())
        .limit(1)
    )
    sequence = int(latest.rsplit("-", 1)[1]) + 1 if latest else 1
    if sequence > 9999:
        raise HTTPException(409, "Booking reference limit reached for today")
    return f"{prefix}{sequence:04d}"


def _facility(db: Session, facility_id: int, expected_type: FacilityType) -> Facility:
    facility = db.get(Facility, facility_id)
    if not facility or not facility.is_active or facility.facility_type != expected_type:
        raise HTTPException(422, "The selected facility is unavailable")
    return facility


def _effective_hours(db: Session, facility_id: int, day: date) -> tuple[time, time]:
    schedule = db.scalar(
        select(OperatingSchedule).where(
            OperatingSchedule.facility_id == facility_id,
            OperatingSchedule.weekday == day.weekday(),
        )
    )
    special_days = db.scalars(
        select(SpecialDay)
        .where(
            SpecialDay.date == day,
            or_(SpecialDay.facility_id == facility_id, SpecialDay.facility_id.is_(None)),
        )
        .order_by(SpecialDay.facility_id.is_(None).desc())
    ).all()
    if schedule:
        open_time, close_time = schedule.open_time, schedule.close_time
        closed = schedule.is_closed
    elif special_days and special_days[0].open_time and special_days[0].close_time:
        open_time, close_time = special_days[0].open_time, special_days[0].close_time
        closed = True
    else:
        raise HTTPException(409, "The facility is closed on that date")
    for special in special_days:
        closed = special.is_closed
        if special.open_time is not None:
            open_time = special.open_time
        if special.close_time is not None:
            close_time = special.close_time
    if closed:
        raise HTTPException(409, "The facility is closed on that date")
    return open_time, close_time


def _validate_horizon(day: date, db: Session) -> None:
    horizon = BusinessSetting.get_int(db, "booking_horizon_days", 21)
    today = datetime.now(TZ).date()
    if day < today:
        raise HTTPException(409, "Bookings cannot be made for a past date")
    if day > today + timedelta(days=horizon):
        raise HTTPException(409, f"Date is outside the booking horizon ({horizon} days)")


def _expire_overlapping_turf_holds(
    db: Session, facility_id: int, start: datetime, end: datetime
) -> None:
    stale = db.scalars(
        select(Booking).where(
            Booking.facility_id == facility_id,
            Booking.status == BookingStatus.held,
            Booking.hold_expires_at <= func.now(),
            Booking.starts_at < end,
            Booking.ends_at > start,
        ).with_for_update()
    ).all()
    _record_expirations(db, stale)
    db.flush()


def _expire_overlapping_pool_holds(db: Session, session_id: int) -> None:
    stale = db.scalars(
        select(Booking).where(
            Booking.pool_session_id == session_id,
            Booking.status == BookingStatus.held,
            Booking.hold_expires_at <= func.now(),
        ).with_for_update()
    ).all()
    _record_expirations(db, stale)
    db.flush()


def _validate_pool_session(db: Session, session: PoolSession) -> None:
    day = session.date
    _validate_horizon(day, db)
    _facility(db, session.facility_id, FacilityType.pool)
    start_local = _as_utc(session.start_at).astimezone(TZ)
    end_local = _as_utc(session.end_at).astimezone(TZ)
    opening, closing = _effective_hours(db, session.facility_id, day)
    if start_local.time() < opening or end_local.time() > closing:
        raise HTTPException(409, "The pool session is outside operating hours")
    session_start = _as_utc(session.start_at)
    session_end = _as_utc(session.end_at)
    blocks = db.scalars(
        select(Block).where(
            Block.facility_id == session.facility_id,
            Block.starts_at < session_end,
            Block.ends_at > session_start,
        )
    ).all()
    if blocks:
        raise HTTPException(409, "The pool session is blocked")


def _active_hold_minutes(db: Session, channel: BookingChannel) -> int:
    key = "hold_minutes_online" if channel == BookingChannel.online else "hold_minutes_phone"
    default = 10 if channel == BookingChannel.online else 30
    minutes = BusinessSetting.get_int(db, key, default)
    if not 1 <= minutes <= 1440:
        raise HTTPException(500, "Booking hold settings are invalid")
    return minutes


def create_booking(
    db: Session,
    actor: User,
    *,
    channel: BookingChannel,
    facility_id: int,
    starts_at: datetime | None = None,
    pool_session_id: int | None = None,
    participants: int | None = None,
    contact: CustomerContact,
    notes: str | None = None,
) -> Booking:
    now = datetime.now(UTC)
    if starts_at is not None:
        facility = _facility(db, facility_id, FacilityType.turf)
        local_start = starts_at.astimezone(TZ)
        day = local_start.date()
        _validate_horizon(day, db)
        duration = BusinessSetting.get_int(db, "turf_duration_minutes", 60)
        step = BusinessSetting.get_int(db, "turf_slot_step_minutes", 30)
        if duration < 1 or step < 1:
            raise HTTPException(500, "Turf booking settings are invalid")
        opening, closing = _effective_hours(db, facility.id, day)
        start_time = local_start.time().replace(tzinfo=None)
        elapsed_minutes = (
            (start_time.hour * 60 + start_time.minute)
            - (opening.hour * 60 + opening.minute)
        )
        if (
            start_time < opening
            or start_time.second
            or start_time.microsecond
            or elapsed_minutes % step
        ):
            raise HTTPException(409, "The selected start time is outside operating hours or not on a valid slot")
        end_at = starts_at.astimezone(UTC) + timedelta(minutes=duration)
        local_end = end_at.astimezone(TZ)
        if local_end.date() != day or local_end.time().replace(tzinfo=None) > closing:
            raise HTTPException(409, "The booking is outside operating hours")
        if starts_at.astimezone(UTC) <= now:
            raise HTTPException(409, "Bookings must start in the future")
        blocks = db.scalars(
            select(Block).where(
                Block.facility_id == facility.id,
                Block.starts_at < end_at,
                Block.ends_at > starts_at.astimezone(UTC),
            )
        ).all()
        if blocks:
            raise HTTPException(409, "That time is blocked")
        start_utc = starts_at.astimezone(UTC)
        end_utc = end_at
        _expire_overlapping_turf_holds(db, facility.id, start_utc, end_utc)
        overlap = db.scalar(
            select(Booking.id).where(
                Booking.facility_id == facility.id,
                Booking.status.in_([BookingStatus.held, BookingStatus.confirmed]),
                Booking.starts_at < end_utc,
                Booking.ends_at > start_utc,
            ).limit(1)
        )
        if overlap:
            raise HTTPException(409, "That turf time is no longer available")
        amount = turf_price(db, facility.id, day, start_utc, end_utc)
        if amount is None:
            raise HTTPException(409, "Turf pricing is not configured for this time")
        if amount < 0:
            raise HTTPException(500, "Turf pricing is invalid")
        session_id = None
        participant_count = None
    else:
        if pool_session_id is None or participants is None or participants < 1:
            raise HTTPException(422, "A pool session and positive participant count are required")
        session = db.scalar(
            select(PoolSession).where(PoolSession.id == pool_session_id).with_for_update()
        )
        if not session or session.facility_id != facility_id:
            raise HTTPException(404, "Pool session not found")
        _validate_pool_session(db, session)
        _expire_overlapping_pool_holds(db, session.id)
        reserved = db.scalar(
            select(func.coalesce(func.sum(Booking.participants), 0)).where(
                Booking.pool_session_id == session.id,
                or_(
                    Booking.status == BookingStatus.confirmed,
                    (Booking.status == BookingStatus.held) & (Booking.hold_expires_at > func.now()),
                ),
            )
        )
        if int(reserved or 0) + participants > session.capacity:
            raise HTTPException(409, "Not enough remaining pool capacity")
        amount = session.price_per_person * participants
        if amount < 0:
            raise HTTPException(500, "Pool session pricing is invalid")
        start_utc, end_utc = None, None
        session_id, participant_count = session.id, participants

    booking = Booking(
        ref=_next_reference(db, now),
        facility_id=facility_id,
        channel=channel,
        status=BookingStatus.draft,
        customer_contact_id=contact.id,
        created_by_user_id=actor.id,
        total_amount=amount,
        currency=settings.currency,
        notes=notes,
        starts_at=start_utc,
        ends_at=end_utc,
        pool_session_id=session_id,
        participants=participant_count,
    )
    db.add(booking)
    db.flush()
    booking.hold_expires_at = now + timedelta(minutes=_active_hold_minutes(db, channel))
    _transition(
        db,
        booking,
        BookingStatus.held,
        actor,
        "Booking hold created",
        {"channel": channel.value, "amount": str(amount)},
    )
    db.add(AuditLog(
        actor_id=actor.id,
        action="booking.create",
        entity="booking",
        entity_id=booking.ref,
        after={"status": BookingStatus.held.value, "channel": channel.value, "total_amount": str(amount)},
    ))
    db.flush()
    return booking


def perform_booking_action(
    db: Session,
    booking: Booking,
    actor: User,
    action: str,
    reason: str,
    minutes: int | None = None,
) -> None:
    now = datetime.now(UTC)
    if action == "extend":
        if booking.status != BookingStatus.held or not booking.hold_expires_at:
            raise HTTPException(409, "Only an active held booking can be extended")
        expiry = _as_utc(booking.hold_expires_at)
        if expiry <= now:
            _transition(db, booking, BookingStatus.expired, None, "Hold expired")
            db.flush()
            db.commit()
            raise HTTPException(409, "This hold has expired and cannot be extended")
        previous_expiry = expiry
        booking.hold_expires_at = max(previous_expiry, now) + timedelta(minutes=minutes or 30)
        db.add(BookingEvent(
            booking_id=booking.id,
            actor_id=actor.id,
            from_status=BookingStatus.held,
            to_status=BookingStatus.held,
            reason=reason,
            data={"hold_expires_at": booking.hold_expires_at.isoformat()},
        ))
        record(
            db, actor, "booking.extend_hold", "booking", booking.ref,
            before={"hold_expires_at": previous_expiry.isoformat()},
            after={"hold_expires_at": booking.hold_expires_at.isoformat()},
            reason=reason,
        )
    elif action == "release":
        previous = booking.status
        _transition(db, booking, BookingStatus.cancelled, actor, reason, {"action": "release"})
        record(db, actor, "booking.release", "booking", booking.ref,
               before={"status": previous.value}, after={"status": "cancelled"}, reason=reason)
    elif action == "cancel":
        previous = booking.status
        _transition(db, booking, BookingStatus.cancelled, actor, reason)
        record(db, actor, "booking.cancel", "booking", booking.ref,
               before={"status": previous.value}, after={"status": "cancelled"}, reason=reason)
    else:
        raise ValueError(f"Unknown booking action: {action}")
    db.flush()


def booking_output(db: Session, booking: Booking, include_events: bool = False) -> dict:
    contact = db.get(CustomerContact, booking.customer_contact_id)
    session = db.get(PoolSession, booking.pool_session_id) if booking.pool_session_id else None
    result = {
        "id": booking.id,
        "ref": booking.ref,
        "facility_id": booking.facility_id,
        "channel": booking.channel.value,
        "status": booking.status.value,
        "customer": {
            "name": contact.name,
            "phone": contact.phone,
            "address": contact.address,
        },
        "created_at": _as_utc(booking.created_at).isoformat() if booking.created_at else None,
        "hold_expires_at": _as_utc(booking.hold_expires_at).isoformat() if booking.hold_expires_at else None,
        "total_amount": str(booking.total_amount),
        "currency": booking.currency,
        "notes": booking.notes,
        "starts_at": _as_utc(booking.starts_at).isoformat() if booking.starts_at else None,
        "ends_at": _as_utc(booking.ends_at).isoformat() if booking.ends_at else None,
        "pool_session_id": booking.pool_session_id,
        "participants": booking.participants,
        "pool_session": {
            "starts_at": _as_utc(session.start_at).isoformat(),
            "ends_at": _as_utc(session.end_at).isoformat(),
        } if session else None,
    }
    if include_events:
        events = db.scalars(
            select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by(BookingEvent.at)
        ).all()
        result["events"] = [{
            "at": event.at.isoformat(),
            "from_status": event.from_status.value if event.from_status else None,
            "to_status": event.to_status.value,
            "reason": event.reason,
            "data": event.data,
        } for event in events]
    return result
