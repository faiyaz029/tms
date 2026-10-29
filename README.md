# Turf & Pool Manager

FastAPI + PostgreSQL + React (TypeScript, Tailwind). Phases 1–8 are implemented.
`demo/turf-pool-demo.html` is the clickable design reference for the finished system.

## What works now
- Email/password registration and login, and Google login
- Customers must have a valid Bangladeshi mobile number (`01XXXXXXXXX`) and an address; Google signups are sent to a "complete your profile" screen
- Six roles with a central permission matrix (`backend/app/permissions.py`) enforced by the API
- Staff, accountant, admin, shareholder and owner accounts are created by the owner (no public signup for those roles)
- httpOnly cookie sessions with CSRF protection, login rate limiting, bcrypt hashing
- Facility schedules, pool sessions, database-backed settings and availability
- Online, phone and walk-in held bookings, contact lookup, hold extension/release, event history and customer booking privacy
- Turf overlap protection with a PostgreSQL exclusion constraint; pool capacity serialized with row locks
- Append-only audit log, Alembic migrations, PostgreSQL test database, customer and staff booking screens, timetable
- Manual payment recording with independent verification, payment history and receipts
- Online checkout is explicitly SIMULATED; a verified simulated result confirms the booking and never represents a real transfer
- Expense entry, independent approval, daily closing review and monthly shareholder reports
- Immutable approved report snapshots, shareholder-specific statements and honest email preview/retry states
- Permission-checked CSV exports and single-use, rate-limited password reset
- Demo seed/reset data, PostgreSQL and SQLite test suites, and desktop/mobile Playwright coverage

Facility schedule, pricing and settings administration screens are still pending.

## Roles

| Role | Main capabilities |
|---|---|
| Owner | Manage users and shareholders, configure facilities, verify payments, approve reports, view audit history |
| Admin | Manage bookings and facility settings, verify payments, review closings, manage email delivery |
| Staff | Create phone/walk-in bookings, record payments, enter expenses, submit daily closings |
| Accountant | Reconcile payments and expenses, review records, prepare shareholder reports |
| Shareholder | Read approved reports and their own statements; cannot book or edit records |
| Customer | View availability and manage only their own bookings and payments |

The API enforces the central permission matrix; navigation visibility is not an authorization boundary.

## Run with Docker (recommended)
```bash
cp .env.example .env          # set SECRET_KEY; optionally GOOGLE_CLIENT_ID
docker compose up --build
```
Open http://localhost:5173. API docs: http://localhost:8000/docs.
The example `.env` uses `APP_ENV=demo`, which shows a persistent demo banner. Seed the sample data:
```bash
docker compose exec backend python -m app.seed
```
Demo accounts and the end-to-end walkthrough are documented in [docs/DEMO_SCRIPT.md](./docs/DEMO_SCRIPT.md).
Reset is destructive and clears application tables, so use it only with a disposable development/demo database:
```bash
docker compose exec backend python -m app.seed --reset
```

Create the first owner (in another terminal):
```bash
docker compose exec backend python -m app.cli create-owner --email you@example.com --name "Your Name"
```
Expire elapsed holds from a scheduled task or operator command:
```bash
docker compose exec backend python -m app.cli expire-holds
```
Migrations run automatically on backend start. To run manually: `docker compose exec backend alembic upgrade head`.

## Run without Docker
Backend (needs PostgreSQL running and a database named `turfpool`):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env       # also set DATABASE_URL if yours differs
alembic upgrade head
python -m app.cli create-owner --email you@example.com --name "Your Name"
uvicorn app.main:app --reload
```
Frontend:
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Tests
```bash
(cd backend && pytest)
docker compose up -d --wait db-test
(cd backend && TEST_DATABASE_URL=postgresql+psycopg://turf:turf@localhost:5433/turfpool_test pytest)
(cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://turf:turf@localhost:5433/turfpool_test alembic upgrade head)
(cd backend && ALEMBIC_DATABASE_URL=postgresql+psycopg://turf:turf@localhost:5433/turfpool_test alembic check)
(cd frontend && npm run build)   # type-checks the frontend
(cd frontend && npx playwright install chromium && npm run test:e2e)
```

The Playwright suite expects the Compose stack and demo data:
```bash
cp .env.example .env
docker compose up --build -d --wait
docker compose exec backend python -m app.seed --reset
cd frontend && npm run test:e2e
```

See [docs/API.md](./docs/API.md), [docs/LIMITATIONS.md](./docs/LIMITATIONS.md), and
[docs/BACKUP_RESTORE.md](./docs/BACKUP_RESTORE.md) for generated API details, constraints, and recovery guidance.
Regenerate the API reference after changing routes or schemas with
`(cd backend && python -m app.openapi_docs)`.

## Google login setup
1. Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID → Web application.
2. Add `http://localhost:5173` (and your real domain later) as an authorized JavaScript origin.
3. Put the client ID in `GOOGLE_CLIENT_ID` (root `.env`). The backend verifies every Google token itself.

## Phone number validation
The format is validated (`01[3-9]XXXXXXXX`, `+880`/`880` prefixes accepted and normalized). Proving the number
belongs to the person needs an SMS OTP provider, which is not included yet.

## Roadmap
2. Facilities, schedules, pool sessions, booking horizon, availability (admin UI pending)
3. Online, phone and walk-in bookings, holds, overbooking protection (implemented)
4. SIMULATED checkout, manual payments, independent verification and receipts (implemented)
5. Expenses with `EXP-` references, daily closing (implemented)
6. Shareholders and monthly reports with approval snapshots (implemented)
7. Statements, email previews, exports, password reset (implemented)
8. QA, end-to-end tests, demo data, deployment and backups (implemented)
9. Optional scalability work; agree on a scale tier before starting

## Known limitations
See [docs/LIMITATIONS.md](./docs/LIMITATIONS.md). Set a strong `SECRET_KEY` and `COOKIE_SECURE=true`
before any real deployment; the documented demo credentials are public and must never be reused.
