from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, Block, Booking, BookingChannel, BookingEvent, BookingStatus, BusinessSetting,
    CustomerContact, Facility, FacilityType, OperatingSchedule, PoolSession,
    PoolSessionTemplate, Role, SpecialDay, TurfPrice, User,
)
from app.permissions import has_permission
from app.services.bookings import create_booking
from tests.conftest import login, make_user

TZ = ZoneInfo("Asia/Dhaka")


def seed_facilities(db, pool_capacity=4):
    turf = Facility(facility_type=FacilityType.turf, name="Main Turf", is_active=True)
    pool = Facility(facility_type=FacilityType.pool, name="Pool", is_active=True)
    db.add_all([turf, pool])
    db.flush()
    for weekday in range(7):
        db.add_all([
            OperatingSchedule(
                facility_id=turf.id, weekday=weekday,
                open_time=time(11), close_time=time(21), is_closed=False,
            ),
            OperatingSchedule(
                facility_id=pool.id, weekday=weekday,
                open_time=time(8), close_time=time(18), is_closed=False,
            ),
            PoolSessionTemplate(
                facility_id=pool.id, weekday=weekday,
                start_time=time(9), end_time=time(10, 30),
                capacity=pool_capacity, price_per_person=Decimal("200.00"),
                is_active=True,
            ),
        ])
    db.add(TurfPrice(
        facility_id=turf.id, weekday=None, start_time=None, end_time=None,
        price=Decimal("2000.00"), is_active=True,
    ))
    db.add(BusinessSetting(key="booking_horizon_days", value="21"))
    db.commit()
    return turf, pool


def service_day():
    return datetime.now(TZ).date() + timedelta(days=1)


def local_start(day=None, hour=11, minute=0):
    target = day or service_day()
    return datetime.combine(target, time(hour), tzinfo=TZ) + timedelta(minutes=minute)


def register_customer(client, email="customer@example.com"):
    response = client.post("/api/auth/register", json={
        "email": email,
        "password": "password123",
        "full_name": "Customer Name",
        "phone": "01712345678",
        "address": "House 1, Road 2, Khulna",
    })
    assert response.status_code == 201, response.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def make_pool_session(client):
    response = client.get(f"/api/availability/pool?date={service_day().isoformat()}")
    assert response.status_code == 200, response.text
    return response.json()[0]


def test_online_turf_booking_uses_backend_price_and_records_hold(client, db):
    turf, _ = seed_facilities(db)
    register_customer(client)
    response = client.post("/api/bookings", headers={
        "X-CSRF-Token": client.cookies.get("csrf_token"),
    }, json={
        "facility_id": turf.id,
        "starts_at": local_start().isoformat(),
    })
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["status"] == "held"
    assert booking["channel"] == "online"
    assert booking["total_amount"] == "2000.00"
    assert booking["hold_expires_at"]
    details = client.get(f"/api/bookings/{booking['ref']}")
    assert details.status_code == 200
    assert len(details.json()["events"]) == 1
    assert db.scalar(select(BookingEvent).where(BookingEvent.booking_id == booking["id"])).to_status == BookingStatus.held
    assert db.scalar(select(AuditLog).where(AuditLog.action == "booking.create"))


def test_turf_availability_reflects_price_and_active_hold(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client)
    query = f"/api/availability/turf?date={service_day().isoformat()}"
    before = client.get(query)
    assert before.status_code == 200
    assert before.json()[0]["facility_id"] == turf.id
    assert before.json()[0]["price"] == "2000.00"
    assert before.json()[0]["status"] == "free"

    booking = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
    })
    assert booking.status_code == 201
    after = client.get(query)
    assert after.json()[0]["status"] == "held"
    assert after.json()[1]["status"] == "held"
    assert after.json()[2]["status"] == "free"


def test_turf_overlap_is_rejected_but_adjacent_slot_is_allowed(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client)
    for minute, expected in ((0, 201), (30, 409), (60, 201)):
        response = client.post("/api/bookings", headers=headers, json={
            "facility_id": turf.id,
            "starts_at": local_start(minute=minute).isoformat(),
        })
        assert response.status_code == expected, response.text


