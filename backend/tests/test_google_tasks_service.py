from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.task import Task
from app.models.user import User
from app.schemas.google_tasks import GoogleTaskRecord, TaskSyncResult
from app.schemas.task_candidate import TaskCandidate
from app.services.google_tasks_service import (
    GoogleTasksAuthenticationError,
    GoogleTasksService,
)
from app.services.task_mapper import TaskMapper


TEST_DATABASE_URL = "sqlite:///:memory:"


class FakeRequest:
    """Simple executable wrapper for fake Google API requests."""

    def __init__(self, executor):
        self.executor = executor

    def execute(self):
        return self.executor()


class FakeTasksResource:
    """Fake Google Tasks resource that stores task state in memory."""

    def __init__(self) -> None:
        self.store: Dict[str, Dict[str, Any]] = {}
        self.insert_calls: List[Dict[str, Any]] = []
        self.update_calls: List[Dict[str, Any]] = []
        self.delete_calls: List[Dict[str, Any]] = []
        self.get_calls: List[Dict[str, Any]] = []
        self.failures: Dict[str, List[Exception]] = {
            "insert": [],
            "update": [],
            "delete": [],
            "get": [],
        }
        self.sequence = 0

    def insert(self, **kwargs: Any) -> FakeRequest:
        self.insert_calls.append(kwargs)

        def executor():
            self._maybe_raise("insert")
            self.sequence += 1
            task_id = f"google-task-{self.sequence}"
            payload = {
                "id": task_id,
                "title": kwargs["body"].get("title", ""),
                "notes": kwargs["body"].get("notes", ""),
                "due": kwargs["body"].get("due"),
                "status": kwargs["body"].get("status", "needsAction"),
                "updated": "2026-06-27T10:00:00.000Z",
                "webViewLink": f"https://tasks.google.com/task/{task_id}",
                "deleted": False,
            }
            self.store[task_id] = payload
            return payload

        return FakeRequest(executor)

    def update(self, **kwargs: Any) -> FakeRequest:
        self.update_calls.append(kwargs)

        def executor():
            self._maybe_raise("update")
            task_id = kwargs["task"]
            payload = self.store.get(task_id, {"id": task_id})
            payload.update(
                {
                    "id": task_id,
                    "title": kwargs["body"].get("title", payload.get("title", "")),
                    "notes": kwargs["body"].get("notes", payload.get("notes", "")),
                    "due": kwargs["body"].get("due", payload.get("due")),
                    "status": kwargs["body"].get("status", payload.get("status", "needsAction")),
                    "updated": "2026-06-27T11:00:00.000Z",
                    "deleted": False,
                }
            )
            self.store[task_id] = payload
            return payload

        return FakeRequest(executor)

    def delete(self, **kwargs: Any) -> FakeRequest:
        self.delete_calls.append(kwargs)

        def executor():
            self._maybe_raise("delete")
            task_id = kwargs["task"]
            if task_id in self.store:
                self.store[task_id]["deleted"] = True
            return None

        return FakeRequest(executor)

    def get(self, **kwargs: Any) -> FakeRequest:
        self.get_calls.append(kwargs)

        def executor():
            self._maybe_raise("get")
            return self.store[kwargs["task"]]

        return FakeRequest(executor)

    def _maybe_raise(self, operation_name: str) -> None:
        failures = self.failures[operation_name]
        if failures:
            raise failures.pop(0)


class FakeGoogleTasksClient:
    """Fake top-level client that exposes a tasks resource."""

    def __init__(self, tasks_resource: FakeTasksResource) -> None:
        self._tasks_resource = tasks_resource

    def tasks(self) -> FakeTasksResource:
        return self._tasks_resource


class StubAuthService:
    """Auth stub that records how often credentials are requested."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.calls: List[int] = []

    def get_user_credentials(self, user_id: int) -> object:
        self.calls.append(user_id)
        return {"access_token": "fresh-token"}


class MissingCredentialsAuthService:
    """Auth stub that simulates missing or invalid credentials."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_user_credentials(self, user_id: int) -> None:
        return None


@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_local()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def create_user(db_session: Session) -> User:
    user = User(email="sync@example.com", credentials="encrypted")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_candidate(
    title: str,
    *,
    description: str = "Action required",
    category: str = "Assignment",
    priority: str = "High",
    deadline: Optional[datetime] = None,
    confidence_score: float = 0.91,
    important: bool = True,
) -> TaskCandidate:
    return TaskCandidate(
        title=title,
        description=description,
        category=category,
        priority=priority,
        deadline=deadline,
        confidence_score=confidence_score,
        important=important,
    )


def build_service(
    db_session: Session,
    tasks_resource: FakeTasksResource,
    auth_service_factory=StubAuthService,
    auth_instances: Optional[List[StubAuthService]] = None,
) -> GoogleTasksService:
    tracked_instances = auth_instances if auth_instances is not None else []

    def factory(db: Session):
        instance = auth_service_factory(db)
        tracked_instances.append(instance)
        return instance

    def client_builder(*args: Any, **kwargs: Any) -> FakeGoogleTasksClient:
        return FakeGoogleTasksClient(tasks_resource)

    return GoogleTasksService(
        db=db_session,
        auth_service_factory=factory,
        tasks_client_builder=client_builder,
        task_mapper=TaskMapper(),
    )


