import json
from datetime import datetime
from typing import Any, List

import pytest

from app.prompts.task_extraction_prompt import TaskExtractionPromptBuilder
from app.schemas.task_candidate import TaskCandidate
from app.services.gemini_service import GeminiService
from app.utils.gmail_parser import ParsedEmail


class FakeGenerateContentResponse:
    """Simple fake response object compatible with GeminiService parsing."""

    def __init__(self, *, text: str | None = None, parsed: Any = None) -> None:
        self.text = text
        self.parsed = parsed


class FakeModels:
    """Fake Gemini models endpoint that replays scripted responses."""

    def __init__(self, scripted_responses: List[Any]) -> None:
        self.scripted_responses = scripted_responses
        self.calls: List[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        next_item = self.scripted_responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


class FakeClient:
    """Fake Gemini client exposing a models interface."""

    def __init__(self, scripted_responses: List[Any]) -> None:
        self.models = FakeModels(scripted_responses)


def build_client_factory(scripted_responses: List[Any], clients: List[FakeClient]):
    """Create a client factory that tracks the fake clients it produces."""

    def factory() -> FakeClient:
        client = FakeClient(scripted_responses)
        clients.append(client)
        return client

    return factory


def build_email(
    subject: str,
    body: str,
    snippet: str = "",
    gmail_message_id: str = "msg-1",
) -> ParsedEmail:
    return ParsedEmail(
        gmail_message_id=gmail_message_id,
        thread_id=f"thread-{gmail_message_id}",
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject=subject,
        date="Fri, 27 Jun 2026 10:00:00 +0000",
        labels=["INBOX"],
        body=body,
        snippet=snippet,
    )


def extraction_payload(task: dict[str, Any]) -> str:
    return json.dumps({"tasks": [task]})


def empty_payload() -> str:
    return json.dumps({"tasks": []})


def make_task(
    *,
    title: str,
    category: str,
    priority: str,
    deadline: str | None,
    description: str = "Actionable task",
    confidence_score: float = 0.9,
    important: bool = True,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "category": category,
        "priority": priority,
        "deadline": deadline,
        "confidence_score": confidence_score,
        "important": important,
    }


def build_service(scripted_responses: List[Any], clients: List[FakeClient] | None = None) -> GeminiService:
    tracked_clients = clients if clients is not None else []
    return GeminiService(
        prompt_builder=TaskExtractionPromptBuilder(),
        client_factory=build_client_factory(scripted_responses, tracked_clients),
    )


def assert_single_task(result: List[TaskCandidate], expected_category: str, expected_title: str) -> None:
    assert len(result) == 1
    assert result[0].category == expected_category
    assert result[0].title == expected_title


def test_extracts_assignment_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Submit Linear Algebra Assignment",
            category="Assignment",
            priority="High",
            deadline="2026-07-01T23:59:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Assignment Due", "Submit by tomorrow."))
    assert_single_task(tasks, "Assignment", "Submit Linear Algebra Assignment")


def test_extracts_quiz_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Prepare for Weekly Quiz",
            category="Quiz",
            priority="Medium",
            deadline="2026-07-03T09:00:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Quiz Announcement", "Quiz on Friday at 9 AM."))
    assert_single_task(tasks, "Quiz", "Prepare for Weekly Quiz")


def test_extracts_exam_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Attend Midterm Exam",
            category="Exam",
            priority="High",
            deadline="2026-07-10T14:00:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Midterm Exam", "Exam starts at 2 PM on July 10."))
    assert_single_task(tasks, "Exam", "Attend Midterm Exam")


def test_extracts_meeting_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Attend Product Review Meeting",
            category="Meeting",
            priority="Medium",
            deadline="2026-07-04T16:00:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Meeting Invite", "Join the review meeting at 4 PM."))
    assert_single_task(tasks, "Meeting", "Attend Product Review Meeting")


def test_extracts_interview_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Attend Backend Engineer Interview",
            category="Interview",
            priority="High",
            deadline="2026-07-05T11:00:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Interview Schedule", "Interview at 11 AM this Saturday."))
    assert_single_task(tasks, "Interview", "Attend Backend Engineer Interview")


def test_extracts_internship_email():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Complete Internship Onboarding",
            category="Internship",
            priority="Medium",
            deadline="2026-07-06T10:00:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Internship Offer", "Please complete onboarding by Monday."))
    assert_single_task(tasks, "Internship", "Complete Internship Onboarding")


