import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import google
from ..audit import record
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, user_out
from ..models import PasswordResetToken, Role, User, utcnow
from ..schemas import (
    ForgotPasswordIn, GoogleIn, LoginIn, ProfileIn, RegisterIn, ResetPasswordIn, UserOut,
)
from ..security import create_token, hash_password, verify_password
from ..services.email import issue_password_reset, rate_limit_reset_request

router = APIRouter(prefix="/auth", tags=["auth"])

_fails: dict[str, list[float]] = {}  # in-memory limiter; use Redis if you run several servers
MAX_FAILS, WINDOW = 5, 15 * 60


def _blocked(key: str) -> bool:
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < WINDOW]
    return len(_fails[key]) >= MAX_FAILS


def _set_cookies(resp: Response, user: User) -> None:
    kw = dict(samesite="lax", secure=settings.cookie_secure,
              max_age=settings.access_token_minutes * 60)
    resp.set_cookie("access_token", create_token(user.id), httponly=True, **kw)
    resp.set_cookie("csrf_token", secrets.token_urlsafe(24), httponly=False, **kw)


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, resp: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, password_hash=hash_password(body.password),
                full_name=body.full_name.strip(), phone=body.phone,
                address=body.address.strip(), role=Role.customer)
    db.add(user)
    db.flush()
    record(db, user, "user.register", "user", user.id)
    db.commit()
    _set_cookies(resp, user)
    return user_out(user)


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, resp: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}:{body.email.lower()}"
    if _blocked(key):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes")
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _fails.setdefault(key, []).append(time.time())
        raise HTTPException(401, "Incorrect email or password")
    _fails.pop(key, None)
    _set_cookies(resp, user)
    return user_out(user)


@router.post("/forgot-password", status_code=202)
def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    email = str(body.email).strip().lower()
    client_host = request.client.host if request.client else "unknown"
    secret = settings.secret_key.encode()
    account_key = hmac.new(
        secret, f"account:{email}:{client_host}".encode(), hashlib.sha256,
    ).hexdigest()
    ip_key = hmac.new(
        secret, f"ip:{client_host}".encode(), hashlib.sha256,
    ).hexdigest()
    now = datetime.now(timezone.utc)
    account_allowed = rate_limit_reset_request(db, account_key, now)
    ip_allowed = rate_limit_reset_request(db, ip_key, now)
    db.commit()
    if account_allowed and ip_allowed:
        background_tasks.add_task(issue_password_reset, email)
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    reset = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .with_for_update()
    )
    now = utcnow()
    expires_at = reset.expires_at if reset else None
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not reset or reset.used_at or not expires_at or expires_at <= now:
        raise HTTPException(400, "This reset link is invalid or expired")
    user = db.get(User, reset.user_id)
    if not user or not user.is_active:
        raise HTTPException(400, "This reset link is invalid or expired")

    reset.used_at = now
    for other in db.scalars(
        select(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.id != reset.id,
        )
        .with_for_update()
    ):
        other.used_at = now
    user.password_hash = hash_password(body.password)
    record(
        db, user, "user.password_reset", "user", user.id,
        after={"password_reset": True},
    )
    db.commit()
    return {"message": "Password updated. Sign in with your new password."}


@router.post("/google", response_model=UserOut)
def google_login(body: GoogleIn, resp: Response, db: Session = Depends(get_db)):
    info = google.verify_google_token(body.credential)
    sub, email = info["sub"], info["email"].lower()
    user = db.scalar(select(User).where(User.google_sub == sub)) or \
        db.scalar(select(User).where(User.email == email))
    if user and not user.is_active:
        raise HTTPException(403, "This account is disabled")
    if not user:  # new customer; phone and address are still required before booking
        user = User(email=email, google_sub=sub, full_name=info.get("name") or email,
                    role=Role.customer)
        db.add(user)
        db.flush()
        record(db, user, "user.register_google", "user", user.id)
    elif not user.google_sub:
        user.google_sub = sub
    db.commit()
    _set_cookies(resp, user)
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(resp: Response):
    resp.delete_cookie("access_token")
    resp.delete_cookie("csrf_token")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/profile", response_model=UserOut)
def update_profile(body: ProfileIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    before = {"phone": user.phone, "address": user.address, "full_name": user.full_name}
    user.phone, user.address = body.phone, body.address.strip()
    if body.full_name:
        user.full_name = body.full_name.strip()
    record(db, user, "user.profile_update", "user", user.id, before,
           {"phone": user.phone, "address": user.address, "full_name": user.full_name})
    db.commit()
    return user_out(user)
