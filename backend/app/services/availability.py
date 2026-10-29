from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from ..models import (
    Block, Booking, BookingStatus, BusinessSetting, Facility, FacilityType,
    OperatingSchedule, PoolSession, PoolSessionTemplate, SpecialDay, TurfPrice,
)

TZ = ZoneInfo("Asia/Dhaka")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def turf_price(
    db,
    facility_id: int,
    target_day: date,
    start: datetime,
    end: datetime,
    rules=None,
):
    local_start = start.astimezone(TZ).time().replace(tzinfo=None)
    local_end = end.astimezone(TZ).time().replace(tzinfo=None)
    if rules is None:
        rules = db.scalars(
            select(TurfPrice).where(
                TurfPrice.facility_id == facility_id,
                TurfPrice.is_active.is_(True),
            )
        ).all()
    matching = [
        rule for rule in rules
        if (rule.weekday is None or rule.weekday == target_day.weekday())
        and (rule.start_time is None or rule.start_time <= local_start)
        and (rule.end_time is None or rule.end_time >= local_end)
    ]
    if not matching:
        return None
    matching.sort(
        key=lambda rule: (
            rule.weekday is not None,
            rule.start_time is not None or rule.end_time is not None,
        ),
        reverse=True,
    )
    return matching[0].price


def _setting_int(db, key: str, default: int) -> int:
    value = BusinessSetting.get(db, key)
    return int(value) if value is not None else default


def _facility(db, facility_type: FacilityType) -> Facility | None:
    return db.scalar(
        select(Facility).where(Facility.facility_type == facility_type, Facility.is_active.is_(True))
    )


def _blocks_for_day(db, facility_id: int, target_day: date):
    start = datetime.combine(target_day, time.min, tzinfo=TZ)
    end = datetime.combine(target_day + timedelta(days=1), time.min, tzinfo=TZ)
    return db.scalars(
        select(Block).where(
            Block.facility_id == facility_id,
            Block.starts_at < end,
            Block.ends_at > start,
        )
    ).all()


def _special_days(db, facility_id: int, target_day: date):
    return db.scalars(
        select(SpecialDay)
        .where(
            SpecialDay.date == target_day,
            (SpecialDay.facility_id == facility_id) | (SpecialDay.facility_id.is_(None))
        )
        .order_by(SpecialDay.facility_id.is_(None).desc())
    ).all()


def turf_availability(db, target_day: date | str, reserved_intervals=None):
    if isinstance(target_day, str):
        target_day = date.fromisoformat(target_day)
    facility = _facility(db, FacilityType.turf)
    if not facility:
        return []
    horizon_days = _setting_int(db, "booking_horizon_days", 21)
    step_minutes = _setting_int(db, "turf_slot_step_minutes", 30)
    duration_minutes = _setting_int(db, "turf_duration_minutes", 60)
    if step_minutes < 1 or duration_minutes < 1:
        raise HTTPException(500, "Turf booking settings are invalid")
    today = datetime.now(TZ).date()
    schedule = db.scalar(
        select(OperatingSchedule).where(
            OperatingSchedule.facility_id == facility.id,
            OperatingSchedule.weekday == target_day.weekday(),
        )
    )
    blocked = _blocks_for_day(db, facility.id, target_day)
    if schedule is None:
        return []

    effective_open, effective_close = schedule.open_time, schedule.close_time
    closed = schedule.is_closed
    for special in _special_days(db, facility.id, target_day):
        closed = special.is_closed
        if special.open_time is not None:
            effective_open = special.open_time
        if special.close_time is not None:
            effective_close = special.close_time
    outside_horizon = target_day < today or target_day > today + timedelta(days=horizon_days)

    if reserved_intervals is None:
        reserved_intervals = [
            {
                "start": _as_utc(booking.starts_at).astimezone(TZ),
                "end": _as_utc(booking.ends_at).astimezone(TZ),
                "status": booking.status.value,
            }
            for booking in db.scalars(
                select(Booking).where(
                    Booking.facility_id == facility.id,
                    Booking.starts_at < datetime.combine(target_day + timedelta(days=1), time.min, tzinfo=TZ),
                    Booking.ends_at > datetime.combine(target_day, time.min, tzinfo=TZ),
                    or_(
                        Booking.status == BookingStatus.confirmed,
                        (Booking.status == BookingStatus.held)
                        & (Booking.hold_expires_at > func.now()),
                    ),
                )
            ).all()
        ]
    price_rules = db.scalars(
        select(TurfPrice).where(
            TurfPrice.facility_id == facility.id,
            TurfPrice.is_active.is_(True),
        )
    ).all()
    open_time = datetime.combine(target_day, effective_open, tzinfo=TZ)
    close_time = datetime.combine(target_day, effective_close, tzinfo=TZ)
    day_slots: list[dict] = []
    cursor = open_time
    while cursor + timedelta(minutes=duration_minutes) <= close_time:
        slot_end = cursor + timedelta(minutes=duration_minutes)
        if outside_horizon:
            status = "beyond_horizon"
        elif closed:
            status = "closed"
        else:
            status = "free"
        if status == "free":
            for block in blocked:
                if cursor < _as_utc(block.ends_at).astimezone(TZ) and slot_end > _as_utc(block.starts_at).astimezone(TZ):
                    status = "blocked"
                    break
        if status == "free":
            for item in reserved_intervals:
                start_i = item["start"] if isinstance(item, dict) else item[0]
                end_i = item["end"] if isinstance(item, dict) else item[1]
                if cursor < end_i and slot_end > start_i:
                    status = item.get("status", "held") if isinstance(item, dict) else "held"
                    break
        price = (
            turf_price(db, facility.id, target_day, cursor, slot_end, price_rules)
            if status in {"free", "held", "confirmed"}
            else None
        )
        day_slots.append({
            "date": target_day.isoformat(),
            "facility_id": facility.id,
            "start": cursor.isoformat(),
            "end": slot_end.isoformat(),
            "status": status,
            "price": str(price) if price is not None else None,
        })
        cursor += timedelta(minutes=step_minutes)
    return day_slots


