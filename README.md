# Turf & Pool Manager

FastAPI + PostgreSQL + React (TypeScript, Tailwind). This is **Phase 1: foundation**.
`demo/turf-pool-demo.html` is the clickable design reference for the finished system.

## What works now (Phase 1)
- Email/password registration and login, and Google login
- Customers must have a valid Bangladeshi mobile number (`01XXXXXXXXX`) and an address; Google signups are sent to a "complete your profile" screen
- Six roles with a central permission matrix (`backend/app/permissions.py`) enforced by the API
- Staff, accountant, admin, shareholder and owner accounts are created by the owner (no public signup for those roles)
- httpOnly cookie sessions with CSRF protection, login rate limiting, bcrypt hashing
- Append-only audit log table, Alembic migration, 12 backend tests
- Mobile-first app shell with role-based navigation (bottom bar on phones, sidebar on desktop)

Pages for bookings, payments, expenses and reports are placeholders until their phases.

## Run with Docker (recommended)
```bash
cp .env.example .env          # set SECRET_KEY; optionally GOOGLE_CLIENT_ID
docker compose up --build
```
Open http://localhost:5173. API docs: http://localhost:8000/docs.

Create the first owner (in another terminal):
```bash
docker compose exec backend python -m app.cli create-owner --email you@example.com --name "Your Name"
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
cd backend && pytest
cd frontend && npm run build   # type-checks the frontend
```

## Google login setup
1. Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID → Web application.
2. Add `http://localhost:5173` (and your real domain later) as an authorized JavaScript origin.
3. Put the client ID in `GOOGLE_CLIENT_ID` (root `.env`). The backend verifies every Google token itself.

## Phone number validation
The format is validated (`01[3-9]XXXXXXXX`, `+880`/`880` prefixes accepted and normalized). Proving the number
belongs to the person needs an SMS OTP provider, which is not included yet.

## Roadmap
2. Facilities, schedules, pool sessions, booking horizon, availability
3. Online, phone and walk-in bookings, holds, overbooking protection (PostgreSQL exclusion constraint)
4. Simulated and manual payments, verification
5. Expenses with `EXP-` references, daily closing
6. Shareholders and monthly reports with approval snapshots
7. Statements, email previews, exports
8. QA, end-to-end tests, demo data, deployment and backups

## Known limitations
- Login rate limiter is in memory (single server only)
- No password reset yet; no SMS verification
- Set a strong `SECRET_KEY` and `COOKIE_SECURE=true` before any real deployment
