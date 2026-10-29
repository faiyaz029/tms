import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

ALGO = "HS256"
BD_PHONE = re.compile(r"^(?:\+?88)?(01[3-9]\d{8})$")


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm=ALGO)


def decode_token(token: str) -> int | None:
    try:
        return int(jwt.decode(token, settings.secret_key, algorithms=[ALGO])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def normalize_bd_phone(raw: str) -> str:
    m = BD_PHONE.match(raw.strip().replace(" ", "").replace("-", ""))
    if not m:
        raise ValueError("Enter a valid Bangladeshi mobile number, like 01712345678")
    return m.group(1)
