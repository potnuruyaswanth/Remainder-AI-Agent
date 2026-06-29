from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import (
    get_agent,
    get_dashboard_service,
    get_gmail_service,
    get_scheduler_state,
    get_settings_service,
    get_task_service,
)
from app.exceptions import register_exception_handlers
from app.models.user import User
from app.routers.agent import router as agent_router
from app.routers.auth import get_current_user, router as auth_router
from app.routers.dashboard import router as dashboard_router
from app.routers.gmail import router as gmail_router
from app.routers.settings import router as settings_router
from app.routers.tasks import router as tasks_router
from app.schemas.agent_execution import AgentExecutionResult
from app.schemas.dashboard import DashboardStatsResponse, SyncStatusResponse
from app.schemas.gmail_api import GmailStatusResponse
from app.schemas.settings_api import SettingsResponse
from app.schemas.task_api import TaskCreateRequest, TaskResponse, TaskUpdateRequest
from app.utils.gmail_parser import ParsedEmail


class StubTaskService:
    def __init__(self) -> None:
        self.tasks = [
            TaskResponse(
                id=1,
                user_id=1,
                title="Existing Task",
                description="Task description",
                deadline=None,
                priority="Medium",
                completed=False,
                google_task_id=None,
                sync_status="pending",
                last_synced_at=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        ]

    def list_tasks(self, user_id: int):
        return self.tasks

    def get_task(self, user_id: int, task_id: int):
        return next((task for task in self.tasks if task.id == task_id), None)

    def create_task(self, user_id: int, payload: TaskCreateRequest):
        task = TaskResponse(
            id=2,
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            deadline=payload.deadline,
            priority=payload.priority,
            completed=payload.completed,
            google_task_id=None,
            sync_status="pending",
            last_synced_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.tasks.append(task)
        return task

    def update_task(self, task: TaskResponse, payload: TaskUpdateRequest):
        data = payload.model_dump(exclude_unset=True)
        updated = task.model_copy(update=data | {"updated_at": datetime.utcnow()})
        self.tasks = [updated if item.id == task.id else item for item in self.tasks]
        return updated

    def delete_task(self, task: TaskResponse):
        self.tasks = [item for item in self.tasks if item.id != task.id]


class StubDashboardService:
    def get_dashboard(self, user_id: int) -> DashboardStatsResponse:
        task = TaskResponse(
            id=1,
            user_id=user_id,
            title="Today Task",
            description="Dashboard task",
            deadline=None,
            priority="High",
            completed=False,
            google_task_id=None,
            sync_status="synced",
            last_synced_at=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        return DashboardStatsResponse(
            todays_tasks=[task],
            upcoming_tasks=[],
            completed_tasks=[],
            recent_emails=[],
            sync_status=SyncStatusResponse(pending_tasks=0, failed_tasks=0, last_synced_at=None),
            total_tasks=1,
            completed_count=0,
            pending_count=1,
        )

    def processed_email_count(self, user_id: int) -> int:
        return 3


class StubGmailService:
    def list_new_emails(self, user_id: int, max_results: int = 10):
        return [
            ParsedEmail(
                gmail_message_id="msg-1",
                thread_id="thread-1",
                sender="sender@example.com",
                recipient="recipient@example.com",
                subject="Inbox Task",
                date="Mon, 29 Jun 2026 09:00:00 +0000",
                labels=["INBOX"],
                body="Body",
                snippet="Snippet",
            )
        ]


class StubSettingsService:
    def __init__(self) -> None:
        self.response = SettingsResponse(
            frontend_url="http://localhost:5173",
            tasklist_id="@default",
            sync_interval_min=5,
            scheduler_enabled=False,
            scheduler_interval_minutes=5,
            scheduler_max_concurrent_runs=1,
            scheduler_retry_delay_seconds=5,
            scheduler_user_id=None,
        )

    def get_settings(self) -> SettingsResponse:
        return self.response

    def update_settings(self, payload):
        updated = self.response.model_copy(update=payload.model_dump(exclude_unset=True))
        self.response = updated
        return self.response


class StubAgent:
    def run(self) -> AgentExecutionResult:
        now = datetime.utcnow()
        return AgentExecutionResult(
            started_at=now,
            finished_at=now,
            emails_checked=1,
            new_emails=1,
            emails_processed=1,
            emails_skipped=0,
            tasks_created=1,
            tasks_updated=0,
            tasks_failed=0,
            total_failures=0,
            execution_status="success",
            execution_time_ms=10,
        )


@pytest.fixture(name="api_client")
def fixture_api_client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(tasks_router, prefix="/api/tasks")
    app.include_router(dashboard_router, prefix="/api/dashboard")
    app.include_router(gmail_router, prefix="/api/gmail")
    app.include_router(settings_router, prefix="/api/settings")
    app.include_router(agent_router, prefix="/api/agent")
    register_exception_handlers(app)

    current_user = User(id=1, email="api@example.com", credentials="secret")

    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_task_service] = lambda: StubTaskService()
    app.dependency_overrides[get_dashboard_service] = lambda: StubDashboardService()
    app.dependency_overrides[get_gmail_service] = lambda: StubGmailService()
    app.dependency_overrides[get_settings_service] = lambda: StubSettingsService()
    app.dependency_overrides[get_agent] = lambda: StubAgent()
    app.dependency_overrides[get_scheduler_state] = lambda: None

    return TestClient(app)


def test_authentication_me_endpoint(api_client: TestClient):
    response = api_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "api@example.com"


def test_task_crud_endpoints(api_client: TestClient):
    list_response = api_client.get("/api/tasks")
    assert list_response.status_code == 200
    assert len(list_response.json()["tasks"]) == 1

    create_response = api_client.post(
        "/api/tasks",
        json={"title": "New Task", "description": "Create me", "priority": "High", "completed": False},
    )
    assert create_response.status_code == 201
    assert create_response.json()["title"] == "New Task"

    update_response = api_client.put("/api/tasks/1", json={"completed": True})
    assert update_response.status_code == 200
    assert update_response.json()["completed"] is True

    delete_response = api_client.delete("/api/tasks/1")
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"


def test_dashboard_endpoint(api_client: TestClient):
    response = api_client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["total_tasks"] == 1


def test_agent_run_endpoint(api_client: TestClient):
    response = api_client.post("/api/agent/run")
    assert response.status_code == 200
    assert response.json()["execution"]["execution_status"] == "success"


def test_scheduler_status_endpoint(api_client: TestClient):
    response = api_client.get("/api/agent/status")
    assert response.status_code == 200
    assert response.json()["scheduler_enabled"] is False


def test_settings_endpoints(api_client: TestClient):
    get_response = api_client.get("/api/settings")
    assert get_response.status_code == 200
    assert get_response.json()["scheduler_enabled"] is False

    update_response = api_client.put("/api/settings", json={"scheduler_enabled": True})
    assert update_response.status_code == 200
    assert update_response.json()["scheduler_enabled"] is True


def test_gmail_endpoints(api_client: TestClient):
    sync_response = api_client.post("/api/gmail/sync")
    assert sync_response.status_code == 200
    assert sync_response.json()["new_emails"] == 1

    test_response = api_client.post("/api/gmail/test")
    assert test_response.status_code == 200
    assert test_response.json()["status"] == "ok"

    status_response = api_client.get("/api/gmail/status")
    assert status_response.status_code == 200
    assert status_response.json()["processed_email_count"] == 3


def test_validation_error_response(api_client: TestClient):
    response = api_client.post("/api/tasks", json={"description": "Missing title"})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_authentication_error_response():
    app = FastAPI()
    app.include_router(tasks_router, prefix="/api/tasks")
    register_exception_handlers(app)

    app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(Exception("Not authenticated"))
    app.dependency_overrides[get_task_service] = lambda: StubTaskService()

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/tasks")
    assert response.status_code == 500
