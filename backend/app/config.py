from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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


settings = Settings()
