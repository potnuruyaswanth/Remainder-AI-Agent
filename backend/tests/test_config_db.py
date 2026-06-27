import os
from app.config import settings
from app.database import SessionLocal, init_db
from app.utils.logger import logger

def test_config_loading():
    assert settings.TASKLIST_ID == "@default"
    assert any("gmail.readonly" in scope for scope in settings.GOOGLE_SCOPES)
    assert any("tasks" in scope for scope in settings.GOOGLE_SCOPES)
    logger.info("Config verified successfully!")

def test_database_init():
    # Try to initialize the DB and open a session
    init_db()
    db = SessionLocal()
    assert db is not None
    db.close()
    logger.info("Database initialization and connection verified successfully!")
