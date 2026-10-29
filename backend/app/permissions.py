"""Single source of truth for who may do what. Enforced by the API, not the UI."""
from fastapi import Depends, HTTPException

from .models import Role, User

O, A, S, AC, SH, C = (Role.owner, Role.admin, Role.staff, Role.accountant,
                      Role.shareholder, Role.customer)

PERMISSIONS: dict[str, set[Role]] = {
    # Phase 1
    "users.manage": {O},
    "audit.view": {O},
    # Facilities and bookings (Phases 2-3)
    "facility.configure": {O, A},
    "timetable.view": {O, A, S, SH},
    "booking.create_self": {C},
    "booking.create_for_customer": {O, A, S},
    "booking.manage": {O, A, S},
    # Payments (Phase 4)
    "payment.record": {O, A, S, AC},
    "payment.verify": {O, A, AC},
    # Expenses and closing (Phase 5)
    "expense.enter": {O, A, S, AC},
    "expense.approve": {O, AC},
    "closing.submit": {O, A, S},
    "closing.review": {O, A},
    # Shareholders and reports (Phases 6-7)
    "shareholder.manage": {O},
    "report.view_full": {O, A, AC},
    "report.prepare": {O, AC},
    "report.approve": {O},
    "report.view_approved": {O, A, AC, SH},
}


def permissions_for(role: Role) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


def has_permission(role: Role, perm: str) -> bool:
    return role in PERMISSIONS.get(perm, set())


def require_permission(perm: str):
    from .deps import get_current_user

    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, perm):
            raise HTTPException(403, f"Your role cannot perform this action ({perm})")
        return user

    return dep
