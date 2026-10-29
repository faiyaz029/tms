from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import (
    auth, availability, bookings, expenses, exports, facilities, mail, payments, reports,
    settings as app_settings, users,
)

app = FastAPI(title="Turf & Pool Manager API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(users.router)
api.include_router(facilities.router)
api.include_router(availability.router)
api.include_router(bookings.router)
api.include_router(bookings.my_router)
api.include_router(payments.router)
api.include_router(payments.booking_router)
api.include_router(expenses.router)
api.include_router(reports.router)
api.include_router(mail.router)
api.include_router(exports.router)
api.include_router(app_settings.router)


@api.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "currency": settings.currency, "timezone": settings.business_timezone}


app.include_router(api)
