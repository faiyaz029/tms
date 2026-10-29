from app.models import AuditLog, Role
from app.permissions import has_permission
from tests.conftest import login, make_user

REG = {"email": "Cust@x.com", "password": "password123", "full_name": "Cust Omer",
       "phone": "+8801712345678", "address": "House 1, Road 2, Khulna"}


def test_register_normalizes_phone_and_signs_in(client):
    r = client.post("/api/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert body["phone"] == "01712345678" and body["role"] == "customer" and body["profile_complete"]
    assert client.get("/api/auth/me").status_code == 200


def test_register_rejects_bad_phone_and_short_address(client):
    assert client.post("/api/auth/register", json={**REG, "phone": "12345"}).status_code == 422
    assert client.post("/api/auth/register", json={**REG, "address": "abc"}).status_code == 422


def test_duplicate_email(client):
    client.post("/api/auth/register", json=REG)
    assert client.post("/api/auth/register", json={**REG, "email": "cust@x.com"}).status_code == 409


def test_login_wrong_password_and_rate_limit(client, db):
    make_user(db, "a@x.com", Role.staff)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "a@x.com", "password": "bad-pass-1"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "a@x.com", "password": "password123"})
    assert r.status_code == 429


def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_required_on_unsafe_requests(client, db):
    make_user(db, "o@x.com", Role.owner)
    login(client, "o@x.com")
    p = {"email": "s@x.com", "password": "password123", "full_name": "Sam Staff", "role": "staff"}
    assert client.post("/api/users", json=p).status_code == 403


def test_owner_creates_staff_but_not_customers(client, owner_headers):
    p = {"email": "s@x.com", "password": "password123", "full_name": "Sam Staff", "role": "accountant"}
    assert client.post("/api/users", json=p, headers=owner_headers).status_code == 201
    r = client.post("/api/users", json={**p, "email": "c@x.com", "role": "customer"}, headers=owner_headers)
    assert r.status_code == 422


def test_non_owner_cannot_manage_users(client, db):
    for role in (Role.admin, Role.staff, Role.accountant, Role.shareholder, Role.customer):
        make_user(db, f"{role.value}@x.com", role)
        h = login(client, f"{role.value}@x.com")
        assert client.get("/api/users").status_code == 403
        p = {"email": "n@x.com", "password": "password123", "full_name": "New User", "role": "staff"}
        assert client.post("/api/users", json=p, headers=h).status_code == 403
        client.post("/api/auth/logout", headers=h)


def test_shareholder_is_read_only_and_cannot_book():
    for perm in ("booking.create_self", "booking.create_for_customer", "payment.record",
                 "payment.verify", "expense.enter", "report.approve", "shareholder.manage"):
        assert not has_permission(Role.shareholder, perm)
    assert has_permission(Role.shareholder, "report.view_approved")


def test_staff_cannot_verify_payments_or_approve_reports():
    assert not has_permission(Role.staff, "payment.verify")
    assert not has_permission(Role.staff, "report.approve")
    assert has_permission(Role.owner, "report.approve")


def test_google_login_creates_incomplete_profile_then_completes(client, monkeypatch):
    from app import google
    monkeypatch.setattr(google, "verify_google_token", lambda c: {
        "sub": "g-1", "email": "g@gmail.com", "name": "Gina", "email_verified": True})
    r = client.post("/api/auth/google", json={"credential": "x"})
    assert r.status_code == 200 and r.json()["profile_complete"] is False
    h = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    r = client.patch("/api/auth/profile", json={"phone": "01912345678", "address": "Sonadanga, Khulna"}, headers=h)
    assert r.status_code == 200 and r.json()["profile_complete"] is True


def test_profile_update_writes_audit_log(client, db):
    client.post("/api/auth/register", json=REG)
    h = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    client.patch("/api/auth/profile", json={"phone": "01812345678", "address": "New address, Khulna"}, headers=h)
    assert db.query(AuditLog).filter_by(action="user.profile_update").count() == 1
