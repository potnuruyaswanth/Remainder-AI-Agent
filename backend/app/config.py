import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency fallback
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv(Path(".env"))


class Settings(BaseModel):
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    TASKLIST_ID: str = "@default"
    DATABASE_URL: str = "sqlite:///./db.sqlite3"
    JWT_SECRET_KEY: str = "super-secret-key-change-me"
    FRONTEND_URL: str = "http://localhost:5173"
    SYNC_INTERVAL_MIN: int = 5
    SCHEDULER_ENABLED: bool = False
    SCHEDULER_INTERVAL_MINUTES: int = 5
    SCHEDULER_MAX_CONCURRENT_RUNS: int = 1
    SCHEDULER_RETRY_DELAY_SECONDS: int = 5
    SCHEDULER_USER_ID: Optional[int] = None
    # Development fallback so local tests can run before a real secret is configured.
    ENCRYPTION_KEY: str = "YSZgbaGtndlDA6E2badxBC4r2TnkmfweX_DPth7zxH4="
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GOOGLE_SCOPES: List[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/tasks",
        ]
    )

    @classmethod
    def from_env(cls) -> "Settings":
        default_scopes = cls.model_fields["GOOGLE_SCOPES"].default_factory()
        scopes_value = os.getenv("GOOGLE_SCOPES", "")
        scopes = [scope.strip() for scope in scopes_value.split(",") if scope.strip()] or default_scopes
        scheduler_user_id_raw = os.getenv("SCHEDULER_USER_ID", "").strip()

        return cls(
            GOOGLE_CLIENT_ID=os.getenv("GOOGLE_CLIENT_ID", ""),
            GOOGLE_CLIENT_SECRET=os.getenv("GOOGLE_CLIENT_SECRET", ""),
            GOOGLE_REDIRECT_URI=os.getenv(
                "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/callback"
            ),
            TASKLIST_ID=os.getenv("TASKLIST_ID", "@default"),
            DATABASE_URL=os.getenv("DATABASE_URL", "sqlite:///./db.sqlite3"),
            JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "super-secret-key-change-me"),
            FRONTEND_URL=os.getenv("FRONTEND_URL", "http://localhost:5173"),
            SYNC_INTERVAL_MIN=int(os.getenv("SYNC_INTERVAL_MIN", "5")),
            SCHEDULER_ENABLED=_parse_bool(os.getenv("SCHEDULER_ENABLED", "false")),
            SCHEDULER_INTERVAL_MINUTES=int(
                os.getenv("SCHEDULER_INTERVAL_MINUTES", os.getenv("SYNC_INTERVAL_MIN", "5"))
            ),
            SCHEDULER_MAX_CONCURRENT_RUNS=int(os.getenv("SCHEDULER_MAX_CONCURRENT_RUNS", "1")),
            SCHEDULER_RETRY_DELAY_SECONDS=int(os.getenv("SCHEDULER_RETRY_DELAY_SECONDS", "5")),
            SCHEDULER_USER_ID=int(scheduler_user_id_raw) if scheduler_user_id_raw else None,
            ENCRYPTION_KEY=os.getenv(
                "ENCRYPTION_KEY", "YSZgbaGtndlDA6E2badxBC4r2TnkmfweX_DPth7zxH4="
            ),
            GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
            GEMINI_MODEL=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            GOOGLE_SCOPES=scopes,
        )


def _parse_bool(value: str) -> bool:
    """Parse common environment-style boolean strings."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


settings = Settings.from_env()
