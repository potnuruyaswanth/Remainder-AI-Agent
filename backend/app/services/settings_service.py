from app.config import settings
from app.schemas.settings_api import SettingsResponse, SettingsUpdateRequest


class SettingsService:
    """Service layer for safe settings reads and in-memory updates."""

    def get_settings(self) -> SettingsResponse:
        """Return safe runtime settings for API clients."""
        return SettingsResponse(
            frontend_url=settings.FRONTEND_URL,
            tasklist_id=settings.TASKLIST_ID,
            sync_interval_min=settings.SYNC_INTERVAL_MIN,
            scheduler_enabled=settings.SCHEDULER_ENABLED,
            scheduler_interval_minutes=settings.SCHEDULER_INTERVAL_MINUTES,
            scheduler_max_concurrent_runs=settings.SCHEDULER_MAX_CONCURRENT_RUNS,
            scheduler_retry_delay_seconds=settings.SCHEDULER_RETRY_DELAY_SECONDS,
            scheduler_user_id=settings.SCHEDULER_USER_ID,
        )

    def update_settings(self, payload: SettingsUpdateRequest) -> SettingsResponse:
        """Apply runtime-safe in-memory settings updates and return the new view."""
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(settings, key.upper(), value)
        return self.get_settings()