def test_extracts_bill_reminder():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Pay Electricity Bill",
            category="Bill Payment",
            priority="High",
            deadline="2026-07-08T23:59:00Z",
        )))]
    )
    tasks = service.extract_tasks(build_email("Bill Due", "Your electricity bill is due on July 8."))
    assert_single_task(tasks, "Bill Payment", "Pay Electricity Bill")


def test_promotional_email_returns_no_tasks():
    service = build_service([FakeGenerateContentResponse(text=empty_payload())])
    tasks = service.extract_tasks(build_email("Big Sale", "Buy now and save 30 percent."))
    assert tasks == []


def test_invalid_gemini_json_retries_once_then_succeeds():
    clients: List[FakeClient] = []
    service = build_service(
        [
            FakeGenerateContentResponse(text="{not valid json"),
            FakeGenerateContentResponse(text=extraction_payload(make_task(
                title="Attend Career Fair",
                category="Event",
                priority="Medium",
                deadline="2026-07-12T09:00:00Z",
            ))),
        ],
        clients=clients,
    )

    tasks = service.extract_tasks(build_email("Career Fair", "Attend on July 12 at 9 AM."))

    assert_single_task(tasks, "Event", "Attend Career Fair")
    total_calls = sum(len(client.models.calls) for client in clients)
    assert total_calls == 2


def test_gemini_timeout_returns_empty_list():
    service = build_service([TimeoutError("Gemini request timed out")])
    tasks = service.extract_tasks(build_email("Reminder", "Body"))
    assert tasks == []


def test_retry_logic_returns_empty_after_second_invalid_response():
    clients: List[FakeClient] = []
    service = build_service(
        [
            FakeGenerateContentResponse(text="not json"),
            FakeGenerateContentResponse(text='{"tasks": [{"title": ""}]}'),
        ],
        clients=clients,
    )

    tasks = service.extract_tasks(build_email("Bad Output", "Body"))

    assert tasks == []
    total_calls = sum(len(client.models.calls) for client in clients)
    assert total_calls == 2


def test_empty_email_body_with_no_other_content_skips_model_call():
    clients: List[FakeClient] = []
    service = build_service([], clients=clients)
    empty_email = build_email(subject="", body="", snippet="", gmail_message_id="msg-empty")

    tasks = service.extract_tasks(empty_email)

    assert tasks == []
    assert clients == []


def test_html_email_is_processed_as_normal_text():
    service = build_service(
        [FakeGenerateContentResponse(text=extraction_payload(make_task(
            title="Attend Team Sync",
            category="Meeting",
            priority="Medium",
            deadline="2026-07-09T15:00:00Z",
        )))]
    )
    html_parsed_email = build_email(
        "Team Sync",
        "Please attend the team sync at 3 PM.",
        gmail_message_id="msg-html",
    )

    tasks = service.extract_tasks(html_parsed_email)

    assert_single_task(tasks, "Meeting", "Attend Team Sync")


def test_multiple_tasks_inside_one_email():
    payload = {
        "tasks": [
            make_task(
                title="Complete Job Assessment",
                category="Job Assessment",
                priority="High",
                deadline="2026-07-07T20:00:00Z",
            ),
            make_task(
                title="Attend Final Interview",
                category="Interview",
                priority="High",
                deadline="2026-07-08T09:30:00Z",
            ),
        ]
    }
    service = build_service([FakeGenerateContentResponse(text=json.dumps(payload))])

    tasks = service.extract_tasks(
        build_email("Application Update", "Complete the assessment and attend the interview.")
    )

    assert len(tasks) == 2
    assert tasks[0].category == "Job Assessment"
    assert tasks[1].category == "Interview"


def test_parsed_response_object_is_accepted():
    parsed_payload = {
        "tasks": [
            make_task(
                title="Submit Project Milestone",
                category="Project Deadline",
                priority="High",
                deadline="2026-07-15T23:59:00Z",
            )
        ]
    }
    service = build_service([FakeGenerateContentResponse(parsed=parsed_payload)])

    tasks = service.extract_tasks(build_email("Milestone", "Milestone due July 15."))

    assert isinstance(tasks[0].deadline, datetime)
    assert tasks[0].category == "Project Deadline"
