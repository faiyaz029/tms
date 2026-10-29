import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ExpenseCategory, PaymentMethod, Role, User
from app.security import hash_password


TEST_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def postgres_test_engine():
    if not TEST_URL:
        yield None
        return
    previous_url = os.environ.get("ALEMBIC_DATABASE_URL")
    os.environ["ALEMBIC_DATABASE_URL"] = TEST_URL
    try:
        alembic_config = Config("alembic.ini")
        command.upgrade(alembic_config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("ALEMBIC_DATABASE_URL", None)
        else:
            os.environ["ALEMBIC_DATABASE_URL"] = previous_url
    engine = create_engine(TEST_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(postgres_test_engine):
    if postgres_test_engine:
        eng = postgres_test_engine
        table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        with eng.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
        s = sessionmaker(bind=eng, expire_on_commit=False)()
    else:
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(eng)
        s = sessionmaker(bind=eng, expire_on_commit=False)()
    s.add_all([
        PaymentMethod(code="cash", label="Cash", is_active=True, requires_reference=False),
        PaymentMethod(code="bkash", label="bKash", is_active=True, requires_reference=True),
        PaymentMethod(code="bank_transfer", label="Bank transfer", is_active=True, requires_reference=True),
        PaymentMethod(code="card", label="Card", is_active=True, requires_reference=False),
        PaymentMethod(code="other", label="Other", is_active=True, requires_reference=False),
        PaymentMethod(code="online_simulated", label="Online (SIMULATED)", is_active=True, requires_reference=False),
    ])
    s.add_all([
        ExpenseCategory(code="electricity", label="Electricity", is_active=True),
        ExpenseCategory(code="cleaning", label="Cleaning", is_active=True),
        ExpenseCategory(code="maintenance", label="Maintenance", is_active=True),
        ExpenseCategory(code="supplies", label="Supplies", is_active=True),
        ExpenseCategory(code="salary", label="Salary", is_active=True),
        ExpenseCategory(code="other", label="Other", is_active=True),
    ])
    s.commit()
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
