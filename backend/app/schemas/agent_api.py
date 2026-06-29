from pydantic import BaseModel, ConfigDict

from app.schemas.agent_execution import AgentExecutionResult


class AgentStatusResponse(BaseModel):
    """API payload describing the current scheduler/agent status."""

    scheduler_enabled: bool
    scheduler_running: bool
    last_execution: AgentExecutionResult | None = None

    model_config = ConfigDict(extra="forbid")


class AgentRunResponse(BaseModel):
    """Response payload for manual agent execution."""

    execution: AgentExecutionResult

    model_config = ConfigDict(extra="forbid")
