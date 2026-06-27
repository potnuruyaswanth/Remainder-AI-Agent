from typing import Any, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.email import ProcessedEmail
from app.models.user import User
from app.services.gmail_service import GmailAuthenticationError, GmailService
from app.utils.gmail_parser import ParsedEmail


TEST_DATABASE_URL = "sqlite:///:memory:"


class FakeRequest:
    """Simple executable wrapper that mimics googleapiclient request objects."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> Dict[str, Any]:
        return self.payload


class FakeMessagesResource:
    """Fake Gmail messages resource used to verify service behavior."""

    def __init__(self, list_payload: Dict[str, Any], message_payloads: Dict[str, Dict[str, Any]]) -> None:
        self.list_payload = list_payload
        self.message_payloads = message_payloads
        self.list_calls: List[Dict[str, Any]] = []
        self.get_calls: List[Dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeRequest:
        self.list_calls.append(kwargs)
        return FakeRequest(self.list_payload)

    def get(self, **kwargs: Any) -> FakeRequest:
        self.get_calls.append(kwargs)
        return FakeRequest(self.message_payloads[kwargs["id"]])


class FakeUsersResource:
    """Fake Gmail users resource."""

    def __init__(self, messages_resource: FakeMessagesResource) -> None:
        self.messages_resource = messages_resource

    def messages(self) -> FakeMessagesResource:
        return self.messages_resource


class FakeGmailClient:
    """Fake top-level Gmail API client."""

    def __init__(self, messages_resource: FakeMessagesResource) -> None:
        self.messages_resource = messages_resource

    def users(self) -> FakeUsersResource:
        return FakeUsersResource(self.messages_resource)


class StubAuthService:
    """Test auth service that records how often credentials are requested."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.calls: List[int] = []

    def get_user_credentials(self, user_id: int) -> object:
        self.calls.append(user_id)
        return {"access_token": "refreshed-token"}


class MissingCredentialsAuthService:
    """Auth service stub that simulates a missing OAuth session."""

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


def build_gmail_service(
    db_session: Session,
    messages_resource: FakeMessagesResource,
    auth_service_factory=StubAuthService,
) -> GmailService:
    """Construct a GmailService with fake dependencies for isolated tests."""

    def gmail_client_builder(*args: Any, **kwargs: Any) -> FakeGmailClient:
        return FakeGmailClient(messages_resource)

    return GmailService(
        db=db_session,
        auth_service_factory=auth_service_factory,
        gmail_client_builder=gmail_client_builder,
    )


def create_user(db_session: Session) -> User:
    user = User(email="learner@example.com", credentials="encrypted-creds")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def build_message_payload(
    message_id: str,
    body_text: str,
    mime_type: str = "text/plain",
) -> Dict[str, Any]:
    import base64

    encoded_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("utf-8").rstrip("=")
    return {
        "id": message_id,
        "threadId": f"thread-{message_id}",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": f"snippet-{message_id}",
        "payload": {
            "mimeType": mime_type,
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
                {"name": "Subject", "value": f"Subject {message_id}"},
                {"name": "Date", "value": "Fri, 27 Jun 2026 10:00:00 +0000"},
            ],
            "body": {"data": encoded_body},
        },
    }


def test_list_new_emails_filters_duplicates(db_session: Session):
    user = create_user(db_session)
    db_session.add(
        ProcessedEmail(
            user_id=user.id,
            gmail_id="msg-processed",
            subject="Already handled",
            snippet="duplicate",
        )
    )
    db_session.commit()

    messages_resource = FakeMessagesResource(
        list_payload={"messages": [{"id": "msg-processed"}, {"id": "msg-new"}]},
        message_payloads={"msg-new": build_message_payload("msg-new", "New body")},
    )
    service = build_gmail_service(db_session, messages_resource)

    parsed_emails = service.list_new_emails(user_id=user.id, max_results=5)

    assert [email.gmail_message_id for email in parsed_emails] == ["msg-new"]
    assert messages_resource.list_calls[0]["labelIds"] == ["INBOX", "UNREAD"]
    assert [call["id"] for call in messages_resource.get_calls] == ["msg-new"]


def test_mark_email_processed_is_idempotent(db_session: Session):
    user = create_user(db_session)
    messages_resource = FakeMessagesResource(list_payload={"messages": []}, message_payloads={})
    service = build_gmail_service(db_session, messages_resource)
    parsed_email = ParsedEmail(
        gmail_message_id="msg-1",
        thread_id="thread-1",
        sender="sender@example.com",
        recipient="recipient@example.com",
        subject="Subject",
        date="Fri, 27 Jun 2026 10:00:00 +0000",
        labels=["INBOX"],
        body="Body",
        snippet="Snippet",
    )

    first_record = service.mark_email_processed(user.id, parsed_email)
    second_record = service.mark_email_processed(user.id, parsed_email)

    assert first_record.id == second_record.id
    assert (
        db_session.query(ProcessedEmail)
        .filter_by(user_id=user.id, gmail_id="msg-1")
        .count()
        == 1
    )


def test_refreshes_credentials_before_each_gmail_request(db_session: Session):
    user = create_user(db_session)
    messages_resource = FakeMessagesResource(
        list_payload={"messages": [{"id": "msg-a"}, {"id": "msg-b"}]},
        message_payloads={
            "msg-a": build_message_payload("msg-a", "A"),
            "msg-b": build_message_payload("msg-b", "B"),
        },
    )

    auth_service_instances: List[StubAuthService] = []

    def auth_service_factory(db: Session) -> StubAuthService:
        instance = StubAuthService(db)
        auth_service_instances.append(instance)
        return instance

    service = build_gmail_service(
        db_session=db_session,
        messages_resource=messages_resource,
        auth_service_factory=auth_service_factory,
    )

    parsed_emails = service.list_new_emails(user_id=user.id)

    assert [email.gmail_message_id for email in parsed_emails] == ["msg-a", "msg-b"]
    assert len(auth_service_instances) == 3
    assert all(instance.calls == [user.id] for instance in auth_service_instances)


def test_raises_authentication_error_when_credentials_missing(db_session: Session):
    user = create_user(db_session)
    messages_resource = FakeMessagesResource(list_payload={"messages": []}, message_payloads={})
    service = build_gmail_service(
        db_session=db_session,
        messages_resource=messages_resource,
        auth_service_factory=MissingCredentialsAuthService,
    )

    with pytest.raises(GmailAuthenticationError):
        service.list_new_emails(user_id=user.id)


def test_parses_multiple_email_formats_in_service(db_session: Session):
    user = create_user(db_session)
    html_body = "<p>Hello <strong>team</strong></p>"
    messages_resource = FakeMessagesResource(
        list_payload={"messages": [{"id": "msg-plain"}, {"id": "msg-html"}]},
        message_payloads={
            "msg-plain": build_message_payload("msg-plain", "Plain content"),
            "msg-html": build_message_payload("msg-html", html_body, mime_type="text/html"),
        },
    )
    service = build_gmail_service(db_session, messages_resource)

    parsed_emails = service.list_new_emails(user_id=user.id)

    assert parsed_emails[0].body == "Plain content"
    assert parsed_emails[1].body == "Hello team"
