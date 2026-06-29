from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.task import Task
from app.schemas.task_api import TaskCreateRequest, TaskUpdateRequest


class TaskService:
    """Service layer for local task CRUD operations used by the REST API."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_tasks(self, user_id: int) -> List[Task]:
        """Return all tasks for a user ordered by newest update first."""
        return (
            self.db.query(Task)
            .filter_by(user_id=user_id)
            .order_by(Task.updated_at.desc())
            .all()
        )

    def get_task(self, user_id: int, task_id: int) -> Optional[Task]:
        """Return one task for a user or None if it does not exist."""
        return self.db.query(Task).filter_by(id=task_id, user_id=user_id).first()

    def create_task(self, user_id: int, payload: TaskCreateRequest) -> Task:
        """Create and persist a new task for a user."""
        task = Task(
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            deadline=payload.deadline,
            priority=payload.priority,
            completed=payload.completed,
            sync_status="pending",
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def update_task(self, task: Task, payload: TaskUpdateRequest) -> Task:
        """Update a task with partial request data."""
        data = payload.model_dump(exclude_unset=True)
        for field_name, value in data.items():
            setattr(task, field_name, value)
        task.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(task)
        return task

    def delete_task(self, task: Task) -> None:
        """Delete a task from the local database."""
        self.db.delete(task)
        self.db.commit()
