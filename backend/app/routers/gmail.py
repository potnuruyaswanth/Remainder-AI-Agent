from fastapi import APIRouter, Depends

from app.dependencies import get_dashboard_service, get_gmail_service
from app.routers.auth import get_current_user
from app.schemas.gmail_api import GmailStatusResponse, GmailSyncResponse, GmailTestResponse
from app.services.dashboard_service import DashboardService
from app.services.gmail_service import GmailService


router = APIRouter()


@router.post("/sync", response_model=GmailSyncResponse)
def sync_gmail(
    current_user=Depends(get_current_user),
    gmail_service: GmailService = Depends(get_gmail_service),
):
    emails = gmail_service.list_new_emails(user_id=current_user.id)
    return GmailSyncResponse(new_emails=len(emails), status="synced")


@router.post("/test", response_model=GmailTestResponse)
def test_gmail(
    current_user=Depends(get_current_user),
    gmail_service: GmailService = Depends(get_gmail_service),
):
    gmail_service.list_new_emails(user_id=current_user.id, max_results=1)
    return GmailTestResponse(status="ok", message="Gmail service responded successfully.")


@router.get("/status", response_model=GmailStatusResponse)
def gmail_status(
    current_user=Depends(get_current_user),
    dashboard_service: DashboardService = Depends(get_dashboard_service),
):
    return GmailStatusResponse(
        connected=True,
        processed_email_count=dashboard_service.processed_email_count(current_user.id),
    )
