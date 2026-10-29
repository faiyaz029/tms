from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "demo", "production"] = "development"

    database_url: str = "postgresql://turf:turf@localhost:5432/turfpool"
    test_database_url: str | None = None
    secret_key: str = "change-me-in-env"
    access_token_minutes: int = 60 * 8
    cookie_secure: bool = False  # set True behind HTTPS in production
    google_client_id: str = ""
    frontend_origin: str = "http://localhost:5173"
    business_timezone: str = "Asia/Dhaka"
    currency: str = "BDT"
    payments_mode: str = "simulated"
    business_name: str = "Turf & Pool Manager"
    email_backend: Literal["console", "outbox", "smtp"] = "outbox"
    email_from: str = "Turf & Pool Manager <noreply@example.com>"
    email_host: str = ""
    email_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_starttls: bool = True
    email_use_ssl: bool = False
    email_simulate_failure_once: bool = True


settings = Settings()
