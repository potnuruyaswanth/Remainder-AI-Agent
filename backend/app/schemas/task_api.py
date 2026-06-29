from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskBase(BaseModel):
    """Shared API schema fields for task requests and responses."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    deadline: Optional[datetime] = None
    priority: str = Field(default="Medium", max_length=20)
    completed: bool = False


class TaskCreateRequest(TaskBase):
    """Request payload for creating a new local task."""


class TaskUpdateRequest(BaseModel):
    """Request payload for updating an existing task."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    deadline: Optional[datetime] = None
    priority: Optional[str] = Field(default=None, max_length=20)
    completed: Optional[bool] = None

    model_config = ConfigDict(extra="forbid")


class TaskResponse(TaskBase):
    """Response schema for one task resource."""

    id: int
    user_id: int
    google_task_id: Optional[str] = None
    sync_status: str
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """Collection wrapper for task list endpoints."""

    tasks: List[TaskResponse]

    model_config = ConfigDict(extra="forbid")
