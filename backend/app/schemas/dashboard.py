from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.task_api import TaskResponse


class RecentEmailResponse(BaseModel):
    """Dashboard response view for recently processed emails."""

    gmail_id: str
    subject: str = ""
    snippet: str = ""
    processed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncStatusResponse(BaseModel):
    """High-level synchronization summary for the dashboard."""

    pending_tasks: int
    failed_tasks: int
    last_synced_at: Optional[datetime] = None

    model_config = ConfigDict(extra="forbid")


class DashboardStatsResponse(BaseModel):
    """Aggregated dashboard payload returned by /dashboard."""

    todays_tasks: List[TaskResponse]
    upcoming_tasks: List[TaskResponse]
    completed_tasks: List[TaskResponse]
    recent_emails: List[RecentEmailResponse]
    sync_status: SyncStatusResponse
    total_tasks: int
    completed_count: int
    pending_count: int

    model_config = ConfigDict(extra="forbid")
