from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TaskCategory = Literal[
    "Assignment",
    "Quiz",
    "Exam",
    "Interview",
    "Meeting",
    "Project Deadline",
    "Bill Payment",
    "Event",
    "Internship",
    "Job Assessment",
]

TaskPriority = Literal["High", "Medium", "Low"]


class TaskCandidate(BaseModel):
    """
    Structured task candidate extracted from one email.

    This schema is validated before the rest of the system sees any AI output,
    which protects future modules from malformed or hallucinated fields.
    """

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    category: TaskCategory
    priority: TaskPriority
    deadline: Optional[datetime] = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    important: bool

    model_config = ConfigDict(extra="forbid")


class TaskExtractionResult(BaseModel):
    """Validated wrapper for Gemini JSON output."""

    tasks: List[TaskCandidate] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
