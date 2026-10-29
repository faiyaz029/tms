import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .permissions import permissions_for
from .schemas import UserOut
from .security import decode_token

SAFE = {"GET", "HEAD", "OPTIONS"}


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, phone=u.phone,
                   address=u.address, role=u.role, is_active=u.is_active,
                   profile_complete=u.profile_complete, permissions=permissions_for(u.role))


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    uid = decode_token(token) if token else None
    user = db.get(User, uid) if uid else None
    if not user or not user.is_active:
        raise HTTPException(401, "Please sign in")
    if request.method not in SAFE:  # CSRF double-submit check for cookie auth
        cookie = request.cookies.get("csrf_token", "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not secrets.compare_digest(cookie, header):
            raise HTTPException(403, "Security check failed. Refresh the page and try again")
    return user


def require_complete_profile(user: User = Depends(get_current_user)) -> User:
    """Use on booking endpoints: phone and address must be on file."""
    if not user.profile_complete:
        raise HTTPException(403, "Add your phone number and address before booking")
    return user
