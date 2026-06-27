from datetime import timezone

from app.schemas.google_tasks import GoogleTaskRequest
from app.schemas.task_candidate import TaskCandidate


class TaskMapper:
    """
    Converts internal TaskCandidate objects into Google Tasks request models.

    This mapper is intentionally independent from any API client so the
    transformation logic remains reusable, testable, and isolated from
    network concerns.
    """

    def to_google_task_request(self, task_candidate: TaskCandidate) -> GoogleTaskRequest:
        """Transform a TaskCandidate into a typed Google Tasks payload."""
        notes_lines = [
            task_candidate.description.strip(),
            f"Category: {task_candidate.category}",
            f"Priority: {task_candidate.priority}",
            f"Important: {'Yes' if task_candidate.important else 'No'}",
            f"Confidence Score: {task_candidate.confidence_score:.2f}",
        ]
        notes = "\n".join(line for line in notes_lines if line)

        due = None
        if task_candidate.deadline is not None:
            deadline = task_candidate.deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            due = deadline.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        return GoogleTaskRequest(
            title=task_candidate.title,
            notes=notes,
            due=due,
            status="needsAction",
        )
