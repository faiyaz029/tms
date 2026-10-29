import csv
import hashlib
import io
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.email import OutboxEmailBackend
from app.email import console as console_email
from app.models import (
    AuditLog, EmailDelivery, EmailDeliveryStatus, PasswordResetRateBucket,
    PasswordResetToken, ReportSnapshot, Role, ShareholderStatement, BusinessSetting,
)
from app.services import email as email_service
from tests.conftest import login, make_user
from tests.test_reports import _make_turf_booking, _switch_user


def _create_holder(client, headers, user, name):
    response = client.post("/api/shareholders", headers=headers, json={
        "name": name,
        "email": user.email,
        "user_id": user.id,
        "shares": 25,
        "effective_from": "2020-01-01",
        "reason": "Initial ownership register entry",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _approve_report(client, headers, year, month, exception_reason=None):
    path = f"/api/reports/{year}/{month}"
    eligible = client.post(
        path + "/eligible-shares",
        headers=headers,
        json={"total_shares": 50, "reason": "Confirm eligible share count"},
    )
    assert eligible.status_code == 200, eligible.text
    distribution = client.post("/api/distribution", headers=headers, json={
        "year": year,
        "month": month,
        "pool_amount": "0.00",
        "reason": "No distribution is declared for this test period",
    })
    assert distribution.status_code == 200, distribution.text
    for key in ("payments_verified", "expenses_approved", "closings_reviewed"):
        response = client.patch(path + f"/checklist/{key}", headers=headers, json={
            "is_done": True,
            "note": f"Reviewed {key}",
        })
        assert response.status_code == 200, response.text
    submitted = client.post(path + "/submit-review", headers=headers, json={"note": "Reviewed"})
    assert submitted.status_code == 200, submitted.text
    approved = client.post(path + "/approve", headers=headers, json={
        "exception_reason": exception_reason,
    })
    assert approved.status_code == 200, approved.text
    return approved.json()


def _token_from_delivery(db, delivery):
    match = re.search(r"token=([^&'\"]+)", delivery.html_body or "")
    assert match
    token = match.group(1)
    reset = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest()
    ))
    assert reset is not None
    assert reset.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert reset.token_hash != token
    return token, reset


def test_approval_creates_snapshot_statements_and_private_previews(client, db, monkeypatch):
    monkeypatch.setattr(email_service, "get_email_backend", lambda: OutboxEmailBackend())
    owner = make_user(db, "owner@phase7.example.com", Role.owner)
    owner_headers = login(client, owner.email)
    first = make_user(db, "first@phase7.example.com", Role.shareholder)
    second = make_user(db, "second@phase7.example.com", Role.shareholder)
    _create_holder(client, owner_headers, first, "First Holder")
    _create_holder(client, owner_headers, second, "Second Holder")

    approved = _approve_report(client, owner_headers, 2025, 10)
    snapshot = db.scalar(select(ReportSnapshot))
    statements = db.scalars(
        select(ShareholderStatement).order_by(ShareholderStatement.id)
    ).all()
    deliveries = db.scalars(
        select(EmailDelivery).order_by(EmailDelivery.id)
    ).all()
    assert approved["status"] == "approved"
    assert len(statements) == len(deliveries) == 2
    assert sum(item.status == EmailDeliveryStatus.failed for item in deliveries) == 1
    assert sum(item.status == EmailDeliveryStatus.previewed for item in deliveries) == 1
    assert all(item.attempts == 1 for item in deliveries)
    assert sum(item.last_error == "Simulated one-time demo failure" for item in deliveries) == 1
    assert all(item.content["payout_status"] == "calculated" for item in statements)
    assert all(item.content["payout_note"] == "A calculated allocation is not confirmation of payment." for item in statements)
    assert all(item.content["report_reference"] == "RPT-202510-V1" for item in statements)
    assert all(item.content["final_result"] == snapshot.totals["operating_result"] for item in statements)
    if db.bind.dialect.name == "postgresql":
        with pytest.raises(DBAPIError, match="Financial history is immutable"):
            db.execute(
                text("UPDATE shareholder_statements SET content = '{}' WHERE id = :id"),
                {"id": statements[0].id},
            )
        db.rollback()

    first_headers = _switch_user(client, owner_headers, first.email)
    own = client.get("/api/statements/mine", headers=first_headers)
    assert own.status_code == 200
    assert len(own.json()["items"]) == 1
    first_statement_id = own.json()["items"][0]["id"]
    second_statement_id = next(item.id for item in statements if item.id != first_statement_id)
    assert client.get(f"/api/statements/{first_statement_id}", headers=first_headers).status_code == 200
    assert client.get(f"/api/statements/{second_statement_id}", headers=first_headers).status_code == 404

    admin_headers = _switch_user(client, first_headers, owner.email)
    listed = client.get("/api/emails", headers=admin_headers)
    assert listed.status_code == 200
    delivery_id = listed.json()["items"][0]["id"]
    preview = client.get(f"/api/emails/{delivery_id}/preview", headers=admin_headers)
    assert preview.status_code == 200
    assert "not confirmation of payment" in preview.text
    failed_delivery = next(
        item for item in deliveries if item.status == EmailDeliveryStatus.failed
    )
    retry = client.post(
        f"/api/emails/{failed_delivery.id}/retry",
        headers=admin_headers,
    )
    assert retry.status_code == 202
    db.refresh(failed_delivery)
    assert failed_delivery.status == EmailDeliveryStatus.previewed
    assert failed_delivery.attempts == 2
    first_headers = _switch_user(client, admin_headers, first.email)
    assert client.get("/api/emails", headers=first_headers).status_code == 403


