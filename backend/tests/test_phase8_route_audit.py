import re

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app.main import app
from app.models import Role, User
from app.permissions import PERMISSIONS

PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/settings/public"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("POST", "/api/auth/google"),
    ("POST", "/api/auth/logout"),
}


def _route_path(path: str) -> str:
    examples = {
        "year": "2026",
        "month": "1",
        "key": "payments_verified",
        "ref": "BK-TEST-0001",
        "expense_ref": "EXP-260101-0001",
    }

    def replace(match):
        name = match.group(1).split(":", 1)[0]
        return examples.get(name, "1")

    return re.sub(r"\{([^}]+)}", replace, path)


def _api_routes():
    def walk(router, prefix=""):
        for route in router.routes:
            if isinstance(route, APIRoute):
                path = route.path if route.path.startswith("/api/") else prefix + route.path
                if path.startswith("/api/"):
                    yield route, path
            else:
                context = getattr(route, "include_context", None)
                if context:
                    yield from walk(context.included_router, context.prefix)

    return list(walk(app))


def _permission_dependencies(dependant):
    found = []
    for child in dependant.dependencies:
        permission = getattr(child.call, "required_permission", None)
        if permission:
            found.append((permission, child.call))
        found.extend(_permission_dependencies(child))
    return found


@pytest.mark.parametrize(
    ("route", "path", "method"),
    [
        (route, path, method)
        for route, path in _api_routes()
        for method in route.methods or ()
        if method not in {"HEAD", "OPTIONS"}
    ],
)
def test_all_non_public_api_routes_require_authentication(client, route, path, method):
    key = (method, path)
    if key in PUBLIC_ROUTES:
        return
    response = client.request(
        method,
        _route_path(path),
        json={},
        headers={"Idempotency-Key": "route-audit"},
    )
    assert response.status_code == 401, (
        f"{method} {path} was expected to require authentication; "
        f"received {response.status_code}: {response.text}"
    )


def test_every_protected_route_uses_the_central_role_matrix():
    protected_routes = 0
    for route, path in _api_routes():
        permissions = _permission_dependencies(route.dependant)
        if not permissions:
            continue
        protected_routes += 1
        for permission, dependency in permissions:
            assert permission in PERMISSIONS, (
                f"{path} uses unknown permission {permission!r}"
            )
            for role in Role:
                user = User(email="audit@example.com", full_name="Audit", role=role)
                if role in PERMISSIONS[permission]:
                    assert dependency(user=user) is user
                else:
                    with pytest.raises(HTTPException) as error:
                        dependency(user=user)
                    assert error.value.status_code == 403
    assert protected_routes > 0
