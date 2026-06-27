from dataclasses import dataclass
from pathlib import Path

from app.utils.gmail_parser import ParsedEmail


PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(slots=True)
class PromptBundle:
    """Container for the system instruction and formatted user prompt."""

    system_instruction: str
    user_prompt: str


class TaskExtractionPromptBuilder:
    """Loads task extraction prompt templates and renders them from a ParsedEmail."""

    def __init__(
        self,
        system_template_path: Path = PROMPTS_DIR / "task_extraction_system.txt",
        user_template_path: Path = PROMPTS_DIR / "task_extraction_user.txt",
    ) -> None:
        self.system_template = system_template_path.read_text(encoding="utf-8")
        self.user_template = user_template_path.read_text(encoding="utf-8")

    def build(self, email: ParsedEmail) -> PromptBundle:
        """Render the reusable task extraction templates for a single parsed email."""
        labels = ", ".join(email.labels) if email.labels else "None"
        user_prompt = self.user_template.format(
            gmail_message_id=email.gmail_message_id,
            thread_id=email.thread_id,
            sender=email.sender or "Unknown",
            recipient=email.recipient or "Unknown",
            date=email.date or "Unknown",
            subject=email.subject or "",
            labels=labels,
            snippet=email.snippet or "",
            body=email.body or "",
        )
        return PromptBundle(
            system_instruction=self.system_template,
            user_prompt=user_prompt,
        )
