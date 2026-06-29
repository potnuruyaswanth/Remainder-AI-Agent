from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Sequence

from app.agent.email_task_agent import EmailTaskAgent
from app.schemas.google_tasks import TaskSyncResult
from app.schemas.task_candidate import TaskCandidate
from app.utils.gmail_parser import ParsedEmail


def make_email(message_id: str, subject: str, body: str = "Body") -> ParsedEmail:
    return ParsedEmail(
        gmail_message_id=message_id,
        thread_id=f"thread-{message_id}",
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject=subject,
        date="Mon, 29 Jun 2026 09:00:00 +0000",
        labels=["INBOX", "UNREAD"],
        body=body,
        snippet=subject,
    )


def make_candidate(title: str, category: str = "Assignment") -> TaskCandidate:
    return TaskCandidate(
        title=title,
        description="Action required",
        category=category,
        priority="High",
        deadline=None,
        confidence_score=0.9,
        important=True,
    )


def make_sync_result(
    *,
    success: bool,
    google_task_id: str | None,
    sync_status: str,
    local_task_id: int | None = 1,
    error_message: str | None = None,
) -> TaskSyncResult:
    return TaskSyncResult(
        success=success,
        google_task_id=google_task_id,
        sync_status=sync_status,
        error_message=error_message,
        synced_at=datetime.utcnow(),
        local_task_id=local_task_id,
    )


@dataclass
class StubGmailService:
    emails: List[ParsedEmail] = field(default_factory=list)
    observe_failures: List[Exception] = field(default_factory=list)
    verify_failures: dict[str, Exception] = field(default_factory=dict)
    observed_calls: int = 0
    marked_processed: List[str] = field(default_factory=list)

    def list_new_emails(self, user_id: int, max_results: int = 10):
        self.observed_calls += 1
        if self.observe_failures:
            raise self.observe_failures.pop(0)
        return self.emails[:max_results]

    def mark_email_processed(self, user_id: int, email: ParsedEmail):
        if email.gmail_message_id in self.verify_failures:
            raise self.verify_failures[email.gmail_message_id]
        self.marked_processed.append(email.gmail_message_id)
        return {"gmail_id": email.gmail_message_id}


@dataclass
class StubGeminiService:
    responses: dict[str, Sequence[TaskCandidate] | Exception]
    received_email_ids: List[str] = field(default_factory=list)

    def extract_tasks(self, email: ParsedEmail):
        self.received_email_ids.append(email.gmail_message_id)
        response = self.responses[email.gmail_message_id]
        if isinstance(response, Exception):
            raise response
        return list(response)


@dataclass
class StubGoogleTasksService:
    responses: dict[str, Sequence[TaskSyncResult] | Exception]
    candidate_calls: List[List[str]] = field(default_factory=list)

    def sync_tasks(self, user_id: int, task_candidates: Sequence[TaskCandidate]):
        titles = [candidate.title for candidate in task_candidates]
        self.candidate_calls.append(titles)
        key = "|".join(titles)
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return list(response)


def build_agent(
    gmail_service: StubGmailService,
    gemini_service: StubGeminiService,
    google_tasks_service: StubGoogleTasksService,
) -> EmailTaskAgent:
    return EmailTaskAgent(
        gmail_service=gmail_service,
        gemini_service=gemini_service,
        google_tasks_service=google_tasks_service,
        user_id=7,
        max_emails_per_run=10,
    )


def test_run_with_no_new_emails():
    agent = build_agent(
        gmail_service=StubGmailService(emails=[]),
        gemini_service=StubGeminiService(responses={}),
        google_tasks_service=StubGoogleTasksService(responses={}),
    )

    result = agent.run()

    assert result.new_emails == 0
    assert result.emails_processed == 0
    assert result.execution_status == "success"
    assert result.total_failures == 0


def test_run_with_one_email_success():
    email = make_email("msg-1", "Assignment")
    candidate = make_candidate("Submit Assignment")
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email]),
        gemini_service=StubGeminiService(responses={"msg-1": [candidate]}),
        google_tasks_service=StubGoogleTasksService(
            responses={
                "Submit Assignment": [
                    make_sync_result(success=True, google_task_id="gtask-1", sync_status="synced")
                ]
            }
        ),
    )

    result = agent.run()

    assert result.new_emails == 1
    assert result.emails_processed == 1
    assert result.execution_status == "success"
    assert result.total_failures == 0


def test_run_with_multiple_emails_isolates_failures():
    email_a = make_email("msg-a", "Quiz")
    email_b = make_email("msg-b", "Interview")
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email_a, email_b]),
        gemini_service=StubGeminiService(
            responses={
                "msg-a": RuntimeError("Gemini failed"),
                "msg-b": [make_candidate("Attend Interview", category="Interview")],
            }
        ),
        google_tasks_service=StubGoogleTasksService(
            responses={
                "Attend Interview": [
                    make_sync_result(success=True, google_task_id="gtask-2", sync_status="synced")
                ]
            }
        ),
    )

    result = agent.run()

    assert result.emails_processed == 1
    assert result.emails_skipped == 1
    assert result.execution_status == "partial_success"
    assert len(result.failures) == 1
    assert result.failures[0].gmail_message_id == "msg-a"


