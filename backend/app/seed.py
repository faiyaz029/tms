import argparse
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .audit import record
from .config import settings
from .db import Base, SessionLocal
from .models import (
    Booking, BookingChannel, BookingEvent, BookingStatus, BusinessSetting,
    CustomerContact, Expense, ExpenseCategory, ExpenseStatus, Facility, FacilityType,
    OperatingSchedule, Payment, PaymentEvent, PaymentMethod, PaymentStatus,
    PoolSession, PoolSessionTemplate, Role, Shareholder, Shareholding,
    TurfPrice, User, utcnow,
)
from .security import hash_password
from .services.expenses import (
    approve_expense, create_expense, reject_expense, review_closing, submit_closing,
)
from .services.reports import (
    CHECKLIST, _ensure_period, approve_report, set_distribution,
    submit_for_review, update_checklist, update_eligible_shares,
)

BUSINESS_TZ = ZoneInfo(settings.business_timezone)
UTC = timezone.utc
DEMO_PASSWORD = "DemoPool2026!"

USER_SPECS = [
    ("owner", "Demo Owner", "demo-owner@example.com", Role.owner, "01700000001"),
    ("admin", "Demo Admin", "demo-admin@example.com", Role.admin, "01700000002"),
    ("staff", "Demo Staff", "demo-staff@example.com", Role.staff, "01700000003"),
    ("accountant", "Demo Accountant", "demo-accountant@example.com", Role.accountant, "01700000004"),
    ("customer", "Demo Customer", "demo-customer@example.com", Role.customer, "01700000005"),
    ("customer_two", "Demo Customer Two", "demo-customer-two@example.com", Role.customer, "01700000006"),
    ("customer_three", "Demo Customer Three", "demo-customer-three@example.com", Role.customer, "01700000007"),
    ("holder_20", "Demo Shareholder 20", "demo-holder-20@example.com", Role.shareholder, "01700000008"),
    ("holder_12", "Demo Shareholder 12", "demo-holder-12@example.com", Role.shareholder, "01700000009"),
    ("holder_8", "Demo Shareholder 8", "demo-holder-8@example.com", Role.shareholder, "01700000010"),
    ("holder_6", "Demo Shareholder 6", "demo-holder-6@example.com", Role.shareholder, "01700000011"),
    ("holder_4", "Demo Shareholder 4", "demo-holder-4@example.com", Role.shareholder, "01700000012"),
]

PAYMENT_METHODS = [
    ("cash", "Cash", False),
    ("bkash", "bKash", True),
    ("bank_transfer", "Bank transfer", True),
    ("card", "Card", False),
    ("other", "Other", False),
    ("online_simulated", "Online (SIMULATED)", False),
]

EXPENSE_CATEGORIES = [
    ("electricity", "Electricity"),
    ("cleaning", "Cleaning"),
    ("maintenance", "Maintenance"),
    ("supplies", "Supplies"),
    ("salary", "Salary"),
    ("other", "Other"),
]


def _month_start(day: date, offset: int = 0) -> date:
    month_index = day.year * 12 + day.month - 1 + offset
    year, month_index = divmod(month_index, 12)
    return date(year, month_index + 1, 1)


def _month_end(day: date) -> date:
    return _month_start(day, 1) - timedelta(days=1)


def _utc_datetime(day: date, hour: int, minute: int = 0) -> datetime:
    local = datetime.combine(day, time(hour, minute), tzinfo=BUSINESS_TZ)
    return local.astimezone(UTC)


def _clear_database(db: Session) -> None:
    db.rollback()
    dialect = db.bind.dialect.name if db.bind else ""
    if dialect == "postgresql":
        table_names = ", ".join(
            f'"{table.name}"' for table in Base.metadata.sorted_tables
        )
        db.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
    elif dialect == "sqlite":
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    else:
        raise RuntimeError(f"Demo reset is not supported for database dialect {dialect}")
    db.commit()
    db.expunge_all()


def _password_for_seed() -> str:
    if settings.app_env == "demo":
        return os.getenv("DEMO_PASSWORD") or DEMO_PASSWORD
    password = os.getenv("DEMO_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError(
            "Set DEMO_PASSWORD to at least 12 characters when seeding development data"
        )
    return password


