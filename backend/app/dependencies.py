from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.agent.email_task_agent import EmailTaskAgent
from app.config import settings
from app.database import get_db
from app.routers.auth import get_current_user
from app.services.dashboard_service import DashboardService
from app.services.gemini_service import GeminiService
from app.services.gmail_service import GmailService
from app.services.google_tasks_service import GoogleTasksService
from app.services.settings_service import SettingsService
from app.services.task_service import TaskService


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    """Provide a TaskService instance for route handlers."""
    return TaskService(db)


def get_dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    """Provide a DashboardService instance for route handlers."""
    return DashboardService(db)


def get_gmail_service(db: Session = Depends(get_db)) -> GmailService:
    """Provide a GmailService instance for route handlers."""
    return GmailService(db)


def get_google_tasks_service(db: Session = Depends(get_db)) -> GoogleTasksService:
    """Provide a GoogleTasksService instance for route handlers."""
    return GoogleTasksService(db)


def get_settings_service() -> SettingsService:
    """Provide a SettingsService instance for route handlers."""
    return SettingsService()


def get_agent(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> EmailTaskAgent:
    """Provide a configured EmailTaskAgent for the authenticated user."""
    return EmailTaskAgent(
        gmail_service=GmailService(db),
        gemini_service=GeminiService(),
        google_tasks_service=GoogleTasksService(db),
        user_id=current_user.id,
    )


def get_scheduler_state(request: Request):
    """Expose the application scheduler instance from FastAPI state."""
    return getattr(request.app.state, "agent_scheduler", None)
