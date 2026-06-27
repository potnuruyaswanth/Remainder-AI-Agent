from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TaskSyncStatus = Literal["pending", "synced", "failed", "deleted"]
GoogleTaskStatus = Literal["needsAction", "completed"]


class GoogleTaskRequest(BaseModel):
    """
    Request payload used for Google Tasks API create and update operations.

    The mapper produces this model so API communication code never has to
    understand TaskCandidate internals directly.
    """

    title: str = Field(min_length=1, max_length=1024)
    notes: str = Field(default="", max_length=8192)
    due: Optional[str] = None
    status: GoogleTaskStatus = "needsAction"

    model_config = ConfigDict(extra="forbid")


class GoogleTaskRecord(BaseModel):
    """Typed view of a Google Task resource returned by the API."""

    google_task_id: str = Field(alias="id")
    title: str = ""
    notes: str = ""
    due: Optional[str] = None
    status: GoogleTaskStatus = "needsAction"
    updated: Optional[str] = None
    deleted: bool = False
    web_view_link: Optional[str] = Field(default=None, alias="webViewLink")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class TaskSyncResult(BaseModel):
    """
    Outcome of one synchronization action against Google Tasks.

    This model is returned from CRUD and batch sync operations so callers never
    need to interpret raw dictionaries or boolean flags.
    """

    success: bool
    google_task_id: Optional[str] = None
    sync_status: TaskSyncStatus
    error_message: Optional[str] = None
    synced_at: Optional[datetime] = None
    local_task_id: Optional[int] = None

    model_config = ConfigDict(extra="forbid")
