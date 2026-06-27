from datetime import datetime

from app.schemas.task_candidate import TaskCandidate
from app.services.task_mapper import TaskMapper


def test_task_mapper_builds_google_task_request():
    mapper = TaskMapper()
    task_candidate = TaskCandidate(
        title="Submit Capstone Project",
        description="Upload the final report to the portal.",
        category="Project Deadline",
        priority="High",
        deadline=datetime(2026, 7, 20, 18, 30),
        confidence_score=0.97,
        important=True,
    )

    request_model = mapper.to_google_task_request(task_candidate)

    assert request_model.title == "Submit Capstone Project"
    assert "Category: Project Deadline" in request_model.notes
    assert "Priority: High" in request_model.notes
    assert "Confidence Score: 0.97" in request_model.notes
    assert request_model.due == "2026-07-20T18:30:00Z"
    assert request_model.status == "needsAction"
