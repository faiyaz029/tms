from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import (
    AuditLog, Booking, BookingStatus, Facility, FacilityType, OperatingSchedule,
    Payment, PaymentEvent, PaymentStatus, Role, TurfPrice, User,
)
from tests.conftest import login, make_user

TZ = ZoneInfo("Asia/Dhaka")


def _setup_turf(db):
    turf = Facility(facility_type=FacilityType.turf, name="Main Turf", is_active=True)
    db.add(turf)
    db.flush()
    for weekday in range(7):
        db.add(OperatingSchedule(
            facility_id=turf.id, weekday=weekday,
            open_time=time(10), close_time=time(22), is_closed=False,
        ))
    db.add(TurfPrice(
        facility_id=turf.id, weekday=None, start_time=None, end_time=None,
        price=Decimal("2000.00"), is_active=True,
    ))
    db.commit()
    return turf


def _future_start():
    day = datetime.now(TZ).date() + timedelta(days=1)
    return datetime.combine(day, time(11), tzinfo=TZ)


def _register_customer(client):
    response = client.post("/api/auth/register", json={
        "email": "customer@example.com",
        "password": "password123",
        "full_name": "Customer Name",
        "phone": "01712345678",
        "address": "House 1, Road 2, Khulna",
    })
    assert response.status_code == 201, response.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _staff_booking(client, turf, headers):
    response = client.post("/api/bookings/staff", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": _future_start().isoformat(),
        "customer_name": "Phone Customer",
        "customer_phone": "01812345678",
        "channel": "phone",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _record_payment(client, booking, headers, **values):
    body = {
        "amount": "2000.00",
        "method": "cash",
        "received_at": datetime.now(timezone.utc).isoformat(),
        **values,
    }
    return client.post(
        f"/api/bookings/{booking['id']}/payments",
        headers=headers,
        json=body,
    )


def test_simulated_payment_is_idempotent_and_confirms_booking(client, db):
    turf = _setup_turf(db)
    customer_headers = _register_customer(client)
    booking_response = client.post("/api/bookings", headers=customer_headers, json={
        "facility_id": turf.id,
        "starts_at": _future_start().isoformat(),
    })
    assert booking_response.status_code == 201, booking_response.text
    booking = booking_response.json()

    intent_response = client.post(
        "/api/payments/online/initiate",
        headers={**customer_headers, "Idempotency-Key": "checkout-1"},
        json={"booking_id": booking["id"]},
    )
    assert intent_response.status_code == 200, intent_response.text
    assert intent_response.json()["gateway_label"] == "SIMULATED PAYMENT"
    repeated = client.post(
        "/api/payments/online/initiate",
        headers={**customer_headers, "Idempotency-Key": "checkout-1"},
        json={"booking_id": booking["id"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == intent_response.json()["id"]

    path = f"/api/payments/online/{intent_response.json()['id']}/simulate/success"
    success = client.post(path, headers=customer_headers)
    assert success.status_code == 200, success.text
    assert success.json()["label"] == "SIMULATED PAYMENT"
    repeated_success = client.post(path, headers=customer_headers)
    assert repeated_success.status_code == 200
    assert db.scalar(select(Booking).where(Booking.id == booking["id"])).status == BookingStatus.confirmed
    payments = db.scalars(select(Payment).where(Payment.booking_id == booking["id"])).all()
    assert len(payments) == 1
    assert payments[0].status == PaymentStatus.verified
    assert payments[0].received_at is not None
    assert payments[0].verified_at is not None
    assert db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == payments[0].id))
    assert db.scalar(select(AuditLog).where(AuditLog.action == "payment.simulated_success"))
    receipt = client.get(f"/api/payments/{payments[0].ref}/receipt")
    assert receipt.status_code == 200
    assert receipt.json()["label"] == "SIMULATED PAYMENT"
    assert "not a real money transfer" in receipt.json()["notice"]


def test_failed_simulated_attempt_keeps_hold_for_retry(client, db):
    turf = _setup_turf(db)
    headers = _register_customer(client)
    booking = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": _future_start().isoformat(),
    }).json()
    intent = client.post(
        "/api/payments/online/initiate",
        headers={**headers, "Idempotency-Key": "checkout-fail"},
        json={"booking_id": booking["id"]},
    ).json()
    failed = client.post(
        f"/api/payments/online/{intent['id']}/simulate/fail",
        headers=headers,
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["booking_status"] == "held"
    repeated = client.post(
        f"/api/payments/online/{intent['id']}/simulate/fail",
        headers=headers,
    )
    assert repeated.status_code == 200
    assert db.scalar(select(Payment).where(Payment.booking_id == booking["id"])).status == PaymentStatus.failed
    retry = client.post(
        "/api/payments/online/initiate",
        headers={**headers, "Idempotency-Key": "checkout-retry"},
        json={"booking_id": booking["id"]},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] != intent["id"]


def test_online_checkout_respects_other_payment_records_before_confirmation(client, db):
    turf = _setup_turf(db)
    customer_headers = _register_customer(client)
    customer = db.scalar(select(User).where(User.email == "customer@example.com"))
    booking = client.post("/api/bookings", headers=customer_headers, json={
        "facility_id": turf.id,
        "starts_at": _future_start().isoformat(),
    }).json()

    staff = make_user(db, "staff@online-partial.example", Role.staff)
    staff_headers = login(client, staff.email)
    first = _record_payment(client, booking, staff_headers, amount="500.00")
    assert first.status_code == 201, first.text

    client.post("/api/auth/logout", headers=staff_headers)
    customer_headers = login(client, customer.email)
    intent_response = client.post(
        "/api/payments/online/initiate",
        headers={**customer_headers, "Idempotency-Key": "checkout-balance"},
        json={"booking_id": booking["id"]},
    )
    assert intent_response.status_code == 200, intent_response.text
    assert intent_response.json()["amount"] == "1500.00"
    success = client.post(
        f"/api/payments/online/{intent_response.json()['id']}/simulate/success",
        headers=customer_headers,
    )
    assert success.status_code == 200, success.text
    assert success.json()["booking_status"] == "held"

    client.post("/api/auth/logout", headers=customer_headers)
    accountant = make_user(db, "accountant@online-partial.example", Role.accountant)
    accountant_headers = login(client, accountant.email)
    verified = client.post(
        f"/api/payments/{first.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert verified.status_code == 200, verified.text
    assert db.get(Booking, booking["id"]).status == BookingStatus.confirmed


def test_manual_payment_requires_independent_verification_and_full_total(client, db):
    turf = _setup_turf(db)
    staff = make_user(db, "staff@x.com", Role.staff)
    staff_headers = login(client, staff.email)
    booking = _staff_booking(client, turf, staff_headers)

    first = _record_payment(client, booking, staff_headers, amount="1000.00")
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "received"
    same_user_verify = client.post(
        f"/api/payments/{first.json()['id']}/verify",
        headers=staff_headers,
    )
    assert same_user_verify.status_code == 403

    client.post("/api/auth/logout", headers=staff_headers)
    accountant = make_user(db, "accountant@x.com", Role.accountant)
    accountant_headers = login(client, accountant.email)
    verified_partial = client.post(
        f"/api/payments/{first.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert verified_partial.status_code == 200, verified_partial.text
    assert db.get(Booking, booking["id"]).status == BookingStatus.held

    second = _record_payment(client, booking, accountant_headers, amount="1000.00")
    assert second.status_code == 201, second.text
    self_verified = client.post(
        f"/api/payments/{second.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert self_verified.status_code == 409
    client.post("/api/auth/logout", headers=accountant_headers)
    owner = make_user(db, "owner@x.com", Role.owner)
    owner_headers = login(client, owner.email)
    final = client.post(
        f"/api/payments/{second.json()['id']}/verify",
        headers=owner_headers,
    )
    assert final.status_code == 200, final.text
    assert db.get(Booking, booking["id"]).status == BookingStatus.confirmed


def test_duplicate_transaction_and_overpayment_are_rejected(client, db):
    turf = _setup_turf(db)
    staff = make_user(db, "staff@x.com", Role.staff)
    headers = login(client, staff.email)
    booking = _staff_booking(client, turf, headers)
    received_date = datetime.now(TZ).date() - timedelta(days=1)
    received_at = datetime.combine(received_date, time(2), tzinfo=TZ).isoformat()
    first = _record_payment(
        client, booking, headers,
        amount="1000.00", method="bkash", trx_id="TRX-123",
        received_at=received_at,
    )
    assert first.status_code == 201, first.text
    duplicate = _record_payment(
        client, booking, headers,
        amount="500.00", method="bkash", trx_id="TRX-123",
    )
    assert duplicate.status_code == 409
    blank_reference = _record_payment(
        client, booking, headers,
        amount="500.00", method="bkash", trx_id=" ", bank_ref=" ",
    )
    assert blank_reference.status_code == 422
    overpayment = _record_payment(client, booking, headers, amount="1000.01")
    assert overpayment.status_code == 409
    filtered = client.get(
        f"/api/payments?received_from={received_date.isoformat()}&received_to={received_date.isoformat()}",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert [item["ref"] for item in filtered.json()["items"]] == [first.json()["ref"]]


def test_payment_read_and_record_permissions_match_roles(client, db):
    for role, expected in (
        (Role.owner, 200),
        (Role.admin, 200),
        (Role.staff, 200),
        (Role.accountant, 200),
        (Role.shareholder, 403),
        (Role.customer, 403),
    ):
        user = make_user(db, f"{role.value}@roles.example", role)
        headers = login(client, user.email)
        assert client.get("/api/payments/methods", headers=headers).status_code == expected
        client.post("/api/auth/logout", headers=headers)


def test_expired_hold_must_be_renewed_before_final_verification(client, db):
    turf = _setup_turf(db)
    staff = make_user(db, "staff@x.com", Role.staff)
    staff_headers = login(client, staff.email)
    booking = _staff_booking(client, turf, staff_headers)
    payment = _record_payment(client, booking, staff_headers)
    assert payment.status_code == 201, payment.text
    db.get(Booking, booking["id"]).hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    client.post("/api/auth/logout", headers=staff_headers)
    accountant = make_user(db, "accountant@x.com", Role.accountant)
    accountant_headers = login(client, accountant.email)
    denied = client.post(
        f"/api/payments/{payment.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert denied.status_code == 409

    client.post("/api/auth/logout", headers=accountant_headers)
    staff_headers = login(client, staff.email)
    renewed = client.post(
        f"/api/bookings/{booking['id']}/renew-hold",
        headers=staff_headers,
        json={"reason": "Customer arrived late; slot remained available"},
    )
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["status"] == "held"

    client.post("/api/auth/logout", headers=staff_headers)
    accountant_headers = login(client, accountant.email)
    verified = client.post(
        f"/api/payments/{payment.json()['id']}/verify",
        headers=accountant_headers,
    )
    assert verified.status_code == 200, verified.text
    assert db.get(Booking, booking["id"]).status == BookingStatus.confirmed
