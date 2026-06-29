from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.email import ProcessedEmail
from app.models.task import Task
from app.schemas.dashboard import DashboardStatsResponse, RecentEmailResponse, SyncStatusResponse
from app.schemas.task_api import TaskResponse


class DashboardService:
    """Service layer that aggregates dashboard-friendly task and email data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_dashboard(self, user_id: int) -> DashboardStatsResponse:
        """Build the dashboard payload for a specific user."""
        now = datetime.utcnow()
        tomorrow = now + timedelta(days=1)
        next_week = now + timedelta(days=7)

        todays_tasks = (
            self.db.query(Task)
            .filter(
                Task.user_id == user_id,
                Task.deadline.isnot(None),
                Task.deadline >= now,
                Task.deadline < tomorrow,
            )
            .order_by(Task.deadline.asc())
            .all()
        )
        upcoming_tasks = (
            self.db.query(Task)
            .filter(
                Task.user_id == user_id,
                Task.deadline.isnot(None),
                Task.deadline >= tomorrow,
                Task.deadline <= next_week,
                Task.completed.is_(False),
            )
            .order_by(Task.deadline.asc())
            .all()
        )
        completed_tasks = (
            self.db.query(Task)
            .filter_by(user_id=user_id, completed=True)
            .order_by(Task.updated_at.desc())
            .limit(10)
            .all()
        )
        recent_emails = (
            self.db.query(ProcessedEmail)
            .filter_by(user_id=user_id)
            .order_by(ProcessedEmail.processed_at.desc())
            .limit(10)
            .all()
        )

        total_tasks = self.db.query(Task).filter_by(user_id=user_id).count()
        completed_count = self.db.query(Task).filter_by(user_id=user_id, completed=True).count()
        pending_count = total_tasks - completed_count
        pending_sync = self.db.query(Task).filter_by(user_id=user_id, sync_status="pending").count()
        failed_sync = self.db.query(Task).filter_by(user_id=user_id, sync_status="failed").count()
        latest_synced_task = (
            self.db.query(Task)
            .filter(Task.user_id == user_id, Task.last_synced_at.isnot(None))
            .order_by(Task.last_synced_at.desc())
            .first()
        )

        return DashboardStatsResponse(
            todays_tasks=[TaskResponse.model_validate(task) for task in todays_tasks],
            upcoming_tasks=[TaskResponse.model_validate(task) for task in upcoming_tasks],
            completed_tasks=[TaskResponse.model_validate(task) for task in completed_tasks],
            recent_emails=[RecentEmailResponse.model_validate(email) for email in recent_emails],
            sync_status=SyncStatusResponse(
                pending_tasks=pending_sync,
                failed_tasks=failed_sync,
                last_synced_at=latest_synced_task.last_synced_at if latest_synced_task else None,
            ),
            total_tasks=total_tasks,
            completed_count=completed_count,
            pending_count=pending_count,
        )

    def processed_email_count(self, user_id: int) -> int:
        """Return the number of processed emails for a user."""
        return self.db.query(ProcessedEmail).filter_by(user_id=user_id).count()
