import json
from json import JSONDecodeError
from typing import Any, Callable, List, Optional

from pydantic import ValidationError

from app.config import settings
from app.prompts.task_extraction_prompt import PromptBundle, TaskExtractionPromptBuilder
from app.schemas.task_candidate import TaskCandidate, TaskExtractionResult
from app.utils.gmail_parser import ParsedEmail
from app.utils.logger import logger

try:
    from google.genai import Client, types
except ImportError:  # pragma: no cover - exercised only when optional deps are missing
    Client = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]


class GeminiService:
    """
    Service responsible for task extraction using the Gemini API.

    The service accepts normalized ParsedEmail objects and returns validated
    TaskCandidate instances. Prompt rendering and response validation are kept
    explicit so the agent can safely depend on the output shape.
    """

    def __init__(
        self,
        prompt_builder: Optional[TaskExtractionPromptBuilder] = None,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.prompt_builder = prompt_builder or TaskExtractionPromptBuilder()
        self.client_factory = client_factory or self._default_client_factory

    def extract_tasks(self, email: ParsedEmail) -> List[TaskCandidate]:
        """
        Extract actionable tasks from a parsed email.

        Returns an empty list if the email lacks meaningful content, if Gemini
        fails, or if Gemini returns invalid structured output after one retry.
        """
        if not self._has_meaningful_content(email):
            logger.info(
                "Skipping Gemini extraction because the parsed email has no meaningful content.",
                extra={"gmail_message_id": email.gmail_message_id},
            )
            return []

        prompt_bundle = self.prompt_builder.build(email)

        for attempt in range(2):
            try:
                payload = self._generate_structured_payload(prompt_bundle)
                extraction_result = TaskExtractionResult.model_validate(payload)
                logger.info(
                    "Gemini task extraction succeeded.",
                    extra={
                        "gmail_message_id": email.gmail_message_id,
                        "task_count": len(extraction_result.tasks),
                        "attempt": attempt + 1,
                    },
                )
                return extraction_result.tasks
            except (JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "Gemini returned invalid structured output.",
                    extra={
                        "gmail_message_id": email.gmail_message_id,
                        "attempt": attempt + 1,
                    },
                    exc_info=True,
                )
                if attempt == 1:
                    logger.error(
                        "Skipping email after repeated invalid Gemini output.",
                        extra={"gmail_message_id": email.gmail_message_id},
                    )
                    return []
            except Exception:
                logger.error(
                    "Gemini extraction failed due to an API or runtime error.",
                    extra={"gmail_message_id": email.gmail_message_id},
                    exc_info=True,
                )
                return []

        return []

    def _generate_structured_payload(self, prompt_bundle: PromptBundle) -> Any:
        """Call Gemini and return the raw structured payload for validation."""
        client = self.client_factory()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt_bundle.user_prompt,
            config=self._build_generation_config(prompt_bundle.system_instruction),
        )
        return self._extract_payload_from_response(response)

    def _build_generation_config(self, system_instruction: str) -> Any:
        """Create a low-temperature JSON-only configuration for Gemini."""
        if types is None:
            raise RuntimeError(
                "google-genai is not installed. Install google-genai to use Gemini."
            )

        return types.GenerateContentConfig(
            systemInstruction=system_instruction,
            temperature=0.1,
            responseMimeType="application/json",
            responseSchema=TaskExtractionResult,
        )

    def _extract_payload_from_response(self, response: Any) -> Any:
        """Normalize the Gemini SDK response into JSON-like Python data."""
        parsed_payload = getattr(response, "parsed", None)
        if parsed_payload is not None:
            if isinstance(parsed_payload, TaskExtractionResult):
                return parsed_payload.model_dump(mode="json")
            if hasattr(parsed_payload, "model_dump"):
                return parsed_payload.model_dump(mode="json")
            return parsed_payload

        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            return json.loads(response_text)

        raise JSONDecodeError("Gemini response did not contain parsable JSON.", "", 0)

    def _default_client_factory(self) -> Any:
        """Create the default Gemini API client from application settings."""
        if Client is None:
            raise RuntimeError(
                "google-genai is not installed. Install google-genai to use Gemini."
            )
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured.")
        return Client(api_key=settings.GEMINI_API_KEY)

    @staticmethod
    def _has_meaningful_content(email: ParsedEmail) -> bool:
        """Return True when the parsed email contains enough information to analyze."""
        return any(
            field.strip()
            for field in (email.subject, email.snippet, email.body)
            if isinstance(field, str)
        )