def test_staff_phone_and_walk_in_bookings_and_role_permissions(client, db):
    turf, _ = seed_facilities(db)
    staff = make_user(db, "staff@x.com", Role.staff)
    headers = login(client, staff.email)
    base = {
        "facility_id": turf.id,
        "starts_at": local_start().isoformat(),
        "customer_name": "Phone Customer",
        "customer_phone": "01812345678",
        "channel": "phone",
    }
    response = client.post("/api/bookings/staff", headers=headers, json=base)
    assert response.status_code == 201, response.text
    assert response.json()["channel"] == "phone"
    assert response.json()["status"] == "held"
    assert response.json()["hold_expires_at"]
    lookup = client.get("/api/bookings/contacts?phone=%2B8801812345678")
    assert lookup.status_code == 200
    assert lookup.json()["found"] is True
    assert lookup.json()["name"] == "Phone Customer"
    assert client.post("/api/bookings/staff", headers=headers, json={
        **base, "channel": "walk_in", "customer_phone": "01912345678",
        "starts_at": local_start(minute=60).isoformat(),
    }).status_code == 201

    client.post("/api/auth/logout", headers=headers)
    shareholder = make_user(db, "shareholder@x.com", Role.shareholder)
    shareholder_headers = login(client, shareholder.email)
    assert client.post("/api/bookings/staff", headers=shareholder_headers, json=base).status_code == 403
    assert not has_permission(Role.shareholder, "booking.create_for_customer")
    client.post("/api/auth/logout", headers=shareholder_headers)
    customer_headers = register_customer(client, "customer-staff-route@example.com")
    assert client.post("/api/bookings/staff", headers=customer_headers, json=base).status_code == 403
    assert client.get("/api/bookings").status_code == 403


def test_pool_capacity_and_snapshot_price(client, db):
    _, pool = seed_facilities(db, pool_capacity=4)
    headers = register_customer(client)
    session = make_pool_session(client)
    first = client.post("/api/bookings", headers=headers, json={
        "facility_id": pool.id, "pool_session_id": session["id"], "participants": 3,
    })
    assert first.status_code == 201, first.text
    assert first.json()["total_amount"] == "600.00"
    second = client.post("/api/bookings", headers=headers, json={
        "facility_id": pool.id, "pool_session_id": session["id"], "participants": 2,
    })
    assert second.status_code == 409
    availability = client.get(f"/api/availability/pool?date={service_day().isoformat()}")
    assert availability.json()[0]["reserved"] == 3
    assert availability.json()[0]["remaining"] == 1


def test_closed_dates_blocks_and_horizon_are_rejected(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client)
    day = service_day()
    db.add(SpecialDay(facility_id=turf.id, date=day, is_closed=True, reason="Closed"))
    db.commit()
    closed = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start(day).isoformat(),
    })
    assert closed.status_code == 409

    db.query(SpecialDay).delete()
    db.add(Block(
        facility_id=turf.id,
        starts_at=local_start(day).astimezone(timezone.utc),
        ends_at=(local_start(day) + timedelta(hours=1)).astimezone(timezone.utc),
        reason="Maintenance",
    ))
    db.commit()
    blocked = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start(day).isoformat(),
    })
    assert blocked.status_code == 409

    db.query(Block).delete()
    db.commit()
    outside = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": local_start(day + timedelta(days=22)).isoformat(),
    })
    assert outside.status_code == 409
    bad_step = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": local_start(day, minute=15).isoformat(),
    })
    assert bad_step.status_code == 409
    after_close = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id,
        "starts_at": local_start(day, hour=21).isoformat(),
    })
    assert after_close.status_code == 409


def test_expired_and_cancelled_holds_release_turf_capacity(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client)
    first = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
    })
    assert first.status_code == 201
    booking = db.get(Booking, first.json()["id"])
    booking.hold_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    second = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
    })
    assert second.status_code == 201, second.text
    assert db.get(Booking, booking.id).status == BookingStatus.expired

    staff = make_user(db, "owner@x.com", Role.owner)
    client.post("/api/auth/logout", headers=headers)
    owner_headers = login(client, staff.email)
    assert client.post(f"/api/bookings/{booking.id}/extend-hold", headers=owner_headers,
                       json={"reason": "Expired hold", "minutes": 10}).status_code == 409
    release = client.post(
        f"/api/bookings/{second.json()['id']}/release",
        headers=owner_headers,
        json={"reason": "Customer no longer needs the hold"},
    )
    assert release.status_code == 200, release.text
    third = client.post("/api/bookings/staff", headers=owner_headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
        "customer_name": "New Customer", "customer_phone": "01912345678", "channel": "walk_in",
    })
    assert third.status_code == 201, third.text


