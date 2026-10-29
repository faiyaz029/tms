from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..permissions import require_permission
from ..services.availability import pool_availability, turf_availability

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("/turf")
def turf(date: date = Query(...), db: Session = Depends(get_db), actor: User = Depends(require_permission("timetable.view"))):
    return turf_availability(db, date)


@router.get("/pool")
def pool(date: date = Query(...), db: Session = Depends(get_db), actor: User = Depends(require_permission("timetable.view"))):
    return pool_availability(db, date)
