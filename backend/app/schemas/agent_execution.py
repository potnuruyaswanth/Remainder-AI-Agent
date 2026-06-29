from datetime import datetime
from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


AgentExecutionStatus = Literal["success", "partial_success", "failed"]


class EmailFailureDetail(BaseModel):
    """Structured record of an email-level failure during one agent run."""

    gmail_message_id: str
    subject: str = ""
    stage: Literal["observe", "reason", "act", "verify"]
    error_message: str

    model_config = ConfigDict(extra="forbid")


class AgentExecutionResult(BaseModel):
    """
    Strongly typed execution summary for one EmailTaskAgent run.

    Future schedulers and dashboards can consume this model without needing to
    interpret raw dictionaries or scan logs for counts.
    """

    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime
    finished_at: datetime
    emails_checked: int = 0
    new_emails: int = 0
    emails_processed: int = 0
    emails_skipped: int = 0
    tasks_created: int = 0
    tasks_updated: int = 0
    tasks_failed: int = 0
    total_failures: int = 0
    execution_status: AgentExecutionStatus
    execution_time_ms: int
    failures: List[EmailFailureDetail] = Field(default_factory=list)
    observe_retry_count: int = 0

    model_config = ConfigDict(extra="forbid")
