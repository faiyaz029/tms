from fastapi import HTTPException
from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from .config import settings


def verify_google_token(credential: str) -> dict:
    """Verify a Google ID token server-side. Replaced with a stub in tests."""
    if not settings.google_client_id:
        raise HTTPException(503, "Google login is not configured on this server")
    try:
        info = id_token.verify_oauth2_token(
            credential, g_requests.Request(), settings.google_client_id)
    except ValueError:
        raise HTTPException(401, "Google sign-in could not be verified")
    if not info.get("email_verified"):
        raise HTTPException(401, "Your Google email is not verified")
    return info
