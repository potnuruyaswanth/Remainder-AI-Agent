import os
from pathlib import Path
from typing import List

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
    # Development fallback so local tests can run before a real secret is configured.
    ENCRYPTION_KEY: str = "YSZgbaGtndlDA6E2badxBC4r2TnkmfweX_DPth7zxH4="
    GEMINI_API_KEY: str = ""
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
            ENCRYPTION_KEY=os.getenv(
                "ENCRYPTION_KEY", "YSZgbaGtndlDA6E2badxBC4r2TnkmfweX_DPth7zxH4="
            ),
            GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
            GOOGLE_SCOPES=scopes,
        )


settings = Settings.from_env()
