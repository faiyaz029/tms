import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Role, User
from app.security import hash_password


TEST_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture()
def db():
    if TEST_URL:
        eng = create_engine(TEST_URL, pool_pre_ping=True)
        Base.metadata.create_all(eng)
        s = sessionmaker(bind=eng, expire_on_commit=False)()
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(eng)
        s = sessionmaker(bind=eng, expire_on_commit=False)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client(db):
    from app.routers import auth
    auth._fails.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(db, email, role, pw="password123"):
    u = User(email=email, full_name=email.split("@")[0].title(),
             password_hash=hash_password(pw), role=role)
    db.add(u)
    db.commit()
    return u


def login(client, email, pw="password123"):
    r = client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


@pytest.fixture()
def owner_headers(client, db):
    make_user(db, "owner@x.com", Role.owner)
    return login(client, "owner@x.com")
