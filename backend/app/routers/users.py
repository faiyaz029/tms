from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record
from ..db import get_db
from ..deps import user_out
from ..models import User
from ..permissions import require_permission
from ..schemas import StaffCreateIn, UserOut
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
               actor: User = Depends(require_permission("users.manage")),
               db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(User))
    rows = db.scalars(select(User).order_by(User.id).offset((page - 1) * size).limit(size)).all()
    return {"items": [user_out(u) for u in rows], "total": total, "page": page, "size": size}


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: StaffCreateIn, actor: User = Depends(require_permission("users.manage")),
                db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    u = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name,
             role=body.role, phone=body.phone, address=body.address)
    db.add(u)
    db.flush()
    record(db, actor, "user.create", "user", u.id, after={"email": email, "role": body.role.value})
    db.commit()
    return user_out(u)


@router.patch("/{user_id}/active", response_model=UserOut)
def set_active(user_id: int, active: bool,
               actor: User = Depends(require_permission("users.manage")),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == actor.id:
        raise HTTPException(400, "You cannot disable your own account")
    record(db, actor, "user.set_active", "user", u.id, {"is_active": u.is_active}, {"is_active": active})
    u.is_active = active
    db.commit()
    return user_out(u)
