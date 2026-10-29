import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Booking, BookingChannel, BookingStatus, CustomerContact, Expense,
    ExpenseEvent, ExpenseStatus, Facility, FacilityType, OperatingSchedule,
    Payment, PaymentStatus, Role, TurfPrice, User,
)
from app.services.expenses import create_expense
from tests.conftest import login, make_user

TZ = ZoneInfo("Asia/Dhaka")


def _setup_turf(db):
    turf = Facility(facility_type=FacilityType.turf, name="Main Turf", is_active=True)
    db.add(turf)
    db.flush()
    for weekday in range(7):
        db.add(OperatingSchedule(
            facility_id=turf.id,
            weekday=weekday,
            open_time=time(10),
            close_time=time(22),
            is_closed=False,
        ))
    db.add(TurfPrice(
        facility_id=turf.id,
        weekday=None,
        start_time=None,
        end_time=None,
        price=Decimal("2000.00"),
        is_active=True,
    ))
    db.commit()
    return turf


def _staff_booking(client, db, turf, headers):
    start = datetime.combine(
        datetime.now(TZ).date() + timedelta(days=1), time(11), tzinfo=TZ,
    )
    response = client.post("/api/bookings/staff", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": start.isoformat(),
        "customer_name": "Expense Test Contact",
        "customer_phone": "01812345678",
        "channel": "phone",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _expense_body(business_day=None, **changes):
    day = business_day or datetime.now(TZ).date()
    return {
        "expense_date": day.isoformat(),
        "payment_date": day.isoformat(),
        "category": "electricity",
        "description": "Monthly electricity bill",
        "amount": "1250.50",
        "method": "cash",
        "vendor": "City Electric",
        "memo_no": "MEMO-42",
        "has_physical_memo": True,
        "trx_id": "MFS-EXP-42",
        "bank_ref": "BANK-42",
        "sms_text": "Payment alert text",
        "notes": "Meter 123",
        **changes,
    }


def _create_expense(client, headers, body=None):
    response = client.post("/api/expenses", headers=headers, json=body or _expense_body())
    assert response.status_code == 201, response.text
    return response.json()


def test_expense_reference_search_and_memo_fields(client, db):
    staff = make_user(db, "staff@expense.example", Role.staff)
    headers = login(client, staff.email)
    created = _create_expense(client, headers)
    assert created["ref"].startswith("EXP-")
    assert created["status"] == "pending"
    assert created["has_physical_memo"] is True
    assert len(created["events"]) == 1

    filters = (
        {"ref": created["ref"][-4:]},
        {"date_from": created["expense_date"], "date_to": created["expense_date"]},
        {"amount": "1250.50"},
        {"category": "electricity"},
        {"vendor": "City"},
        {"method": "cash"},
        {"trx_id": "MFS-EXP"},
        {"memo_no": "MEMO-42"},
        {"status": "pending"},
    )
    for params in filters:
        response = client.get("/api/expenses", headers=headers, params=params)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [created["id"]]
    details = client.get(f"/api/expenses/{created['ref']}", headers=headers)
    assert details.status_code == 200
    assert details.json()["vendor"] == "City Electric"

    without_memo = _create_expense(client, headers, _expense_body(
        description="Cash supplies",
        amount="40.00",
        vendor=None,
        memo_no=None,
        has_physical_memo=False,
        trx_id=None,
        bank_ref=None,
        sms_text=None,
    ))
    assert without_memo["memo_no"] is None
    assert without_memo["has_physical_memo"] is False


def test_expense_approval_rejection_and_correction_history(client, db):
    staff = make_user(db, "staff@expense-history.example", Role.staff)
    headers = login(client, staff.email)
    expense = _create_expense(client, headers)
    forbidden = client.post(f"/api/expenses/{expense['id']}/approve", headers=headers)
    assert forbidden.status_code == 403

    client.post("/api/auth/logout", headers=headers)
    accountant = make_user(db, "accountant@expense-history.example", Role.accountant)
    accountant_headers = login(client, accountant.email)
    approved = client.post(
        f"/api/expenses/{expense['id']}/approve",
        headers=accountant_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    client.post("/api/auth/logout", headers=accountant_headers)
    headers = login(client, staff.email)
    corrected = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"amount": "1300.00", "reason": "Corrected meter reading"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["status"] == "pending"
    assert corrected.json()["approved_by"] is None
    assert corrected.json()["amount"] == "1300.00"
    assert corrected.json()["events"][-1]["before"]["status"] == "approved"
    assert corrected.json()["events"][-1]["reason"] == "Corrected meter reading"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "expense.correct"))

    rejected = _create_expense(client, headers, _expense_body(
        description="Cleaning supplies",
        amount="100.00",
    ))
    client.post("/api/auth/logout", headers=headers)
    accountant_headers = login(client, accountant.email)
    reject_response = client.post(
        f"/api/expenses/{rejected['id']}/reject",
        headers=accountant_headers,
        json={"reason": "Receipt is not attached"},
    )
    assert reject_response.status_code == 200, reject_response.text
    assert reject_response.json()["status"] == "rejected"
    events = client.get(
        f"/api/expenses/{rejected['ref']}",
        headers=accountant_headers,
    ).json()["events"]
    assert [event["action"] for event in events] == ["created", "rejected"]


