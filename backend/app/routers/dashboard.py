from fastapi import APIRouter, Depends

from app.dependencies import get_dashboard_service
from app.routers.auth import get_current_user
from app.schemas.dashboard import DashboardStatsResponse
from app.services.dashboard_service import DashboardService


router = APIRouter()


@router.get("", response_model=DashboardStatsResponse)
def get_dashboard(
    current_user=Depends(get_current_user),
    dashboard_service: DashboardService = Depends(get_dashboard_service),
):
    return dashboard_service.get_dashboard(current_user.id)
