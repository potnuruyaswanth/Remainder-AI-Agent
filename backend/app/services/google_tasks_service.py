from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.task import Task
from app.schemas.google_tasks import GoogleTaskRecord, GoogleTaskRequest, TaskSyncResult
from app.schemas.task_candidate import TaskCandidate
from app.services.auth_service import AuthService
from app.services.task_mapper import TaskMapper
from app.utils.logger import logger

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover - exercised only when optional deps are missing
    def build(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError(
            "Google API client dependencies are not installed. "
            "Install google-api-python-client to use Google Tasks features."
        )

    class HttpError(Exception):
        """Fallback Google API error when googleapiclient is unavailable."""


class GoogleTasksServiceError(RuntimeError):
    """Raised when Google Tasks operations cannot be completed."""


class GoogleTasksAuthenticationError(GoogleTasksServiceError):
    """Raised when no valid Google OAuth credentials are available."""


class GoogleTasksService:
    """Service layer responsible for Google Tasks CRUD and local sync metadata."""

    def __init__(
        self,
        db: Session,
        auth_service_factory: Callable[[Session], AuthService] = AuthService,
        tasks_client_builder: Callable[..., Any] = build,
        task_mapper: Optional[TaskMapper] = None,
    ) -> None:
        self.db = db
        self.auth_service_factory = auth_service_factory
        self.tasks_client_builder = tasks_client_builder
        self.task_mapper = task_mapper or TaskMapper()

    def sync_tasks(self, user_id: int, task_candidates: Sequence[TaskCandidate]) -> List[TaskSyncResult]:
        """
        Synchronize a batch of extracted task candidates.

        This high-level entrypoint exists so future orchestration layers can
        sync a full email's tasks through one service call while preserving
        per-task isolation and typed outcomes.
        """
        results: List[TaskSyncResult] = []

        for task_candidate in task_candidates:
            result = self._sync_single_task(user_id=user_id, task_candidate=task_candidate)
            results.append(result)

        logger.info(
            "Completed Google Tasks batch synchronization.",
            extra={
                "user_id": user_id,
                "candidate_count": len(task_candidates),
                "success_count": sum(1 for result in results if result.success),
            },
        )
        return results

    def create_task(self, user_id: int, task_candidate: TaskCandidate) -> TaskSyncResult:
        """Create a new Google Task and persist its sync metadata locally."""
        local_task = self._upsert_local_task_from_candidate(user_id=user_id, task_candidate=task_candidate)
        if local_task.google_task_id:
            return self.update_task(user_id=user_id, local_task=local_task, task_candidate=task_candidate)

        return self._create_google_task(user_id=user_id, local_task=local_task, task_candidate=task_candidate)

    def update_task(
        self,
        user_id: int,
        local_task: Task,
        task_candidate: TaskCandidate,
    ) -> TaskSyncResult:
        """Update an existing Google Task and refresh local sync metadata."""
        try:
            request_model = self.task_mapper.to_google_task_request(task_candidate)
        except ValidationError as exc:
            return self._mark_sync_failure(local_task, f"Invalid TaskCandidate: {exc}")

        if not local_task.google_task_id:
            return self._create_google_task(user_id=user_id, local_task=local_task, task_candidate=task_candidate)

        def operation() -> Dict[str, Any]:
            tasks_resource = self._tasks_resource(user_id)
            return (
                tasks_resource.update(
                    tasklist=settings.TASKLIST_ID,
                    task=local_task.google_task_id,
                    body=request_model.model_dump(exclude_none=True),
                )
                .execute()
            )

        try:
            response = self._execute_with_retry(operation, operation_name="update", user_id=user_id)
            google_task_record = GoogleTaskRecord.model_validate(response)
        except Exception as exc:
            return self._mark_sync_failure(local_task, self._format_error_message("update", exc))

        self._apply_candidate_to_local_task(local_task, task_candidate)
        return self._mark_sync_success(local_task, google_task_record.google_task_id)

    def delete_task(self, user_id: int, local_task: Task) -> TaskSyncResult:
        """Delete a Google Task and update the local sync status."""
        if not local_task.google_task_id:
            return self._mark_sync_success(local_task, google_task_id=None, sync_status="deleted")

        def operation() -> None:
            tasks_resource = self._tasks_resource(user_id)
            tasks_resource.delete(
                tasklist=settings.TASKLIST_ID,
                task=local_task.google_task_id,
            ).execute()
            return None

        try:
            self._execute_with_retry(operation, operation_name="delete", user_id=user_id)
        except Exception as exc:
            return self._mark_sync_failure(local_task, self._format_error_message("delete", exc))

        return self._mark_sync_success(
            local_task,
            google_task_id=local_task.google_task_id,
            sync_status="deleted",
        )

    def retrieve_task(self, user_id: int, google_task_id: str) -> Optional[GoogleTaskRecord]:
        """Retrieve a Google Task by its Google ID."""
        def operation() -> Dict[str, Any]:
            tasks_resource = self._tasks_resource(user_id)
            return (
                tasks_resource.get(
                    tasklist=settings.TASKLIST_ID,
                    task=google_task_id,
                )
                .execute()
            )

        try:
            response = self._execute_with_retry(operation, operation_name="retrieve", user_id=user_id)
            return GoogleTaskRecord.model_validate(response)
        except Exception:
            logger.error(
                "Failed to retrieve Google Task.",
                extra={"user_id": user_id, "google_task_id": google_task_id},
                exc_info=True,
            )
            return None

    def _sync_single_task(self, user_id: int, task_candidate: TaskCandidate) -> TaskSyncResult:
        """Synchronize one task candidate without stopping the rest of the batch."""
        try:
            local_task = self._find_matching_local_task(user_id=user_id, task_candidate=task_candidate)
            if local_task is None:
                return self.create_task(user_id=user_id, task_candidate=task_candidate)

            return self.update_task(user_id=user_id, local_task=local_task, task_candidate=task_candidate)
        except ValidationError as exc:
            logger.error(
                "Task synchronization skipped because the candidate is invalid.",
                extra={"user_id": user_id, "task_title": getattr(task_candidate, "title", "")},
                exc_info=True,
            )
            return TaskSyncResult(
                success=False,
                google_task_id=None,
                sync_status="failed",
                error_message=f"Invalid TaskCandidate: {exc}",
                synced_at=datetime.utcnow(),
                local_task_id=None,
            )
        except Exception:
            logger.error(
                "Unexpected error while synchronizing a task candidate.",
                extra={"user_id": user_id, "task_title": task_candidate.title},
                exc_info=True,
            )
            return TaskSyncResult(
                success=False,
                google_task_id=None,
                sync_status="failed",
                error_message="Unexpected synchronization error.",
                synced_at=datetime.utcnow(),
                local_task_id=None,
            )

    def _create_google_task(
        self,
        user_id: int,
        local_task: Task,
        task_candidate: TaskCandidate,
    ) -> TaskSyncResult:
        """Create a remote Google Task for a local task record."""
        try:
            request_model = self.task_mapper.to_google_task_request(task_candidate)
        except ValidationError as exc:
            return self._mark_sync_failure(local_task, f"Invalid TaskCandidate: {exc}")

        def operation() -> Dict[str, Any]:
            tasks_resource = self._tasks_resource(user_id)
            return (
                tasks_resource.insert(
                    tasklist=settings.TASKLIST_ID,
                    body=request_model.model_dump(exclude_none=True),
                )
                .execute()
            )

        try:
            response = self._execute_with_retry(operation, operation_name="create", user_id=user_id)
            google_task_record = GoogleTaskRecord.model_validate(response)
        except Exception as exc:
            return self._mark_sync_failure(local_task, self._format_error_message("create", exc))

        self._apply_candidate_to_local_task(local_task, task_candidate)
        return self._mark_sync_success(local_task, google_task_record.google_task_id)

    def _tasks_resource(self, user_id: int) -> Any:
        """Build and return the Google Tasks API resource."""
        auth_service = self.auth_service_factory(self.db)
        credentials = auth_service.get_user_credentials(user_id)
        if credentials is None:
            raise GoogleTasksAuthenticationError(
                f"No valid Google credentials found for user ID {user_id}."
            )

        client = self.tasks_client_builder(
            "tasks",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
        return client.tasks()

    def _find_matching_local_task(self, user_id: int, task_candidate: TaskCandidate) -> Optional[Task]:
        """
        Find an existing local task that likely represents the same extracted task.

        The local database remains the source of truth for deduplication. Matching
        uses stable task fields so reprocessing the same email does not create
        duplicate Google Tasks when a local task already exists.
        """
        query = self.db.query(Task).filter_by(
            user_id=user_id,
            title=task_candidate.title,
            deadline=task_candidate.deadline,
        )

        candidate = query.first()
        if candidate is not None:
            return candidate

        return (
            self.db.query(Task)
            .filter_by(
                user_id=user_id,
                title=task_candidate.title,
                description=task_candidate.description,
            )
            .first()
        )

    def _upsert_local_task_from_candidate(self, user_id: int, task_candidate: TaskCandidate) -> Task:
        """Create or refresh a local task row before remote synchronization."""
        existing_task = self._find_matching_local_task(user_id=user_id, task_candidate=task_candidate)
        if existing_task is None:
            existing_task = Task(
                user_id=user_id,
                title=task_candidate.title,
                description=task_candidate.description,
                deadline=task_candidate.deadline,
                priority=task_candidate.priority,
                completed=False,
                sync_status="pending",
            )
            self.db.add(existing_task)
        else:
            self._apply_candidate_to_local_task(existing_task, task_candidate)
            existing_task.sync_status = "pending"

        self.db.commit()
        self.db.refresh(existing_task)
        return existing_task

    @staticmethod
    def _apply_candidate_to_local_task(local_task: Task, task_candidate: TaskCandidate) -> None:
        """Update local task fields from a TaskCandidate."""
        local_task.title = task_candidate.title
        local_task.description = task_candidate.description
        local_task.deadline = task_candidate.deadline
        local_task.priority = task_candidate.priority

    def _mark_sync_success(
        self,
        local_task: Task,
        google_task_id: Optional[str],
        sync_status: str = "synced",
    ) -> TaskSyncResult:
        """Persist successful synchronization metadata and return a typed result."""
        synced_at = datetime.utcnow()
        if google_task_id is not None:
            local_task.google_task_id = google_task_id
        local_task.sync_status = sync_status
        local_task.last_synced_at = synced_at
        self.db.commit()
        self.db.refresh(local_task)

        logger.info(
            "Google Task synchronization succeeded.",
            extra={
                "local_task_id": local_task.id,
                "google_task_id": local_task.google_task_id,
                "sync_status": sync_status,
            },
        )
        return TaskSyncResult(
            success=True,
            google_task_id=local_task.google_task_id,
            sync_status=sync_status,
            error_message=None,
            synced_at=synced_at,
            local_task_id=local_task.id,
        )

    def _mark_sync_failure(self, local_task: Task, error_message: str) -> TaskSyncResult:
        """Persist failed synchronization metadata and return a typed result."""
        local_task.sync_status = "failed"
        self.db.commit()
        self.db.refresh(local_task)

        logger.error(
            "Google Task synchronization failed.",
            extra={"local_task_id": local_task.id, "google_task_id": local_task.google_task_id},
        )
        return TaskSyncResult(
            success=False,
            google_task_id=local_task.google_task_id,
            sync_status="failed",
            error_message=error_message,
            synced_at=local_task.last_synced_at,
            local_task_id=local_task.id,
        )

    def _execute_with_retry(
        self,
        operation: Callable[[], Any],
        operation_name: str,
        user_id: int,
    ) -> Any:
        """Run a Google Tasks API operation with one retry for transient failures."""
        last_exception: Optional[Exception] = None

        for attempt in range(2):
            try:
                return operation()
            except Exception as exc:  # noqa: BLE001 - normalized into typed service behavior
                last_exception = exc
                if attempt == 0 and self._should_retry(exc):
                    logger.warning(
                        "Retrying Google Tasks API operation after transient failure.",
                        extra={"user_id": user_id, "operation": operation_name, "attempt": attempt + 1},
                        exc_info=True,
                    )
                    continue
                raise

        raise GoogleTasksServiceError(f"Failed to {operation_name} Google Task.") from last_exception

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """Return True for retryable transport and rate-limit failures."""
        if isinstance(exc, (TimeoutError, ConnectionError)):
            return True

        if isinstance(exc, HttpError):
            status = getattr(getattr(exc, "resp", None), "status", None)
            return status in {429, 500, 502, 503, 504}

        status_code = getattr(exc, "status_code", None)
        return status_code in {429, 500, 502, 503, 504}

    @staticmethod
    def _format_error_message(action: str, exc: Exception) -> str:
        """Format a concise error message for failed sync operations."""
        return f"Failed to {action} Google Task: {exc}"