def pool_availability(db, target_day: date | str, reserved_map: dict | None = None):
    if isinstance(target_day, str):
        target_day = date.fromisoformat(target_day)
    facility = _facility(db, FacilityType.pool)
    if not facility:
        return []
    templates = db.scalars(
        select(PoolSessionTemplate).where(
            PoolSessionTemplate.facility_id == facility.id,
            PoolSessionTemplate.weekday == target_day.weekday(),
            PoolSessionTemplate.is_active.is_(True),
        )
    ).all()
    reserved_map = reserved_map or {}
    sessions = []
    today = datetime.now(TZ).date()
    beyond_horizon = target_day < today or target_day > today + timedelta(
        days=_setting_int(db, "booking_horizon_days", 21)
    )
    schedule = db.scalar(
        select(OperatingSchedule).where(
            OperatingSchedule.facility_id == facility.id,
            OperatingSchedule.weekday == target_day.weekday(),
        )
    )
    special_days = db.scalars(
        select(SpecialDay)
        .where(
            SpecialDay.date == target_day,
            or_(SpecialDay.facility_id == facility.id, SpecialDay.facility_id.is_(None)),
        )
        .order_by(SpecialDay.facility_id.is_(None).desc())
    ).all()
    closed = schedule is None or schedule.is_closed
    open_time = schedule.open_time if schedule else None
    close_time = schedule.close_time if schedule else None
    for special in special_days:
        closed = special.is_closed
        if special.open_time is not None:
            open_time = special.open_time
        if special.close_time is not None:
            close_time = special.close_time
    for template in templates:
        start_at = datetime.combine(target_day, template.start_time, tzinfo=TZ)
        end_at = datetime.combine(target_day, template.end_time, tzinfo=TZ)
        session = None
        if not beyond_horizon:
            session = db.scalar(
                select(PoolSession).where(
                    PoolSession.facility_id == facility.id,
                    PoolSession.date == target_day,
                    PoolSession.start_at == start_at,
                )
            )
            if session is None:
                session = PoolSession(
                    facility_id=facility.id,
                    date=target_day,
                    start_at=start_at,
                    end_at=end_at,
                    capacity=template.capacity,
                    price_per_person=template.price_per_person,
                )
                try:
                    with db.begin_nested():
                        db.add(session)
                        db.flush()
                except IntegrityError:
                    session = db.scalar(
                        select(PoolSession).where(
                            PoolSession.facility_id == facility.id,
                            PoolSession.date == target_day,
                            PoolSession.start_at == start_at,
                        )
                    )
                    if session is None:
                        raise
        actual_reserved = db.scalar(
            select(func.coalesce(func.sum(Booking.participants), 0)).where(
                Booking.pool_session_id == session.id,
                or_(
                    Booking.status == BookingStatus.confirmed,
                    (Booking.status == BookingStatus.held)
                    & (Booking.hold_expires_at > func.now()),
                ),
            )
        ) if session else 0
        reserved_override = reserved_map.get(session.id, 0) if session else 0
        reserved = max(int(actual_reserved or 0), int(reserved_override))
        capacity = session.capacity if session else template.capacity
        price_per_person = session.price_per_person if session else template.price_per_person
        remaining = max(capacity - reserved, 0)
        status = "open" if remaining > 0 else "full"
        if beyond_horizon:
            status = "beyond_horizon"
        elif closed:
            status = "closed"
        elif (
            open_time is None
            or close_time is None
            or template.start_time < open_time
            or template.end_time > close_time
        ):
            status = "outside_hours"
        else:
            blocks = db.scalars(
                select(Block).where(
                    Block.facility_id == facility.id,
                    Block.starts_at < end_at,
                    Block.ends_at > start_at,
                )
            ).all()
            if blocks:
                status = "blocked"
        sessions.append({
            "id": session.id if session else None,
            "facility_id": facility.id,
            "date": target_day.isoformat(),
            "start": (session.start_at if session else start_at).isoformat(),
            "end": (session.end_at if session else end_at).isoformat(),
            "capacity": capacity,
            "reserved": reserved,
            "remaining": remaining,
            "price_per_person": str(price_per_person),
            "status": status,
        })
    if db.new:
        db.commit()
    return sessions
