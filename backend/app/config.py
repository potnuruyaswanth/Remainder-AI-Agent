import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    TASKLIST_ID: str = "@default"
    DATABASE_URL: str = "sqlite:///./db.sqlite3"
    JWT_SECRET_KEY: str = "super-secret-key-change-me"
    SYNC_INTERVAL_MIN: int = 5
    ENCRYPTION_KEY: str = ""  # Base64 Fernet key for token encryption
    GEMINI_API_KEY: str = ""

    # Google API Scopes required by the agent
    GOOGLE_SCOPES: List[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/tasks"
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