def _seed_users(db: Session, password: str) -> dict[str, User]:
    users: dict[str, User] = {}
    password_hash = hash_password(password)
    for key, name, email, role, phone in USER_SPECS:
        user = User(
            email=email,
            full_name=name,
            phone=phone,
            address="Demo address, Dhaka",
            password_hash=password_hash,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.flush()
        users[key] = user
        record(
            db,
            users.get("owner"),
            "demo.user_seed",
            "user",
            user.id,
            after={"email": user.email, "role": user.role.value},
        )
    return users


def _seed_reference_data(db: Session) -> None:
    for code, label, requires_reference in PAYMENT_METHODS:
        method = db.get(PaymentMethod, code)
        if method is None:
            method = PaymentMethod(code=code, label=label, requires_reference=requires_reference)
            db.add(method)
        method.label = label
        method.is_active = True
        method.requires_reference = requires_reference
    for code, label in EXPENSE_CATEGORIES:
        category = db.get(ExpenseCategory, code)
        if category is None:
            category = ExpenseCategory(code=code, label=label)
            db.add(category)
        category.label = label
        category.is_active = True


def _seed_facilities(db: Session) -> tuple[Facility, Facility]:
    turf = Facility(facility_type=FacilityType.turf, name="Demo Turf", is_active=True)
    pool = Facility(facility_type=FacilityType.pool, name="Demo Pool", is_active=True)
    db.add_all([turf, pool])
    db.flush()
    for weekday in range(7):
        db.add_all([
            OperatingSchedule(
                facility_id=turf.id,
                weekday=weekday,
                open_time=time(8),
                close_time=time(23),
                is_closed=False,
            ),
            OperatingSchedule(
                facility_id=pool.id,
                weekday=weekday,
                open_time=time(8),
                close_time=time(20),
                is_closed=False,
            ),
            PoolSessionTemplate(
                facility_id=pool.id,
                weekday=weekday,
                start_time=time(10),
                end_time=time(12),
                capacity=30,
                price_per_person=Decimal("1000.00"),
                is_active=True,
            ),
            PoolSessionTemplate(
                facility_id=pool.id,
                weekday=weekday,
                start_time=time(14),
                end_time=time(16),
                capacity=30,
                price_per_person=Decimal("1000.00"),
                is_active=True,
            ),
        ])
    db.add(TurfPrice(
        facility_id=turf.id,
        weekday=None,
        start_time=None,
        end_time=None,
        price=Decimal("5000.00"),
        is_active=True,
    ))
    return turf, pool


def _seed_pool_sessions(
    db: Session,
    pool: Facility,
    today: date,
) -> dict[tuple[date, int], PoolSession]:
    sessions: dict[tuple[date, int], PoolSession] = {}
    for day_offset in range(15):
        session_date = today + timedelta(days=day_offset)
        for hour in (10, 14):
            capacity = 5 if day_offset in (3, 4) and hour == 10 else 30
            session = PoolSession(
                facility_id=pool.id,
                date=session_date,
                start_at=_utc_datetime(session_date, hour),
                end_at=_utc_datetime(session_date, hour + 2),
                capacity=capacity,
                price_per_person=Decimal("1000.00"),
            )
            db.add(session)
            sessions[(session_date, hour)] = session
    db.flush()
    return sessions


def _seed_contact(db: Session, user: User) -> CustomerContact:
    contact = CustomerContact(
        user_id=user.id,
        name=user.full_name,
        phone=user.phone or "01700000000",
        address=user.address,
    )
    db.add(contact)
    db.flush()
    return contact


def _seed_booking(
    db: Session,
    *,
    ref: str,
    facility_id: int,
    contact: CustomerContact,
    creator: User,
    channel: BookingChannel,
    status: BookingStatus,
    total: Decimal,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    pool_session: PoolSession | None = None,
    participants: int | None = None,
    created_at: datetime | None = None,
    hold_expires_at: datetime | None = None,
) -> Booking:
    booking = Booking(
        ref=ref,
        facility_id=facility_id,
        channel=channel,
        status=status,
        customer_contact_id=contact.id,
        created_by_user_id=creator.id,
        created_at=created_at or utcnow(),
        hold_expires_at=hold_expires_at,
        total_amount=total,
        currency=settings.currency,
        notes="DEMO DATA — no real service or payment",
        starts_at=starts_at,
        ends_at=ends_at,
        pool_session_id=pool_session.id if pool_session else None,
        participants=participants,
    )
    db.add(booking)
    db.flush()
    if status in (BookingStatus.confirmed, BookingStatus.cancelled, BookingStatus.expired):
        db.add_all([
            BookingEvent(
                booking_id=booking.id,
                actor_id=creator.id,
                from_status=None,
                to_status=BookingStatus.held,
                reason="Demo booking created",
            ),
            BookingEvent(
                booking_id=booking.id,
                actor_id=creator.id,
                from_status=BookingStatus.held,
                to_status=status,
                reason="Demo status history",
            ),
        ])
    else:
        db.add(BookingEvent(
            booking_id=booking.id,
            actor_id=creator.id,
            from_status=None,
            to_status=status,
            reason="Demo booking created",
        ))
    return booking


def _seed_payment(
    db: Session,
    *,
    ref: str,
    booking: Booking,
    method: str,
    status: PaymentStatus,
    amount: Decimal,
    received_at: datetime,
    recorded_by: User,
    verified_by: User | None = None,
    verified_at: datetime | None = None,
) -> Payment:
    payment = Payment(
        ref=ref,
        booking_id=booking.id,
        amount=amount,
        currency=settings.currency,
        method=method,
        status=status,
        received_at=received_at,
        recorded_at=received_at,
        verified_at=verified_at,
        recorded_by=recorded_by.id,
        verified_by=verified_by.id if verified_by else None,
        trx_id=f"DEMO-{ref}" if method != "cash" else None,
        notes="DEMO DATA — no real payment was made",
    )
    db.add(payment)
    db.flush()
    if status == PaymentStatus.verified:
        db.add_all([
            PaymentEvent(
                payment_id=payment.id,
                actor_id=recorded_by.id,
                from_status=None,
                to_status=PaymentStatus.received,
                reason="Demo payment recorded",
            ),
            PaymentEvent(
                payment_id=payment.id,
                actor_id=verified_by.id if verified_by else None,
                from_status=PaymentStatus.received,
                to_status=PaymentStatus.verified,
                reason="Demo payment verified",
            ),
        ])
    else:
        db.add(PaymentEvent(
            payment_id=payment.id,
            actor_id=recorded_by.id,
            from_status=None,
            to_status=status,
            reason="Demo payment status",
        ))
    record(
        db,
        recorded_by,
        "demo.payment_seed",
        "payment",
        payment.ref,
        after={"status": status.value, "method": method, "amount": str(amount)},
        reason="DEMO data; no real payment was received",
    )
    return payment


def _new_walk_in_contact(db: Session) -> CustomerContact:
    contact = CustomerContact(
        name="Demo Walk-in Customer",
        phone="01700000020",
        address="Demo address, Dhaka",
    )
    db.add(contact)
    db.flush()
    return contact


def _seed_expenses(
    db: Session,
    users: dict[str, User],
    report_month: date,
    older_month: date,
) -> None:
    staff = users["staff"]
    accountant = users["accountant"]
    approved = create_expense(
        db,
        staff,
        expense_date=report_month + timedelta(days=5),
        payment_date=report_month + timedelta(days=5),
        category="electricity",
        description="Demo electricity bill",
        amount=Decimal("1500.00"),
        method="cash",
        vendor="Demo utility provider",
        notes="DEMO DATA",
    )
    approve_expense(db, approved, accountant)
    create_expense(
        db,
        staff,
        expense_date=older_month + timedelta(days=12),
        payment_date=older_month + timedelta(days=12),
        category="maintenance",
        description="Demo pending maintenance",
        amount=Decimal("750.00"),
        method="bkash",
        vendor="Demo maintenance vendor",
        notes="DEMO DATA",
    )
    rejected = create_expense(
        db,
        staff,
        expense_date=older_month + timedelta(days=15),
        payment_date=older_month + timedelta(days=15),
        category="supplies",
        description="Demo rejected supplies",
        amount=Decimal("250.00"),
        method="bank_transfer",
        vendor="Demo supplies vendor",
        notes="DEMO DATA",
    )
    reject_expense(db, rejected, accountant, "DEMO: illustrative rejection")


def _seed_closing(db: Session, users: dict[str, User], report_day: date) -> None:
    closing = submit_closing(
        db,
        report_day,
        users["staff"],
        "DEMO: monthly closing sample",
        None,
    )
    review_closing(db, closing, users["owner"], "DEMO: sample closing reviewed")


def _seed_shareholders(db: Session, users: dict[str, User], owner: User) -> None:
    for key, shares in (
        ("holder_20", 20),
        ("holder_12", 12),
        ("holder_8", 8),
        ("holder_6", 6),
        ("holder_4", 4),
    ):
        user = users[key]
        shareholder = Shareholder(
            user_id=user.id,
            name=user.full_name,
            email=user.email,
            is_active=True,
            notes="DEMO shareholder",
            acquisition_amount=Decimal(shares * 250000),
        )
        db.add(shareholder)
        db.flush()
        db.add(Shareholding(
            shareholder_id=shareholder.id,
            shares=shares,
            effective_from=date(2020, 1, 1),
        ))
        record(
            db,
            owner,
            "demo.shareholder_seed",
            "shareholder",
            shareholder.id,
            after={"shares": shares, "effective_from": "2020-01-01"},
        )


def seed_demo(db: Session, *, reset: bool = False) -> None:
    if settings.app_env not in ("development", "demo"):
        raise RuntimeError("Demo seeding is permitted only when APP_ENV is development or demo")
    if reset:
        _clear_database(db)
    if db.scalar(select(BusinessSetting).where(BusinessSetting.key == "demo_seed_version")):
        raise RuntimeError("Demo data already exists; use --reset to replace it")

    password = _password_for_seed()
    _seed_reference_data(db)
    now = datetime.now(BUSINESS_TZ)
    today = now.date()
    current_month = _month_start(today)
    previous_month = _month_start(today, -1)
    older_month = _month_start(today, -2)

    users = _seed_users(db, password)
    owner = users["owner"]
    staff = users["staff"]
    accountant = users["accountant"]
    contacts = {
        key: _seed_contact(db, users[key])
        for key in ("customer", "customer_two", "customer_three")
    }

    turf, pool = _seed_facilities(db)
    pool_sessions = _seed_pool_sessions(db, pool, today)
    for key, value in {
        "business_name": "Turf & Pool Manager — DEMO",
        "payment_instructions": "DEMO ONLY. No real payment is accepted.",
        "booking_horizon_days": "60",
        "turf_slot_step_minutes": "30",
        "turf_duration_minutes": "60",
        "hold_minutes_online": "10",
        "hold_minutes_phone": "30",
        "email_demo_failure_pending": "true",
        "demo_seed_version": "1",
    }.items():
        BusinessSetting.set(db, key, value)

    report_day = _month_end(previous_month)
    report_booking = _seed_booking(
        db,
        ref="BK-DEMO-0001",
        facility_id=turf.id,
        contact=contacts["customer"],
        creator=users["customer"],
        channel=BookingChannel.online,
        status=BookingStatus.confirmed,
        total=Decimal("5000.00"),
        starts_at=_utc_datetime(report_day, 10),
        ends_at=_utc_datetime(report_day, 11),
        created_at=_utc_datetime(report_day - timedelta(days=4), 12),
    )
    _seed_payment(
        db,
        ref="PAY-DEMO-0001",
        booking=report_booking,
        method="cash",
        status=PaymentStatus.verified,
        amount=Decimal("5000.00"),
        received_at=_utc_datetime(report_day, 18),
        recorded_by=staff,
        verified_by=accountant,
        verified_at=_utc_datetime(current_month, 9),
    )

    phone_day = today + timedelta(days=6)
    phone_booking = _seed_booking(
        db,
        ref="BK-DEMO-0002",
        facility_id=turf.id,
        contact=contacts["customer_two"],
        creator=staff,
        channel=BookingChannel.phone,
        status=BookingStatus.held,
        total=Decimal("5000.00"),
        starts_at=_utc_datetime(phone_day, 17),
        ends_at=_utc_datetime(phone_day, 18),
        hold_expires_at=(now + timedelta(hours=2)).astimezone(UTC),
        created_at=now.astimezone(UTC),
    )
    _seed_payment(
        db,
        ref="PAY-DEMO-0002",
        booking=phone_booking,
        method="bkash",
        status=PaymentStatus.received,
        amount=Decimal("5000.00"),
        received_at=now.astimezone(UTC),
        recorded_by=staff,
    )

    old_booking_day = older_month + timedelta(days=10)
    walk_in_booking = _seed_booking(
        db,
        ref="BK-DEMO-0003",
        facility_id=turf.id,
        contact=_new_walk_in_contact(db),
        creator=staff,
        channel=BookingChannel.walk_in,
        status=BookingStatus.cancelled,
        total=Decimal("5000.00"),
        starts_at=_utc_datetime(old_booking_day, 16),
        ends_at=_utc_datetime(old_booking_day, 17),
        created_at=_utc_datetime(old_booking_day - timedelta(days=1), 12),
    )
    _seed_payment(
        db,
        ref="PAY-DEMO-0003",
        booking=walk_in_booking,
        method="bank_transfer",
        status=PaymentStatus.rejected,
        amount=Decimal("1000.00"),
        received_at=_utc_datetime(old_booking_day, 15),
        recorded_by=staff,
    )
    _seed_booking(
        db,
        ref="BK-DEMO-0004",
        facility_id=turf.id,
        contact=contacts["customer_three"],
        creator=users["customer_three"],
        channel=BookingChannel.online,
        status=BookingStatus.expired,
        total=Decimal("5000.00"),
        starts_at=_utc_datetime(old_booking_day, 18),
        ends_at=_utc_datetime(old_booking_day, 19),
        hold_expires_at=_utc_datetime(old_booking_day, 9),
        created_at=_utc_datetime(old_booking_day - timedelta(days=1), 12),
    )

    for offset in (3, 4):
        pool_day = today + timedelta(days=offset)
        _seed_booking(
            db,
            ref=f"BK-DEMO-P{offset:03d}",
            facility_id=pool.id,
            contact=contacts["customer_three"],
            creator=users["customer_three"],
            channel=BookingChannel.online,
            status=BookingStatus.confirmed,
            total=Decimal("3000.00"),
            pool_session=pool_sessions[(pool_day, 10)],
            participants=3,
        )

    _seed_expenses(db, users, previous_month, older_month)
    _seed_closing(db, users, report_day)
    _seed_shareholders(db, users, owner)

    year, month = previous_month.year, previous_month.month
    update_eligible_shares(
        db, accountant, year, month, 50, "DEMO: confirm 50 eligible shares",
    )
    set_distribution(
        db, accountant, year, month, Decimal("2500.00"),
        "DEMO: illustrative distribution pool",
    )
    for key, label in CHECKLIST:
        update_checklist(db, accountant, year, month, key, True, f"DEMO reviewed: {label}")
    submit_for_review(db, accountant, year, month, "DEMO: sample report prepared")
    approve_report(db, owner, year, month, None)

    _ensure_period(db, current_month.year, current_month.month, accountant)
    db.commit()
    print(
        "Demo data seeded: users for all roles, facilities, bookings, payments, "
        "expenses, a reviewed closing, one approved report and one open report."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset safe Turf & Pool demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="clear application tables and reseed (development/demo only)",
    )
    args = parser.parse_args()
    if settings.app_env not in ("development", "demo"):
        parser.error("refusing to seed unless APP_ENV is development or demo")
    try:
        with SessionLocal() as db:
            seed_demo(db, reset=args.reset)
    except (HTTPException, RuntimeError) as exc:
        parser.error(str(exc.detail if isinstance(exc, HTTPException) else exc))


if __name__ == "__main__":
    main()