def test_my_bookings_is_private_and_incomplete_profiles_cannot_book(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client, "first@example.com")
    booked = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
    })
    assert booked.status_code == 201
    assert client.get("/api/my/bookings").json()["total"] == 1
    client.post("/api/auth/logout", headers=headers)
    register_customer(client, "second@example.com")
    assert client.get("/api/my/bookings").json()["total"] == 0
    assert client.get(f"/api/bookings/{booked.json()['ref']}").status_code == 403

    client.post("/api/auth/logout", headers={"X-CSRF-Token": client.cookies.get("csrf_token")})
    incomplete = make_user(db, "incomplete@example.com", Role.customer)
    login(client, incomplete.email)
    denied = client.post("/api/bookings", headers={
        "X-CSRF-Token": client.cookies.get("csrf_token"),
    }, json={"facility_id": turf.id, "starts_at": local_start(minute=60).isoformat()})
    assert denied.status_code == 403


def test_illegal_booking_transitions_return_conflict(client, db):
    turf, _ = seed_facilities(db)
    headers = register_customer(client)
    response = client.post("/api/bookings", headers=headers, json={
        "facility_id": turf.id, "starts_at": local_start().isoformat(),
    })
    assert response.status_code == 201
    booking_id = response.json()["id"]
    client.post("/api/auth/logout", headers=headers)
    owner = make_user(db, "owner@x.com", Role.owner)
    owner_headers = login(client, owner.email)
    assert client.post(f"/api/bookings/{booking_id}/release", headers=owner_headers,
                       json={"reason": "release this hold"}).status_code == 200
    assert client.post(f"/api/bookings/{booking_id}/extend-hold", headers=owner_headers,
                       json={"reason": "extend it", "minutes": 10}).status_code == 409


@pytest.mark.skipif(not __import__("os").getenv("TEST_DATABASE_URL"),
                    reason="concurrency guarantees require the PostgreSQL test database")
def test_postgres_turf_race_allows_only_one_booking(postgres_test_engine, db):
    turf, _ = seed_facilities(db)
    actor = make_user(db, "race@example.com", Role.customer)
    actor.phone = "01712345678"
    actor.address = "House 1, Road 2, Khulna"
    contact = CustomerContact(
        user_id=actor.id, name=actor.full_name, phone=actor.phone, address=actor.address,
    )
    db.add(contact)
    db.commit()
    start = local_start()

    def attempt():
        with Session(postgres_test_engine, expire_on_commit=False) as session:
            user = session.get(User, actor.id)
            customer = session.scalar(select(CustomerContact).where(CustomerContact.user_id == user.id))
            try:
                create_booking(
                    session, user, channel=BookingChannel.online,
                    facility_id=turf.id, starts_at=start, contact=customer,
                )
                session.commit()
                return "created"
            except HTTPException:
                session.rollback()
                return "conflict"
            except IntegrityError:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results.count("created") == 1
    assert results.count("conflict") == 1


@pytest.mark.skipif(not __import__("os").getenv("TEST_DATABASE_URL"),
                    reason="concurrency guarantees require the PostgreSQL test database")
def test_postgres_pool_race_never_exceeds_capacity(postgres_test_engine, db):
    _, pool = seed_facilities(db, pool_capacity=1)
    actor = make_user(db, "pool-race@example.com", Role.customer)
    actor.phone = "01712345678"
    actor.address = "House 1, Road 2, Khulna"
    contact = CustomerContact(
        user_id=actor.id, name=actor.full_name, phone=actor.phone, address=actor.address,
    )
    session = PoolSession(
        facility_id=pool.id,
        date=service_day(),
        start_at=datetime.combine(service_day(), time(9), tzinfo=TZ),
        end_at=datetime.combine(service_day(), time(10, 30), tzinfo=TZ),
        capacity=1,
        price_per_person=Decimal("200.00"),
    )
    db.add_all([contact, session])
    db.commit()
    actor_id, contact_id, session_id = actor.id, contact.id, session.id

    def attempt():
        with Session(postgres_test_engine, expire_on_commit=False) as test_session:
            user = test_session.get(User, actor_id)
            customer = test_session.get(CustomerContact, contact_id)
            try:
                create_booking(
                    test_session,
                    user,
                    channel=BookingChannel.online,
                    facility_id=pool.id,
                    pool_session_id=session_id,
                    participants=1,
                    contact=customer,
                )
                test_session.commit()
                return "created"
            except HTTPException:
                test_session.rollback()
                return "conflict"
            except IntegrityError:
                test_session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: attempt(), range(2)))
    assert results.count("created") == 1
    assert results.count("conflict") == 1