def test_create_google_task(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)

    result = service.create_task(
        user_id=user.id,
        task_candidate=make_candidate("Submit AI Assignment", deadline=datetime(2026, 7, 1, 23, 59)),
    )

    assert isinstance(result, TaskSyncResult)
    assert result.success is True
    assert result.google_task_id == "google-task-1"
    saved_task = db_session.query(Task).filter_by(user_id=user.id, title="Submit AI Assignment").first()
    assert saved_task is not None
    assert saved_task.google_task_id == "google-task-1"
    assert saved_task.sync_status == "synced"
    assert saved_task.last_synced_at is not None


def test_update_google_task(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    create_result = service.create_task(user.id, make_candidate("Attend Interview", category="Interview"))
    local_task = db_session.query(Task).filter_by(id=create_result.local_task_id).first()

    result = service.update_task(
        user_id=user.id,
        local_task=local_task,
        task_candidate=make_candidate(
            "Attend Final Interview",
            category="Interview",
            priority="High",
            deadline=datetime(2026, 7, 3, 11, 0),
        ),
    )

    assert result.success is True
    assert result.google_task_id == create_result.google_task_id
    assert tasks_resource.update_calls
    assert local_task.title == "Attend Final Interview"


def test_delete_google_task(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    create_result = service.create_task(user.id, make_candidate("Pay Rent", category="Bill Payment"))
    local_task = db_session.query(Task).filter_by(id=create_result.local_task_id).first()

    result = service.delete_task(user.id, local_task)

    assert result.success is True
    assert result.sync_status == "deleted"
    assert tasks_resource.delete_calls
    assert local_task.sync_status == "deleted"


def test_sync_tasks_handles_multiple_task_candidates(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)

    results = service.sync_tasks(
        user.id,
        [
            make_candidate("Complete Quiz", category="Quiz"),
            make_candidate("Attend Team Meeting", category="Meeting"),
        ],
    )

    assert len(results) == 2
    assert all(result.success for result in results)
    assert db_session.query(Task).filter_by(user_id=user.id).count() == 2


def test_duplicate_prevention_updates_existing_task(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    candidate = make_candidate("Complete Job Assessment", category="Job Assessment")

    first_result = service.sync_tasks(user.id, [candidate])
    second_result = service.sync_tasks(user.id, [candidate])

    assert first_result[0].success is True
    assert second_result[0].success is True
    assert len(tasks_resource.insert_calls) == 1
    assert len(tasks_resource.update_calls) == 1
    assert db_session.query(Task).filter_by(user_id=user.id, title="Complete Job Assessment").count() == 1


def test_expired_token_refresh_path_requests_credentials_for_each_operation(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    auth_instances: List[StubAuthService] = []
    service = build_service(db_session, tasks_resource, auth_instances=auth_instances)

    service.sync_tasks(
        user.id,
        [
            make_candidate("Prepare Exam", category="Exam"),
            make_candidate("Join Orientation Event", category="Event"),
        ],
    )

    assert len(auth_instances) == 2
    assert all(instance.calls == [user.id] for instance in auth_instances)


def test_api_failure_does_not_stop_remaining_tasks(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    tasks_resource.failures["insert"] = [RuntimeError("API unavailable")]
    service = build_service(db_session, tasks_resource)

    results = service.sync_tasks(
        user.id,
        [
            make_candidate("Broken First Task", category="Assignment"),
            make_candidate("Attend Seminar", category="Event"),
        ],
    )

    assert len(results) == 2
    assert results[0].success is False
    assert results[1].success is True


def test_invalid_credentials_returns_failed_sync_result(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(
        db_session,
        tasks_resource,
        auth_service_factory=MissingCredentialsAuthService,
    )

    result = service.create_task(user.id, make_candidate("Submit Report"))

    assert result.success is False
    assert result.sync_status == "failed"
    assert "No valid Google credentials" in result.error_message


def test_network_timeout_retries_and_then_fails(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    tasks_resource.failures["insert"] = [TimeoutError("timeout"), TimeoutError("timeout")]
    service = build_service(db_session, tasks_resource)

    result = service.create_task(user.id, make_candidate("Attend Mock Interview", category="Interview"))

    assert result.success is False
    assert len(tasks_resource.insert_calls) == 2


def test_retrieve_task_returns_typed_record(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    create_result = service.create_task(user.id, make_candidate("Pay Internet Bill", category="Bill Payment"))

    record = service.retrieve_task(user.id, create_result.google_task_id)

    assert isinstance(record, GoogleTaskRecord)
    assert record.google_task_id == create_result.google_task_id
    assert record.title == "Pay Internet Bill"


def test_synchronization_logic_updates_existing_google_task_id_locally(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    create_result = service.create_task(user.id, make_candidate("Attend Internship Orientation", category="Internship"))
    local_task = db_session.query(Task).filter_by(id=create_result.local_task_id).first()

    service.update_task(
        user.id,
        local_task,
        make_candidate(
            "Attend Internship Orientation",
            category="Internship",
            priority="Medium",
            deadline=datetime(2026, 7, 5, 9, 0),
        ),
    )

    refreshed_task = db_session.query(Task).filter_by(id=local_task.id).first()
    assert refreshed_task.google_task_id == create_result.google_task_id
    assert refreshed_task.sync_status == "synced"
    assert refreshed_task.last_synced_at is not None


def test_invalid_task_candidate_is_reported_safely(db_session: Session):
    user = create_user(db_session)
    tasks_resource = FakeTasksResource()
    service = build_service(db_session, tasks_resource)
    invalid_candidate = TaskCandidate.model_construct(
        title="",
        description="",
        category="Assignment",
        priority="High",
        deadline=None,
        confidence_score=0.5,
        important=True,
    )

    result = service.sync_tasks(user.id, [invalid_candidate])[0]

    assert result.success is False
    assert result.sync_status == "failed"
