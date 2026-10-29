from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import event

from app.models import (
    Booking, BookingChannel, BookingEvent, BookingStatus, CustomerContact,
    Expense, ExpenseStatus, Facility, FacilityType, ReportSnapshot,
    ReportingPeriod, ReportingPeriodStatus, Role, Shareholder, Shareholding,
    ShareholderStatement, User,
)
from app.security import hash_password


def _make_user(db, email, role):
    user = User(
        email=email,
        full_name="Performance test user",
        password_hash=hash_password("password123"),
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _capture_selects(db, request):
    statements = []

    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        response = request()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return response, statements


def test_customer_booking_list_has_bounded_select_count(db, client):
    customer = _make_user(db, "booking-list@example.com", Role.customer)
    facility = Facility(
        facility_type=FacilityType.turf,
        name="Performance test turf",
        is_active=True,
    )
    db.add(facility)
    db.flush()
    contact = CustomerContact(
        user_id=customer.id,
        name="Performance test customer",
        phone="01712345678",
        address="Test address",
    )
    db.add(contact)
    db.flush()
    start = datetime(2030, 1, 1, 8, tzinfo=timezone.utc)
    for index in range(20):
        booking = Booking(
            ref=f"BK-PERF-{index:04d}",
            facility_id=facility.id,
            channel=BookingChannel.online,
            status=BookingStatus.cancelled,
            customer_contact_id=contact.id,
            created_by_user_id=customer.id,
            total_amount=Decimal("100.00"),
            currency="BDT",
            starts_at=start + timedelta(days=index),
            ends_at=start + timedelta(days=index, hours=1),
        )
        db.add(booking)
        db.flush()
        db.add(BookingEvent(
            booking_id=booking.id,
            actor_id=customer.id,
            from_status=None,
            to_status=BookingStatus.cancelled,
            reason="Query-count test",
        ))
    db.commit()
    _login(client, customer.email)
    db.expunge_all()

    response, statements = _capture_selects(
        db,
        lambda: client.get("/api/my/bookings?page=1&size=100"),
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 20
    assert all(item["events"] for item in response.json()["items"])
    assert len(statements) <= 7


def test_expense_list_has_bounded_select_count(db, client):
    owner = _make_user(db, "expense-list@example.com", Role.owner)
    categories = ("electricity", "cleaning", "maintenance", "supplies", "salary", "other")
    for index in range(24):
        db.add(Expense(
            ref=f"EXP-PERF-{index:04d}",
            expense_date=date(2026, 1, 1) + timedelta(days=index),
            payment_date=date(2026, 1, 1) + timedelta(days=index),
            category=categories[index % len(categories)],
            description="Query-count test",
            amount=Decimal("1.25"),
            method="cash",
            entered_by=owner.id,
            status=ExpenseStatus.pending,
        ))
    db.commit()
    _login(client, owner.email)
    db.expunge_all()

    response, statements = _capture_selects(
        db,
        lambda: client.get("/api/expenses?page=1&size=100"),
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 24
    assert len(statements) <= 6


def test_shareholder_register_is_paginated_and_batched(db, client):
    owner = _make_user(db, "shareholder-register@example.com", Role.owner)
    linked_users = [
        _make_user(db, f"shareholder-{index}@example.com", Role.shareholder)
        for index in range(4)
    ]
    for index in range(24):
        holder = Shareholder(
            name=f"Performance holder {index:02d}",
            email=f"holder-{index}@example.com",
            user_id=linked_users[index].id if index < len(linked_users) else None,
        )
        db.add(holder)
        db.flush()
        db.add(Shareholding(
            shareholder_id=holder.id,
            shares=index + 1,
            effective_from=date(2025, 1, 1),
        ))
    db.commit()
    _login(client, owner.email)
    db.expunge_all()

    response, statements = _capture_selects(
        db,
        lambda: client.get("/api/shareholders?page=2&size=10"),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["total"], result["page"], result["size"]) == (24, 2, 10)
    assert len(result["items"]) == 10
    assert len({item["id"] for item in result["items"]}) == 10
    assert len(statements) <= 8


def test_shareholder_report_and_statement_lists_are_paginated_and_private(db, client):
    owner = _make_user(db, "report-page-owner@example.com", Role.owner)
    shareholder_user = _make_user(db, "report-page-holder@example.com", Role.shareholder)
    other_user = _make_user(db, "report-page-other@example.com", Role.shareholder)
    holder = Shareholder(
        name="Page test holder",
        email="report-page-holder@example.com",
        user_id=shareholder_user.id,
    )
    other_holder = Shareholder(
        name="Other private holder",
        email="report-page-other@example.com",
        user_id=other_user.id,
    )
    db.add_all([holder, other_holder])
    db.flush()
    for index in range(24):
        period = ReportingPeriod(
            year=2020 + index // 12,
            month=index % 12 + 1,
            status=ReportingPeriodStatus.approved,
            version=1,
        )
        db.add(period)
        db.flush()
        snapshot = ReportSnapshot(
            reporting_period_id=period.id,
            version=1,
            approved_by=owner.id,
            calculation_basis="Cash-receipt basis",
            inputs={"payments": [], "expenses": []},
            totals={"operating_result": "1.00"},
            allocations=[
                {"shareholder_id": holder.id, "name": holder.name, "shares": 1, "amount": "1.00"},
                {"shareholder_id": other_holder.id, "name": other_holder.name, "shares": 1, "amount": "1.00"},
            ],
            total_shares=2,
            pool=Decimal("1.00"),
            remainder=Decimal("0.00"),
        )
        db.add(snapshot)
        db.flush()
        db.add_all([
            ShareholderStatement(
                snapshot_id=snapshot.id,
                shareholder_id=holder.id,
                content={"holder": holder.name},
                generated_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            ),
            ShareholderStatement(
                snapshot_id=snapshot.id,
                shareholder_id=other_holder.id,
                content={"holder": other_holder.name},
                generated_at=datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            ),
        ])
    db.commit()
    _login(client, shareholder_user.email)
    db.expunge_all()

    reports, report_queries = _capture_selects(
        db,
        lambda: client.get("/api/reports/approved?page=2&size=10"),
    )
    statements, statement_queries = _capture_selects(
        db,
        lambda: client.get("/api/statements/mine?page=2&size=10"),
    )

    assert reports.status_code == 200, reports.text
    report_result = reports.json()
    assert (report_result["total"], report_result["page"], report_result["size"]) == (24, 2, 10)
    assert len(report_result["items"]) == 10
    assert all("allocations" not in item and "inputs" not in item for item in report_result["items"])
    assert "Other private holder" not in str(report_result)
    assert len(report_queries) <= 8
    assert statements.status_code == 200, statements.text
    statement_result = statements.json()
    assert (statement_result["total"], statement_result["page"], statement_result["size"]) == (24, 2, 10)
    assert len(statement_result["items"]) == 10
    assert all(item["content"]["holder"] == holder.name for item in statement_result["items"])
    assert len(statement_queries) <= 5