def test_expense_enterer_cannot_approve_and_permissions_are_role_aware(client, db):
    owner = make_user(db, "owner@expense.example", Role.owner)
    owner_headers = login(client, owner.email)
    expense = _create_expense(client, owner_headers)
    own_approval = client.post(
        f"/api/expenses/{expense['id']}/approve",
        headers=owner_headers,
    )
    assert own_approval.status_code == 409

    for role, expected in (
        (Role.owner, 200),
        (Role.admin, 200),
        (Role.staff, 200),
        (Role.accountant, 200),
        (Role.shareholder, 403),
        (Role.customer, 403),
    ):
        client.post("/api/auth/logout", headers=owner_headers)
        user = make_user(db, f"{role.value}@expense-roles.example", role)
        role_headers = login(client, user.email)
        assert client.get("/api/expenses", headers=role_headers).status_code == expected
        client.post("/api/auth/logout", headers=role_headers)


def test_closing_totals_review_and_correction_versions(client, db):
    turf = _setup_turf(db)
    staff = make_user(db, "staff@closing.example", Role.staff)
    staff_headers = login(client, staff.email)
    booking = _staff_booking(client, db, turf, staff_headers)
    business_day = datetime.now(TZ).date() - timedelta(days=1)
    db.get(Booking, booking["id"]).created_at = datetime.combine(
        business_day, time(12), tzinfo=TZ,
    ).astimezone(timezone.utc)
    db.commit()
    payment_response = client.post(
        f"/api/bookings/{booking['id']}/payments",
        headers=staff_headers,
        json={
            "amount": "500.00",
            "method": "cash",
            "received_at": datetime.combine(
                business_day, time(13), tzinfo=TZ,
            ).isoformat(),
        },
    )
    assert payment_response.status_code == 201, payment_response.text

    client.post("/api/auth/logout", headers=staff_headers)
    accountant = make_user(db, "accountant@closing.example", Role.accountant)
    accountant_headers = login(client, accountant.email)
    verified = client.post(
        f"/api/payments/{payment_response.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert verified.status_code == 200, verified.text

    client.post("/api/auth/logout", headers=accountant_headers)
    staff_headers = login(client, staff.email)
    approved_expense = _create_expense(
        client, staff_headers, _expense_body(business_day, amount="300.00"),
    )
    pending_expense = _create_expense(
        client, staff_headers, _expense_body(
            business_day, description="Pending cleaning materials", amount="80.00",
        ),
    )
    rejected_expense = _create_expense(
        client, staff_headers, _expense_body(
            business_day, description="Rejected repair claim", amount="50.00",
        ),
    )
    client.post("/api/auth/logout", headers=staff_headers)
    accountant_headers = login(client, accountant.email)
    approved = client.post(
        f"/api/expenses/{approved_expense['id']}/approve",
        headers=accountant_headers,
    )
    assert approved.status_code == 200
    rejected = client.post(
        f"/api/expenses/{rejected_expense['id']}/reject",
        headers=accountant_headers,
        json={"reason": "Not a business expense"},
    )
    assert rejected.status_code == 200

    preview = client.get(
        f"/api/closings/totals?business_date={business_day.isoformat()}",
        headers=accountant_headers,
    )
    assert preview.status_code == 200, preview.text
    totals = preview.json()
    assert totals["bookings"]["created"] == 1
    assert totals["collections_by_method"]["cash"]["verified_amount"] == "500.00"
    assert totals["expenses_by_method"]["cash"]["amount"] == "300.00"
    assert totals["pending_verifications"]["count"] == 0
    assert totals["pending_approvals"] == {"count": 1, "amount": "80.00"}

    client.post("/api/auth/logout", headers=accountant_headers)
    staff_headers = login(client, staff.email)
    submitted = client.post("/api/closings", headers=staff_headers, json={
        "business_date": business_day.isoformat(),
        "notes": "Till balanced",
        "difference_notes": "No unresolved differences",
    })
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["version"] == 1
    staff_review = client.post(
        f"/api/closings/{submitted.json()['id']}/review",
        headers=staff_headers,
        json={},
    )
    assert staff_review.status_code == 403
    blocked_resubmit = client.post("/api/closings", headers=staff_headers, json={
        "business_date": business_day.isoformat(),
    })
    assert blocked_resubmit.status_code == 409
    immutable_totals = submitted.json()["totals"]

    client.post("/api/auth/logout", headers=staff_headers)
    owner = make_user(db, "owner@closing.example", Role.owner)
    owner_headers = login(client, owner.email)
    reviewed = client.post(
        f"/api/closings/{submitted.json()['id']}/review",
        headers=owner_headers,
        json={"review_notes": "Reviewed against the till"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "reviewed"
    assert reviewed.json()["totals"] == immutable_totals

    client.post("/api/auth/logout", headers=owner_headers)
    staff_headers = login(client, staff.email)
    extra_expense = _create_expense(
        client, staff_headers, _expense_body(
            business_day, description="Late cleaning supplies", amount="25.00",
        ),
    )
    client.post("/api/auth/logout", headers=staff_headers)
    owner_headers = login(client, owner.email)
    assert client.post(
        f"/api/expenses/{extra_expense['id']}/approve",
        headers=owner_headers,
    ).status_code == 200
    second = client.post("/api/closings", headers=owner_headers, json={
        "business_date": business_day.isoformat(),
        "notes": "Corrected after a late verification",
    })
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert second.json()["totals"]["expenses_by_method"]["cash"]["amount"] == "325.00"
    assert second.json()["totals"] != immutable_totals
    history = client.get(
        f"/api/closings?date={business_day.isoformat()}",
        headers=owner_headers,
    )
    assert history.status_code == 200
    assert [closing["version"] for closing in history.json()["items"]] == [2, 1]
    assert history.json()["items"][1]["totals"] == immutable_totals


def test_concurrent_expense_references_are_unique(postgres_test_engine, db):
    if not os.getenv("TEST_DATABASE_URL") or postgres_test_engine is None:
        pytest.skip("This collision test requires PostgreSQL")
    actor = make_user(db, "concurrent-expense@example.com", Role.staff)
    actor_id = actor.id
    day = datetime.now(TZ).date()

    def create_one(index):
        with Session(postgres_test_engine) as session:
            worker = session.get(User, actor_id)
            expense = create_expense(
                session,
                worker,
                expense_date=day,
                payment_date=day,
                category="other",
                description=f"Concurrent expense {index}",
                amount=Decimal("1.00"),
                method="cash",
            )
            session.commit()
            return expense.ref

    with ThreadPoolExecutor(max_workers=12) as executor:
        references = list(executor.map(create_one, range(50)))
    assert len(references) == 50
    assert len(set(references)) == 50
    assert all(reference.startswith("EXP-") for reference in references)
