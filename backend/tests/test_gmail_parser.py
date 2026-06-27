import base64

import pytest

from app.utils.gmail_parser import (
    GmailParserError,
    decode_base64url,
    html_to_text,
    parse_gmail_message,
)


def encode_text(value: str) -> str:
    """Encode text into the Base64URL form Gmail uses."""
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_decode_base64url_returns_original_text():
    encoded = encode_text("Hello from Gmail")
    assert decode_base64url(encoded) == "Hello from Gmail"


def test_decode_base64url_rejects_invalid_content():
    with pytest.raises(GmailParserError):
        decode_base64url("%%%not-valid%%%")


def test_parse_gmail_message_prefers_plain_text_body():
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Project reminder",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "alice@example.com"},
                {"name": "To", "value": "bob@example.com"},
                {"name": "Subject", "value": "Reminder"},
                {"name": "Date", "value": "Fri, 27 Jun 2026 10:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encode_text("Plain body text")},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": encode_text("<p>HTML body text</p>")},
                },
            ],
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed.gmail_message_id == "msg-1"
    assert parsed.thread_id == "thread-1"
    assert parsed.sender == "alice@example.com"
    assert parsed.recipient == "bob@example.com"
    assert parsed.subject == "Reminder"
    assert parsed.date == "Fri, 27 Jun 2026 10:00:00 +0000"
    assert parsed.labels == ["INBOX", "UNREAD"]
    assert parsed.body == "Plain body text"
    assert parsed.snippet == "Project reminder"


def test_parse_gmail_message_uses_html_fallback_when_plain_missing():
    message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "labelIds": ["INBOX"],
        "snippet": "HTML only",
        "payload": {
            "mimeType": "text/html",
            "headers": [],
            "body": {"data": encode_text("<p>Hello <strong>team</strong></p><br>Next line")},
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed.body == "Hello team\nNext line"


def test_parse_gmail_message_handles_nested_multipart_payloads():
    message = {
        "id": "msg-3",
        "threadId": "thread-3",
        "snippet": "Nested content",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": encode_text("Nested plain content")},
                        }
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "report.pdf",
                    "body": {"attachmentId": "attach-1"},
                },
            ],
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed.body == "Nested plain content"


def test_html_to_text_removes_tags_and_decodes_entities():
    result = html_to_text("<p>One &amp; Two</p><script>alert('x')</script><br>Done")
    assert result == "One & Two\nDone"