def test_run_with_multiple_task_candidates():
    email = make_email("msg-2", "Project and Meeting")
    candidates = [
        make_candidate("Submit Project", category="Project Deadline"),
        make_candidate("Attend Project Meeting", category="Meeting"),
    ]
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email]),
        gemini_service=StubGeminiService(responses={"msg-2": candidates}),
        google_tasks_service=StubGoogleTasksService(
            responses={
                "Submit Project|Attend Project Meeting": [
                    make_sync_result(success=True, google_task_id="gtask-3", sync_status="synced", local_task_id=1),
                    make_sync_result(success=True, google_task_id="gtask-4", sync_status="synced", local_task_id=2),
                ]
            }
        ),
    )

    result = agent.run()

    assert result.emails_processed == 1
    assert result.tasks_created == 2
    assert result.tasks_failed == 0


def test_run_with_google_tasks_failure():
    email = make_email("msg-3", "Meeting")
    candidate = make_candidate("Attend Meeting", category="Meeting")
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email]),
        gemini_service=StubGeminiService(responses={"msg-3": [candidate]}),
        google_tasks_service=StubGoogleTasksService(
            responses={"Attend Meeting": RuntimeError("Google Tasks failed")}
        ),
    )

    result = agent.run()

    assert result.emails_processed == 0
    assert result.emails_skipped == 1
    assert result.execution_status == "failed"
    assert result.failures[0].stage == "act"


def test_run_with_partial_task_sync_success():
    email = make_email("msg-4", "Assessment and Interview")
    candidates = [
        make_candidate("Complete Assessment", category="Job Assessment"),
        make_candidate("Attend Interview", category="Interview"),
    ]
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email]),
        gemini_service=StubGeminiService(responses={"msg-4": candidates}),
        google_tasks_service=StubGoogleTasksService(
            responses={
                "Complete Assessment|Attend Interview": [
                    make_sync_result(success=True, google_task_id="gtask-5", sync_status="synced", local_task_id=1),
                    make_sync_result(
                        success=False,
                        google_task_id=None,
                        sync_status="failed",
                        local_task_id=2,
                        error_message="Task sync failed",
                    ),
                ]
            }
        ),
    )

    result = agent.run()

    assert result.emails_processed == 0
    assert result.emails_skipped == 1
    assert result.tasks_failed == 1
    assert result.execution_status == "partial_success"


def test_run_with_verify_failure():
    email = make_email("msg-5", "Event")
    candidate = make_candidate("Attend Event", category="Event")
    gmail_service = StubGmailService(
        emails=[email],
        verify_failures={"msg-5": RuntimeError("DB failure")},
    )
    agent = build_agent(
        gmail_service=gmail_service,
        gemini_service=StubGeminiService(responses={"msg-5": [candidate]}),
        google_tasks_service=StubGoogleTasksService(
            responses={
                "Attend Event": [
                    make_sync_result(success=True, google_task_id="gtask-6", sync_status="synced")
                ]
            }
        ),
    )

    result = agent.run()

    assert result.emails_processed == 0
    assert result.failures[0].stage == "verify"
    assert gmail_service.marked_processed == []


def test_observe_retry_logic():
    email = make_email("msg-6", "Retry Observe")
    agent = build_agent(
        gmail_service=StubGmailService(
            emails=[email],
            observe_failures=[RuntimeError("Temporary Gmail failure")],
        ),
        gemini_service=StubGeminiService(responses={"msg-6": []}),
        google_tasks_service=StubGoogleTasksService(responses={}),
    )

    result = agent.run()

    assert result.observe_retry_count == 1
    assert result.new_emails == 1


def test_execution_summary_contains_expected_metrics():
    email = make_email("msg-7", "No Tasks")
    agent = build_agent(
        gmail_service=StubGmailService(emails=[email]),
        gemini_service=StubGeminiService(responses={"msg-7": []}),
        google_tasks_service=StubGoogleTasksService(responses={}),
    )

    result = agent.run()

    assert result.execution_id
    assert result.started_at <= result.finished_at
    assert result.execution_time_ms >= 0
    assert result.emails_checked == 1
    assert result.emails_skipped == 1


def test_dependency_injection_uses_provided_services():
    email = make_email("msg-8", "DI Test")
    gmail_service = StubGmailService(emails=[email])
    gemini_service = StubGeminiService(responses={"msg-8": []})
    google_tasks_service = StubGoogleTasksService(responses={})
    agent = build_agent(gmail_service, gemini_service, google_tasks_service)

    agent.run()

    assert gmail_service.observed_calls == 1
    assert gemini_service.received_email_ids == ["msg-8"]
    assert google_tasks_service.candidate_calls == []
