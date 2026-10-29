from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import (
    DailyClosing, DailyClosingStatus, Facility, FacilityType, OperatingSchedule,
    Payment, ReportSnapshot, Role, Shareholder, TurfPrice, User,
)
from tests.conftest import login, make_user

TZ = ZoneInfo("Asia/Dhaka")


def _switch_user(client, current_headers, email):
    client.post("/api/auth/logout", headers=current_headers)
    return login(client, email)


def _create_holder(client, owner_headers, name, email, shares, user_id=None):
    response = client.post("/api/shareholders", headers=owner_headers, json={
        "name": name,
        "email": email,
        "user_id": user_id,
        "shares": shares,
        "effective_from": "2025-01-01",
        "reason": "Initial shareholder register entry",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _prepare_report(client, headers, year, month, pool, checklist=()):
    setting = client.post(
        f"/api/reports/{year}/{month}/eligible-shares",
        headers=headers,
        json={"total_shares": 50, "reason": "Confirm the total eligible share count"},
    )
    assert setting.status_code == 200, setting.text
    distribution = client.post("/api/distribution", headers=headers, json={
        "year": year,
        "month": month,
        "pool_amount": pool,
        "reason": "Owner-approved monthly distribution pool",
    })
    assert distribution.status_code == 200, distribution.text
    for key in checklist:
        updated = client.patch(
            f"/api/reports/{year}/{month}/checklist/{key}",
            headers=headers,
            json={"is_done": True, "note": f"Verified: {key}"},
        )
        assert updated.status_code == 200, updated.text
    submitted = client.post(
        f"/api/reports/{year}/{month}/submit-review",
        headers=headers,
        json={"note": "Financial reviewer checked source records"},
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _make_turf_booking(client, db, headers, price):
    turf = Facility(facility_type=FacilityType.turf, name="Report Test Turf", is_active=True)
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
        price=Decimal(price),
        is_active=True,
    ))
    db.commit()
    starts_at = datetime.combine(
        datetime.now(TZ).date() + timedelta(days=1),
        time(11),
        tzinfo=TZ,
    )
    response = client.post("/api/bookings/staff", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": starts_at.isoformat(),
        "customer_name": "Report Test Contact",
        "customer_phone": "01812345678",
        "channel": "phone",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_report_example_receipt_month_allocation_and_shareholder_privacy(client, db):
    owner = make_user(db, "owner@report-example.com", Role.owner)
    owner_headers = login(client, owner.email)
    first_holder_user = make_user(db, "one@report-example.com", Role.shareholder)
    second_holder_user = make_user(db, "two@report-example.com", Role.shareholder)
    first_holder = _create_holder(
        client, owner_headers, "Shareholder One", first_holder_user.email, 1,
        first_holder_user.id,
    )
    future_holding = client.post(
        f"/api/shareholders/{first_holder['id']}/holdings",
        headers=owner_headers,
        json={
            "shares": 5,
            "effective_from": "2025-11-01",
            "reason": "Record an effective-dated transfer",
        },
    )
    assert future_holding.status_code == 201, future_holding.text
    assert future_holding.json()["effective_to"] is None
    _create_holder(
        client, owner_headers, "Shareholder Two", second_holder_user.email, 2,
        second_holder_user.id,
    )

    staff = make_user(db, "staff@report-example.com", Role.staff)
    staff_headers = _switch_user(client, owner_headers, staff.email)
    booking = _make_turf_booking(client, db, staff_headers, "600000.00")
    received = client.post(
        f"/api/bookings/{booking['id']}/payments",
        headers=staff_headers,
        json={
            "amount": "600000.00",
            "method": "cash",
            "received_at": "2025-10-28T14:00:00+06:00",
        },
    )
    assert received.status_code == 201, received.text

    accountant = make_user(db, "accountant@report-example.com", Role.accountant)
    accountant_headers = _switch_user(client, staff_headers, accountant.email)
    verified = client.post(
        f"/api/payments/{received.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert verified.status_code == 200, verified.text
    payment = db.get(Payment, received.json()["id"])
    payment.verified_at = datetime(2025, 11, 2, 4, tzinfo=timezone.utc)
    db.commit()

    staff_headers = _switch_user(client, accountant_headers, staff.email)
    expense = client.post("/api/expenses", headers=staff_headers, json={
        "expense_date": "2025-10-30",
        "payment_date": "2025-10-31",
        "category": "electricity",
        "description": "October electricity bill",
        "amount": "350000.00",
        "method": "cash",
        "vendor": "Private vendor details",
    })
    assert expense.status_code == 201, expense.text
    accountant_headers = _switch_user(client, staff_headers, accountant.email)
    approved_expense = client.post(
        f"/api/expenses/{expense.json()['id']}/approve",
        headers=accountant_headers,
    )
    assert approved_expense.status_code == 200, approved_expense.text

    report = _prepare_report(
        client,
        accountant_headers,
        2025,
        10,
        "250000.00",
        checklist=("payments_verified", "expenses_approved"),
    )
    totals = report["totals"]
    assert report["status"] == "under_review"
    assert totals["verified_collections"]["amount"] == "600000.00"
    assert totals["verified_collections"]["by_method"]["cash"]["amount"] == "600000.00"
    assert totals["approved_expenses"]["amount"] == "350000.00"
    assert totals["operating_result"] == "250000.00"
    assert totals["per_share"] == "5000.00"
    assert totals["remainder"] == "235000.00"
    assert report["allocations"] == [
        {
            "shareholder_id": first_holder["id"],
            "name": "Shareholder One",
            "shares": 1,
            "amount": "5000.00",
        },
        {
            "shareholder_id": first_holder["id"] + 1,
            "name": "Shareholder Two",
            "shares": 2,
            "amount": "10000.00",
        },
    ]
    allocated = sum(Decimal(row["amount"]) for row in report["allocations"])
    assert allocated + Decimal(totals["remainder"]) == Decimal(totals["pool"])
    assert "2025-10-28" in report["inputs"]["payments"][0]["received_at"]

    non_owner_approval = client.post(
        "/api/reports/2025/10/approve",
        headers=accountant_headers,
        json={},
    )
    assert non_owner_approval.status_code == 403
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    blocked = client.post(
        "/api/reports/2025/10/approve",
        headers=owner_headers,
        json={},
    )
    assert blocked.status_code == 409
    accountant_headers = _switch_user(client, owner_headers, accountant.email)
    checked = client.patch(
        "/api/reports/2025/10/checklist/closings_reviewed",
        headers=accountant_headers,
        json={"is_done": True, "note": "All October closings reviewed"},
    )
    assert checked.status_code == 200
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    approved = client.post(
        "/api/reports/2025/10/approve",
        headers=owner_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    snapshot = db.scalar(select(ReportSnapshot))
    assert snapshot is not None
    assert snapshot.inputs["payments"][0]["status"] == "verified"

    shareholder_headers = _switch_user(client, owner_headers, first_holder_user.email)
    own_reports = client.get("/api/reports/approved", headers=shareholder_headers)
    assert own_reports.status_code == 200, own_reports.text
    assert (own_reports.json()["total"], own_reports.json()["page"], own_reports.json()["size"]) == (1, 1, 20)
    own = own_reports.json()["items"][0]
    assert own["my_allocation"] == {
        "shareholder_id": first_holder["id"],
        "name": "Shareholder One",
        "shares": 1,
        "amount": "5000.00",
    }
    assert "allocations" not in own and "inputs" not in own
    assert "Shareholder Two" not in str(own)
    holding = client.get("/api/my/shareholding", headers=shareholder_headers)
    assert holding.status_code == 200
    assert holding.json()["current_shares"] == 5
    assert holding.json()["holdings"][1]["effective_to"] == "2025-10-31"
    assert client.get("/api/reports/2025/10", headers=shareholder_headers).status_code == 403
    approved_expenses = client.get(
        "/api/reports/approved/2025/10/expenses",
        headers=shareholder_headers,
    )
    assert approved_expenses.status_code == 200
    assert (approved_expenses.json()["total"], approved_expenses.json()["page"], approved_expenses.json()["size"]) == (1, 1, 20)
    assert approved_expenses.json()["items"] == [{
        "ref": expense.json()["ref"],
        "payment_date": "2025-10-31",
        "category": "electricity",
        "description": "October electricity bill",
        "amount": "350000.00",
        "method": "cash",
        "status": "approved",
    }]
    empty_page = client.get(
        "/api/reports/approved/2025/10/expenses?page=2&size=1",
        headers=shareholder_headers,
    )
    assert empty_page.status_code == 200, empty_page.text
    assert empty_page.json() == {"items": [], "total": 1, "page": 2, "size": 1}
    assert "vendor" not in approved_expenses.json()["items"][0]
    write_attempt = client.post("/api/distribution", headers=shareholder_headers, json={
        "year": 2025,
        "month": 10,
        "pool_amount": "1.00",
        "reason": "Should not be allowed",
    })
    assert write_attempt.status_code == 403


def test_reopen_preserves_snapshot_and_rounding_remainder(client, db):
    owner = make_user(db, "owner@reopen-report.com", Role.owner)
    owner_headers = login(client, owner.email)
    holder_user = make_user(db, "holder@reopen-report.com", Role.shareholder)
    _create_holder(
        client, owner_headers, "Full Register Holder", holder_user.email, 50,
        holder_user.id,
    )
    accountant = make_user(db, "accountant@reopen-report.com", Role.accountant)
    accountant_headers = _switch_user(client, owner_headers, accountant.email)

    _prepare_report(
        client,
        accountant_headers,
        2025,
        11,
        "100000.01",
        checklist=("payments_verified", "expenses_approved", "closings_reviewed"),
    )
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    approved = client.post(
        "/api/reports/2025/11/approve",
        headers=owner_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    first_snapshot = db.scalar(select(ReportSnapshot))
    original_totals = dict(first_snapshot.totals)
    original_allocations = list(first_snapshot.allocations)
    assert first_snapshot.remainder == Decimal("0.01")
    assert first_snapshot.allocations[0]["amount"] == "100000.00"
    assert sum(Decimal(row["amount"]) for row in first_snapshot.allocations) + first_snapshot.remainder == first_snapshot.pool

    reopened = client.post(
        "/api/reports/2025/11/reopen",
        headers=owner_headers,
        json={"reason": "Correcting a late reconciliation item"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "reopened"
    assert reopened.json()["version"] == 2
    assert first_snapshot.totals == original_totals
    assert first_snapshot.allocations == original_allocations
    assert db.scalar(select(ReportSnapshot.id)) == first_snapshot.id

    accountant_headers = _switch_user(client, owner_headers, accountant.email)
    _prepare_report(
        client,
        accountant_headers,
        2025,
        11,
        "100000.01",
        checklist=("payments_verified", "expenses_approved", "closings_reviewed"),
    )
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    second_approval = client.post(
        "/api/reports/2025/11/approve",
        headers=owner_headers,
        json={},
    )
    assert second_approval.status_code == 200, second_approval.text
    history = second_approval.json()["history"]
    assert [item["version"] for item in history] == [2, 1]
    assert history[1]["totals"] == original_totals
    assert history[1]["allocations"] == original_allocations

    if db.bind.dialect.name == "postgresql":
        with pytest.raises(DBAPIError, match="Financial history is immutable"):
            db.execute(
                text("UPDATE report_snapshots SET pool = 1 WHERE id = :id"),
                {"id": first_snapshot.id},
            )
        db.rollback()
        audit_id = db.scalar(text("SELECT id FROM audit_logs LIMIT 1"))
        with pytest.raises(DBAPIError, match="Financial history is immutable"):
            db.execute(
                text("UPDATE audit_logs SET reason = 'changed' WHERE id = :id"),
                {"id": audit_id},
            )
        db.rollback()


def test_shareholder_register_access_is_owner_only(client, db):
    owner = make_user(db, "owner@register-report.com", Role.owner)
    owner_headers = login(client, owner.email)
    accountant = make_user(db, "accountant@register-report.com", Role.accountant)
    accountant_headers = _switch_user(client, owner_headers, accountant.email)
    shareholder = make_user(db, "holder@register-report.com", Role.shareholder)
    shareholder_headers = _switch_user(client, accountant_headers, shareholder.email)

    assert client.get("/api/shareholders", headers=shareholder_headers).status_code == 403
    accountant_headers = _switch_user(client, shareholder_headers, accountant.email)
    assert client.get("/api/shareholders", headers=accountant_headers).status_code == 403
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    assert client.get("/api/shareholders", headers=owner_headers).status_code == 200
    shareholder_headers = _switch_user(client, owner_headers, shareholder.email)
    assert client.get("/api/shareholders", headers=shareholder_headers).status_code == 403
    denied = client.post("/api/shareholders", headers=shareholder_headers, json={
        "name": "Forbidden holder",
        "email": "forbidden@register-report.test",
        "shares": 1,
        "effective_from": "2025-01-01",
        "reason": "Unauthorized write attempt",
    })
    assert denied.status_code == 403
    for method, path, body in (
        ("PATCH", "/api/shareholders/1", {
            "is_active": False, "reason": "Unauthorized register edit",
        }),
        ("POST", "/api/shareholders/1/holdings", {
            "shares": 2, "effective_from": "2025-02-01", "reason": "Unauthorized holding edit",
        }),
        ("POST", "/api/reports/2025/12/submit-review", {"note": "Unauthorized review"}),
        ("PATCH", "/api/reports/2025/12/checklist/payments_verified", {"is_done": True}),
        ("POST", "/api/reports/2025/12/eligible-shares", {
            "total_shares": 50, "reason": "Unauthorized share confirmation",
        }),
        ("POST", "/api/distribution", {
            "year": 2025, "month": 12, "pool_amount": "1.00",
            "reason": "Unauthorized distribution",
        }),
        ("POST", "/api/reports/2025/12/approve", {}),
        ("POST", "/api/reports/2025/12/reopen", {"reason": "Unauthorized reopen"}),
    ):
        response = client.request(method, path, headers=shareholder_headers, json=body)
        assert response.status_code == 403, (method, path, response.text)
    assert db.scalar(select(Shareholder).where(Shareholder.email == "forbidden@register-report.test")) is None


def test_approved_expense_and_unverified_payments_block_without_owner_exception(client, db):
    owner = make_user(db, "owner@exceptions-report.com", Role.owner)
    owner_headers = login(client, owner.email)
    holder_user = make_user(db, "holder@exceptions-report.com", Role.shareholder)
    _create_holder(
        client, owner_headers, "Exception Test Holder", holder_user.email, 50,
        holder_user.id,
    )
    staff = make_user(db, "staff@exceptions-report.com", Role.staff)
    staff_headers = _switch_user(client, owner_headers, staff.email)
    expense = client.post("/api/expenses", headers=staff_headers, json={
        "expense_date": "2025-12-10",
        "payment_date": "2025-12-10",
        "category": "other",
        "description": "Pending expense",
        "amount": "12.00",
        "method": "cash",
    })
    assert expense.status_code == 201
    booking = _make_turf_booking(client, db, staff_headers, "10.00")
    payment = client.post(
        f"/api/bookings/{booking['id']}/payments",
        headers=staff_headers,
        json={
            "amount": "1.00",
            "method": "cash",
            "received_at": "2025-12-10T12:00:00+06:00",
        },
    )
    assert payment.status_code == 201, payment.text
    db.add(DailyClosing(
        business_date=datetime(2025, 12, 10).date(),
        version=1,
        status=DailyClosingStatus.submitted,
        totals={},
        submitted_by=staff.id,
    ))
    db.commit()
    accountant = make_user(db, "accountant@exceptions-report.com", Role.accountant)
    accountant_headers = _switch_user(client, staff_headers, accountant.email)
    report = _prepare_report(
        client,
        accountant_headers,
        2025,
        12,
        "100.00",
        checklist=("payments_verified", "expenses_approved", "closings_reviewed"),
    )
    assert report["unresolved"]["pending_expenses"] == 1
    assert report["unresolved"]["received_payments"] == 1
    assert len(report["unresolved"]["daily_closings"]) == 1
    owner_headers = _switch_user(client, accountant_headers, owner.email)
    blocked = client.post(
        "/api/reports/2025/12/approve",
        headers=owner_headers,
        json={},
    )
    assert blocked.status_code == 409
    exception = client.post(
        "/api/reports/2025/12/approve",
        headers=owner_headers,
        json={"exception_reason": "Pending expense is documented for follow-up"},
    )
    assert exception.status_code == 200, exception.text
    snapshot = db.scalar(select(ReportSnapshot))
    assert snapshot.exception_reason == "Pending expense is documented for follow-up"
    assert snapshot.totals["unverified_payments"]["count"] == 1
