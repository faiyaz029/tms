from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings as app_settings
from ..db import get_db
from ..models import BusinessSetting, User
from ..permissions import require_permission
from ..schemas import SettingUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/public")
def public_settings(db: Session = Depends(get_db)):
    horizon = BusinessSetting.get_int(db, "booking_horizon_days", 21)
    slot = BusinessSetting.get_int(db, "turf_slot_step_minutes", 30)
    duration = BusinessSetting.get_int(db, "turf_duration_minutes", 60)
    hold_online = BusinessSetting.get_int(db, "hold_minutes_online", 10)
    hold_phone = BusinessSetting.get_int(db, "hold_minutes_phone", 30)
    return {
        "currency": app_settings.currency,
        "timezone": app_settings.business_timezone,
        "business_name": BusinessSetting.get(db, "business_name", "Turf & Pool Manager"),
        "payment_instructions": BusinessSetting.get(db, "payment_instructions", "Please pay using the approved method."),
        "booking_horizon_days": horizon,
        "turf_slot_step_minutes": slot,
        "turf_duration_minutes": duration,
        "hold_minutes_online": hold_online,
        "hold_minutes_phone": hold_phone,
    }


@router.get("")
def list_settings(actor: User = Depends(require_permission("facility.configure")), db: Session = Depends(get_db)):
    rows = db.scalars(select(BusinessSetting).order_by(BusinessSetting.key)).all()
    return {"items": [{"key": r.key, "value": r.value} for r in rows], "total": len(rows), "page": 1, "size": len(rows)}


@router.post("")
def upsert_setting(body: SettingUpdate, actor: User = Depends(require_permission("facility.configure")), db: Session = Depends(get_db)):
    row = db.scalar(select(BusinessSetting).where(BusinessSetting.key == body.key))
    before = {"value": row.value} if row else None
    if row is None:
        row = BusinessSetting(key=body.key, value=str(body.value))
        db.add(row)
    else:
        row.value = str(body.value)
    record(db, actor, "settings.update", "setting", body.key, before, {"value": str(body.value)}, reason=body.reason)
    db.commit()
    return {"key": row.key, "value": row.value}
