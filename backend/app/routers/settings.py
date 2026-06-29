from fastapi import APIRouter, Depends

from app.dependencies import get_settings_service
from app.routers.auth import get_current_user
from app.schemas.settings_api import SettingsResponse, SettingsUpdateRequest
from app.services.settings_service import SettingsService


router = APIRouter()


@router.get("", response_model=SettingsResponse)
def get_settings(
    current_user=Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
):
    return settings_service.get_settings()


@router.put("", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdateRequest,
    current_user=Depends(get_current_user),
    settings_service: SettingsService = Depends(get_settings_service),
):
    return settings_service.update_settings(payload)
