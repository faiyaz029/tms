from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record
from ..db import get_db
from ..models import Facility, FacilityType, User
from ..permissions import require_permission

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get("")
def list_facilities(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                   actor: User = Depends(require_permission("facility.configure")), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(Facility))
    rows = db.scalars(select(Facility).order_by(Facility.id).offset((page - 1) * size).limit(size)).all()
    return {"items": [{"id": r.id, "name": r.name, "facility_type": r.facility_type.value, "is_active": r.is_active} for r in rows], "total": total, "page": page, "size": size}


@router.post("")
def create_facility(body: dict, actor: User = Depends(require_permission("facility.configure")), db: Session = Depends(get_db)):
    facility_type = body.get("facility_type")
    name = (body.get("name") or "").strip()
    if facility_type not in {"turf", "pool"}:
        raise HTTPException(400, "facility_type must be turf or pool")
    if not name:
        raise HTTPException(400, "name is required")
    facility = Facility(facility_type=FacilityType(facility_type), name=name, is_active=True)
    db.add(facility)
    db.flush()
    record(db, actor, "facility.create", "facility", facility.id, after={"name": name, "facility_type": facility_type})
    db.commit()
    return {"id": facility.id, "name": facility.name, "facility_type": facility.facility_type.value, "is_active": facility.is_active}
