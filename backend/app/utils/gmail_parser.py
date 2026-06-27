import base64
import binascii
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List, Mapping, Sequence


@dataclass(slots=True)
class ParsedEmail:
    """Normalized email payload returned by Gmail parsing utilities."""

    gmail_message_id: str
    thread_id: str
    sender: str
    recipient: str
    subject: str
    date: str
    labels: List[str]
    body: str
    snippet: str


class GmailParserError(ValueError):
    """Raised when a Gmail message cannot be parsed into the expected shape."""


def decode_base64url(data: str) -> str:
    """Decode Gmail Base64URL text into UTF-8 content."""
    if not data:
        return ""

    padding = (-len(data)) % 4
    normalized = data + ("=" * padding)

    try:
        decoded_bytes = base64.urlsafe_b64decode(normalized.encode("utf-8"))
    except (binascii.Error, ValueError) as exc:
        raise GmailParserError("Invalid Base64URL body received from Gmail.") from exc

    return decoded_bytes.decode("utf-8", errors="replace")


def parse_gmail_message(message: Mapping[str, Any]) -> ParsedEmail:
    """Convert a raw Gmail API message payload into a normalized email object."""
    gmail_message_id = str(message.get("id", "")).strip()
    thread_id = str(message.get("threadId", "")).strip()
    payload = message.get("payload") or {}

    if not gmail_message_id or not thread_id or not isinstance(payload, Mapping):
        raise GmailParserError("Gmail message is missing required metadata.")

    headers = extract_headers(payload.get("headers", []))
    body = extract_email_body(payload)

    return ParsedEmail(
        gmail_message_id=gmail_message_id,
        thread_id=thread_id,
        sender=headers.get("from", ""),
        recipient=headers.get("to", ""),
        subject=headers.get("subject", ""),
        date=headers.get("date", ""),
        labels=[str(label) for label in message.get("labelIds", [])],
        body=body,
        snippet=str(message.get("snippet", "")).strip(),
    )


def extract_headers(headers: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """Return lower-cased header names mapped to their string values."""
    extracted: Dict[str, str] = {}

    for header in headers:
        name = str(header.get("name", "")).strip().lower()
        value = str(header.get("value", "")).strip()
        if name and value:
            extracted[name] = value

    return extracted


def extract_email_body(payload: Mapping[str, Any]) -> str:
    """Prefer plain text content and fall back to HTML converted into text."""
    plain_parts: List[str] = []
    html_parts: List[str] = []
    _collect_bodies(payload, plain_parts, html_parts)

    if plain_parts:
        return _normalize_body("\n".join(part for part in plain_parts if part))

    if html_parts:
        html_body = "\n".join(part for part in html_parts if part)
        return _normalize_body(html_to_text(html_body))

    return ""


def html_to_text(html_content: str) -> str:
    """Convert basic HTML email content into readable plain text."""
    if not html_content:
        return ""

    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_content)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    return _normalize_body(text)


def _collect_bodies(
    part: Mapping[str, Any],
    plain_parts: List[str],
    html_parts: List[str],
) -> None:
    """Walk a Gmail MIME tree and collect text/plain and text/html bodies."""
    mime_type = str(part.get("mimeType", "")).lower()
    filename = str(part.get("filename", ""))
    body = part.get("body") or {}
    data = body.get("data")

    if data and not filename:
        decoded_body = decode_base64url(str(data))
        if mime_type == "text/plain":
            plain_parts.append(decoded_body)
        elif mime_type == "text/html":
            html_parts.append(decoded_body)
        elif not part.get("parts"):
            plain_parts.append(decoded_body)

    for child_part in part.get("parts", []) or []:
        if isinstance(child_part, Mapping):
            _collect_bodies(child_part, plain_parts, html_parts)


def _normalize_body(body: str) -> str:
    """Collapse noisy whitespace while preserving line breaks where useful."""
    compact_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in body.splitlines()]
    meaningful_lines = [line for line in compact_lines if line]
    return "\n".join(meaningful_lines).strip()
