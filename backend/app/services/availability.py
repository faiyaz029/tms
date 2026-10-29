from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..models import Block, BusinessSetting, Facility, FacilityType, OperatingSchedule, PoolSessionTemplate, SpecialDay

TZ = ZoneInfo("Asia/Dhaka")


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


def _special_day(db, facility_id: int | None, target_day: date):
    return db.scalar(
        select(SpecialDay).where(
            SpecialDay.date == target_day,
            (SpecialDay.facility_id == facility_id) | (SpecialDay.facility_id.is_(None))
        )
    )


def turf_availability(db, target_day: date | str, reserved_intervals=None):
    if isinstance(target_day, str):
        target_day = date.fromisoformat(target_day)
    facility = _facility(db, FacilityType.turf)
    if not facility:
        return []
    horizon_days = _setting_int(db, "booking_horizon_days", 21)
    step_minutes = _setting_int(db, "turf_slot_step_minutes", 30)
    duration_minutes = _setting_int(db, "turf_duration_minutes", 60)
    today = datetime.now(TZ).date()
    schedule = db.scalar(
        select(OperatingSchedule).where(
            OperatingSchedule.facility_id == facility.id,
            OperatingSchedule.weekday == target_day.weekday(),
        )
    )
    special = _special_day(db, facility.id, target_day)
    blocked = _blocks_for_day(db, facility.id, target_day)

    effective_open = schedule.open_time if schedule and not schedule.is_closed else None
    effective_close = schedule.close_time if schedule and not schedule.is_closed else None
    if special:
        if special.is_closed:
            effective_open = None
            effective_close = None
        else:
            if special.open_time is not None:
                effective_open = special.open_time
            if special.close_time is not None:
                effective_close = special.close_time

    day_slots = []
    if target_day > today + timedelta(days=horizon_days):
        if schedule and not schedule.is_closed:
            open_dt = datetime.combine(target_day, schedule.open_time, tzinfo=TZ)
            close_dt = datetime.combine(target_day, schedule.close_time, tzinfo=TZ)
            cursor = open_dt
            while cursor + timedelta(minutes=duration_minutes) <= close_dt:
                slot_end = cursor + timedelta(minutes=duration_minutes)
                day_slots.append({
                    "date": target_day.isoformat(),
                    "start": cursor.isoformat(),
                    "end": slot_end.isoformat(),
                    "status": "beyond_horizon",
                })
                cursor += timedelta(minutes=step_minutes)
        return day_slots

    if schedule is None or schedule.is_closed or effective_open is None or effective_close is None:
        return []

    if reserved_intervals is None:
        reserved_intervals = []
    open_time = datetime.combine(target_day, effective_open, tzinfo=TZ)
    close_time = datetime.combine(target_day, effective_close, tzinfo=TZ)
    cursor = open_time
    while cursor + timedelta(minutes=duration_minutes) <= close_time:
        slot_end = cursor + timedelta(minutes=duration_minutes)
        status = "free"
        for block in blocked:
            if cursor < block.ends_at and slot_end > block.starts_at:
                status = "blocked"
                break
        if status == "free":
            for item in reserved_intervals:
                start_i = item["start"] if isinstance(item, dict) else item[0]
                end_i = item["end"] if isinstance(item, dict) else item[1]
                if cursor < end_i and slot_end > start_i:
                    status = item.get("status", "held") if isinstance(item, dict) else "held"
                    break
        day_slots.append({
            "date": target_day.isoformat(),
            "start": cursor.isoformat(),
            "end": slot_end.isoformat(),
            "status": status,
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
    for template in templates:
        start_at = datetime.combine(target_day, template.start_time, tzinfo=TZ)
        end_at = datetime.combine(target_day, template.end_time, tzinfo=TZ)
        reserved = reserved_map.get(template.id, 0)
        remaining = max(template.capacity - reserved, 0)
        sessions.append({
            "id": template.id,
            "facility_id": facility.id,
            "date": target_day.isoformat(),
            "start": start_at.isoformat(),
            "end": end_at.isoformat(),
            "capacity": template.capacity,
            "reserved": reserved,
            "remaining": remaining,
            "price_per_person": str(template.price_per_person),
            "status": "full" if remaining <= 0 else "open",
        })
    return sessions
