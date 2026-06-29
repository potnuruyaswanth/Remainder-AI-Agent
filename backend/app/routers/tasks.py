from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_task_service
from app.routers.auth import get_current_user
from app.schemas.common import MessageResponse
from app.schemas.task_api import TaskCreateRequest, TaskListResponse, TaskResponse, TaskUpdateRequest
from app.services.task_service import TaskService


router = APIRouter()


@router.get("", response_model=TaskListResponse)
def list_tasks(
    current_user=Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
):
    tasks = task_service.list_tasks(current_user.id)
    return TaskListResponse(tasks=[TaskResponse.model_validate(task) for task in tasks])


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    current_user=Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
):
    task = task_service.create_task(current_user.id, payload)
    return TaskResponse.model_validate(task)


@router.put("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    payload: TaskUpdateRequest,
    current_user=Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
):
    task = task_service.get_task(current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    updated_task = task_service.update_task(task, payload)
    return TaskResponse.model_validate(updated_task)


@router.delete("/{task_id}", response_model=MessageResponse)
def delete_task(
    task_id: int,
    current_user=Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
):
    task = task_service.get_task(current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task_service.delete_task(task)
    return MessageResponse(status="deleted", message="Task deleted successfully.")
