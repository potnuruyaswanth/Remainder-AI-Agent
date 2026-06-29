from typing import List

from fastapi import APIRouter, Depends

from app.dependencies import get_agent, get_scheduler_state
from app.routers.auth import get_current_user
from app.schemas.agent_api import AgentRunResponse, AgentStatusResponse
from app.schemas.agent_execution import AgentExecutionResult


router = APIRouter()

_agent_history: List[AgentExecutionResult] = []


@router.post("/run", response_model=AgentRunResponse)
def run_agent(
    current_user=Depends(get_current_user),
    agent=Depends(get_agent),
):
    execution = agent.run()
    _agent_history.insert(0, execution)
    del _agent_history[20:]
    return AgentRunResponse(execution=execution)


@router.get("/status", response_model=AgentStatusResponse)
def get_agent_status(
    current_user=Depends(get_current_user),
    scheduler=Depends(get_scheduler_state),
):
    return AgentStatusResponse(
        scheduler_enabled=scheduler is not None,
        scheduler_running=bool(getattr(scheduler, "_is_running", False)) if scheduler is not None else False,
        last_execution=_agent_history[0] if _agent_history else None,
    )


@router.get("/history", response_model=list[AgentExecutionResult])
def get_agent_history(current_user=Depends(get_current_user)):
    return _agent_history