def test_email_failure_is_stored_and_retry_does_not_reverse_approval(client, db, monkeypatch):
    class FailingBackend:
        def send(self, recipient, subject, html_body):
            raise ConnectionError("temporary service failure")

    monkeypatch.setattr(email_service, "get_email_backend", FailingBackend)
    demo_flag = db.scalar(select(BusinessSetting).where(
        BusinessSetting.key == "email_demo_failure_pending"
    ))
    demo_flag.value = "false"
    db.commit()
    owner = make_user(db, "owner@email-failure.example.com", Role.owner)
    headers = login(client, owner.email)
    holder = make_user(db, "holder@email-failure.example.com", Role.shareholder)
    _create_holder(client, headers, holder, "Retry Holder")

    result = _approve_report(client, headers, 2025, 11)
    delivery = db.scalar(select(EmailDelivery))
    assert result["status"] == "approved"
    assert delivery.status == EmailDeliveryStatus.failed
    assert delivery.attempts == 1
    assert "ConnectionError" in delivery.last_error

    monkeypatch.setattr(email_service, "get_email_backend", lambda: OutboxEmailBackend())
    retry = client.post(f"/api/emails/{delivery.id}/retry", headers=headers)
    assert retry.status_code == 202
    db.refresh(delivery)
    assert delivery.status == EmailDeliveryStatus.previewed
    assert delivery.attempts == 2
    assert db.scalar(select(ReportSnapshot)).id == result["history"][0]["id"]
    assert client.post(f"/api/emails/{delivery.id}/retry", headers=headers).status_code == 409


def test_password_reset_is_generic_hashed_single_use_and_rate_limited(client, db, monkeypatch):
    monkeypatch.setattr(email_service, "get_email_backend", lambda: OutboxEmailBackend())
    user = make_user(db, "customer@reset.example.com", Role.customer)
    unknown = client.post("/api/auth/forgot-password", json={"email": "missing@reset.example.com"})
    known = client.post("/api/auth/forgot-password", json={"email": user.email})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()

    delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.kind == "password_reset"))
    assert delivery.status == EmailDeliveryStatus.previewed
    token, reset = _token_from_delivery(db, delivery)
    response = client.post("/api/auth/reset-password", json={
        "token": token,
        "password": "new-password-123",
    })
    assert response.status_code == 200
    assert client.post("/api/auth/reset-password", json={
        "token": token,
        "password": "another-password-123",
    }).status_code == 400
    assert client.post("/api/auth/login", json={
        "email": user.email,
        "password": "new-password-123",
    }).status_code == 200
    assert client.post("/api/auth/login", json={
        "email": user.email,
        "password": "password123",
    }).status_code == 401
    assert reset.used_at is not None
    assert db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "user.password_reset"
    )) == 1

    for _ in range(5):
        limited = client.post("/api/auth/forgot-password", json={"email": user.email})
        assert limited.status_code == 202
        assert limited.json() == known.json()
    assert db.scalar(select(func.count()).select_from(EmailDelivery).where(
        EmailDelivery.kind == "password_reset"
    )) == 4
    assert db.scalar(select(func.count()).select_from(PasswordResetRateBucket).where(
        PasswordResetRateBucket.request_count > 5
    )) == 2


def test_password_reset_tokens_expire(client, db, monkeypatch):
    monkeypatch.setattr(email_service, "get_email_backend", lambda: OutboxEmailBackend())
    user = make_user(db, "expired@reset.example.com", Role.customer)
    client.post("/api/auth/forgot-password", json={"email": user.email})
    delivery = db.scalar(select(EmailDelivery).where(EmailDelivery.kind == "password_reset"))
    token, reset = _token_from_delivery(db, delivery)
    reset.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    expired = client.post("/api/auth/reset-password", json={
        "token": token,
        "password": "new-password-123",
    })
    assert expired.status_code == 400


