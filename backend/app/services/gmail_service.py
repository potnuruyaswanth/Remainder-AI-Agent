from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.email import ProcessedEmail
from app.services.auth_service import AuthService
from app.utils.gmail_parser import ParsedEmail, parse_gmail_message
from app.utils.logger import logger

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover - exercised only when optional deps are missing
    def build(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError(
            "Google API client dependencies are not installed. "
            "Install google-api-python-client to use Gmail features."
        )

    class HttpError(Exception):
        """Fallback Gmail API error when googleapiclient is unavailable."""


class GmailServiceError(RuntimeError):
    """Raised when Gmail API operations fail or return unusable data."""


class GmailAuthenticationError(GmailServiceError):
    """Raised when stored user credentials are missing or invalid."""


class GmailService:
    """Service layer for reading new Gmail messages and tracking processed items."""

    def __init__(
        self,
        db: Session,
        auth_service_factory: Callable[[Session], AuthService] = AuthService,
        gmail_client_builder: Callable[..., Any] = build,
        parser: Callable[[Dict[str, Any]], ParsedEmail] = parse_gmail_message,
    ) -> None:
        self.db = db
        self.auth_service_factory = auth_service_factory
        self.gmail_client_builder = gmail_client_builder
        self.parser = parser

    def list_new_emails(
        self,
        user_id: int,
        max_results: int = 10,
        label_ids: Optional[Sequence[str]] = None,
        query: str = "is:unread",
    ) -> List[ParsedEmail]:
        """
        Return parsed Gmail messages that have not yet been recorded in ProcessedEmail.

        The future EmailTaskAgent can pass these objects directly to Gemini because the
        Gmail-specific MIME and Base64 handling has already been normalized here.
        """
        message_refs = self._list_message_refs(
            user_id=user_id,
            max_results=max_results,
            label_ids=label_ids or ["INBOX", "UNREAD"],
            query=query,
        )

        new_emails: List[ParsedEmail] = []

        for message_ref in message_refs:
            gmail_message_id = str(message_ref.get("id", "")).strip()
            if not gmail_message_id:
                continue

            if self.is_email_processed(user_id=user_id, gmail_message_id=gmail_message_id):
                logger.info(
                    "Skipping previously processed Gmail message.",
                    extra={"user_id": user_id, "gmail_message_id": gmail_message_id},
                )
                continue

            raw_message = self._get_message(user_id=user_id, gmail_message_id=gmail_message_id)
            parsed_email = self.parser(raw_message)
            new_emails.append(parsed_email)

        logger.info(
            "Finished loading new Gmail messages.",
            extra={"user_id": user_id, "new_email_count": len(new_emails)},
        )
        return new_emails

    def mark_email_processed(self, user_id: int, email: ParsedEmail) -> ProcessedEmail:
        """Persist a Gmail message in the dedup table after downstream processing succeeds."""
        existing = (
            self.db.query(ProcessedEmail)
            .filter_by(user_id=user_id, gmail_id=email.gmail_message_id)
            .first()
        )
        if existing:
            return existing

        processed_email = ProcessedEmail(
            user_id=user_id,
            gmail_id=email.gmail_message_id,
            subject=email.subject,
            snippet=email.snippet,
        )
        self.db.add(processed_email)
        self.db.commit()
        self.db.refresh(processed_email)

        logger.info(
            "Recorded Gmail message as processed.",
            extra={"user_id": user_id, "gmail_message_id": email.gmail_message_id},
        )
        return processed_email

    def is_email_processed(self, user_id: int, gmail_message_id: str) -> bool:
        """Return True when a Gmail message has already been handled for this user."""
        processed_email = (
            self.db.query(ProcessedEmail)
            .filter_by(user_id=user_id, gmail_id=gmail_message_id)
            .first()
        )
        return processed_email is not None

    def _list_message_refs(
        self,
        user_id: int,
        max_results: int,
        label_ids: Sequence[str],
        query: str,
    ) -> List[Dict[str, Any]]:
        """List Gmail message references matching the requested filters."""
        try:
            gmail_client = self._build_gmail_client(user_id)
            response = (
                gmail_client.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=list(label_ids),
                    q=query,
                    maxResults=max_results,
                )
                .execute()
            )
        except HttpError as exc:
            logger.error(
                "Gmail list request failed.",
                extra={"user_id": user_id, "query": query},
                exc_info=True,
            )
            raise GmailServiceError("Failed to list Gmail messages.") from exc

        messages = response.get("messages", []) or []
        logger.info(
            "Loaded Gmail message references.",
            extra={"user_id": user_id, "message_count": len(messages)},
        )
        return [message for message in messages if isinstance(message, dict)]

    def _get_message(self, user_id: int, gmail_message_id: str) -> Dict[str, Any]:
        """Fetch a full Gmail message by ID."""
        try:
            gmail_client = self._build_gmail_client(user_id)
            response = (
                gmail_client.users()
                .messages()
                .get(userId="me", id=gmail_message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            logger.error(
                "Gmail get request failed.",
                extra={"user_id": user_id, "gmail_message_id": gmail_message_id},
                exc_info=True,
            )
            raise GmailServiceError(
                f"Failed to load Gmail message '{gmail_message_id}'."
            ) from exc

        if not isinstance(response, dict):
            raise GmailServiceError("Gmail returned an unexpected message payload.")

        return response

    def _build_gmail_client(self, user_id: int) -> Any:
        """
        Build a Gmail client using fresh credentials.

        AuthService is called before every Gmail API request, which ensures expired
        OAuth access tokens are refreshed before list/get operations execute.
        """
        auth_service = self.auth_service_factory(self.db)
        credentials = auth_service.get_user_credentials(user_id)
        if credentials is None:
            raise GmailAuthenticationError(
                f"No valid Google credentials found for user ID {user_id}."
            )

        return self.gmail_client_builder(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )
