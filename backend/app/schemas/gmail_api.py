from pydantic import BaseModel, ConfigDict


class GmailStatusResponse(BaseModel):
    """Status payload for Gmail connectivity and dedup state."""

    connected: bool
    processed_email_count: int

    model_config = ConfigDict(extra="forbid")


class GmailSyncResponse(BaseModel):
    """Response payload for manual Gmail synchronization requests."""

    new_emails: int
    status: str

    model_config = ConfigDict(extra="forbid")


class GmailTestResponse(BaseModel):
    """Response payload for Gmail service smoke tests."""

    status: str
    message: str

    model_config = ConfigDict(extra="forbid")