def test_console_backend_never_logs_reset_contents(monkeypatch):
    log_calls = []
    monkeypatch.setattr(console_email.logger, "info", lambda *args: log_calls.append(args))
    result = console_email.ConsoleEmailBackend().send(
        "owner@example.com",
        "Reset your password",
        "<a href='https://example.com/reset?token=do-not-log'>Reset</a>",
    )
    assert result.status == EmailDeliveryStatus.sent
    assert result.provider_id == "console-log"
    assert log_calls and "not delivered" in log_calls[0][0]
    assert "do-not-log" not in repr(log_calls)


def test_csv_exports_share_filters_and_enforce_access(client, db, owner_headers, monkeypatch):
    monkeypatch.setattr(email_service, "get_email_backend", lambda: email_service.OutboxEmailBackend())
    booking = _make_turf_booking(client, db, owner_headers, "120.00")
    booking_day = datetime.fromisoformat(booking["starts_at"]).astimezone(
        timezone(timedelta(hours=6))
    ).date().isoformat()
    params = f"date_from={booking_day}&date_to={booking_day}&status=held&ref={booking['ref']}"
    booking_list = client.get(f"/api/bookings?{params}", headers=owner_headers)
    booking_export = client.get(f"/api/exports/bookings.csv?{params}", headers=owner_headers)
    assert booking_list.status_code == booking_export.status_code == 200
    booking_rows = list(csv.reader(io.StringIO(booking_export.text)))
    assert [row[0] for row in booking_rows[1:]] == [booking["ref"]]
    assert "Report Test Contact" in booking_export.text
    assert "01812345678" not in booking_export.text

    payment = client.post(f"/api/bookings/{booking['id']}/payments", headers=owner_headers, json={
        "amount": "20.00",
        "method": "cash",
        "received_at": "2025-12-10T12:00:00+06:00",
    })
    assert payment.status_code == 201, payment.text
    payment_query = "received_from=2025-12-10&received_to=2025-12-10&status=received"
    payment_export = client.get(
        f"/api/exports/payments.csv?{payment_query}", headers=owner_headers,
    )
    assert payment_export.status_code == 200
    assert payment.json()["ref"] in payment_export.text

    first_expense = client.post("/api/expenses", headers=owner_headers, json={
        "expense_date": "2025-12-12",
        "payment_date": "2025-12-12",
        "category": "cleaning",
        "description": "Cleaning supplies",
        "amount": "30.00",
        "method": "cash",
        "vendor": "Vendor name",
        "trx_id": "private-trx",
        "sms_text": "private SMS text",
    })
    second_expense = client.post("/api/expenses", headers=owner_headers, json={
        "expense_date": "2025-12-11",
        "payment_date": "2025-12-11",
        "category": "other",
        "description": "Other supplies",
        "amount": "40.00",
        "method": "cash",
    })
    assert first_expense.status_code == second_expense.status_code == 201
    expense_query = "date_from=2025-12-12&date_to=2025-12-12&category=cleaning&status=pending"
    expense_list = client.get(f"/api/expenses?{expense_query}", headers=owner_headers)
    expense_export = client.get(f"/api/exports/expenses.csv?{expense_query}", headers=owner_headers)
    assert expense_list.status_code == expense_export.status_code == 200
    assert [row[0] for row in list(csv.reader(io.StringIO(expense_export.text)))[1:]] == [
        first_expense.json()["ref"],
    ]
    assert "private-trx" not in expense_export.text
    assert "private SMS text" not in expense_export.text
    assert second_expense.json()["ref"] not in expense_export.text

    closing = client.post("/api/closings", headers=owner_headers, json={
        "business_date": "2025-12-12",
        "notes": "",
        "difference_notes": "",
    })
    assert closing.status_code == 201, closing.text
    closing_export = client.get(
        "/api/exports/closings.csv?date=2025-12-12", headers=owner_headers,
    )
    assert closing_export.status_code == 200
    assert "2025-12-12" in closing_export.text

    holder = make_user(db, "export-holder@phase7.example.com", Role.shareholder)
    _create_holder(client, owner_headers, holder, "Export Holder")
    _approve_report(client, owner_headers, 2025, 12, "Unverified records retained for export test")
    report_export = client.get(
        "/api/exports/reports.csv?year=2025&month=12", headers=owner_headers,
    )
    assert report_export.status_code == 200
    assert "RPT-202512-V1" in report_export.text
    assert "private SMS text" not in report_export.text
    assert db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "export.download"
    )) == 5

    shareholder_headers = _switch_user(client, owner_headers, holder.email)
    assert client.get("/api/exports/payments.csv", headers=shareholder_headers).status_code == 403
    assert client.get("/api/exports/reports.csv", headers=shareholder_headers).status_code == 403
