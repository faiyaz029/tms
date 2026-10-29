"""Create the first owner:
    python -m app.cli create-owner --email you@example.com --name "Your Name"
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from .audit import record
from .db import SessionLocal
from .models import Role, User
from .security import hash_password


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["create-owner"])
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--password")
    a = p.parse_args()
    pw = a.password or getpass.getpass("Password (min 8 chars): ")
    if len(pw) < 8:
        sys.exit("Password must be at least 8 characters")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == a.email.lower())):
            sys.exit("A user with that email already exists")
        u = User(email=a.email.lower(), full_name=a.name,
                 password_hash=hash_password(pw), role=Role.owner)
        db.add(u)
        db.flush()
        record(db, None, "user.create_owner_cli", "user", u.id)
        db.commit()
    print("Owner created. You can now sign in.")


if __name__ == "__main__":
    main()
