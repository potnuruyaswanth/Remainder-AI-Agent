from pydantic import BaseModel, ConfigDict


class MessageResponse(BaseModel):
    """Generic API response for simple success messages."""

    status: str
    message: str

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    """Centralized error payload returned by exception handlers."""

    detail: str

    model_config = ConfigDict(extra="forbid")
