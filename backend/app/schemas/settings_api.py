from pydantic import BaseModel, ConfigDict


class SettingsResponse(BaseModel):
    """Safe application settings returned to the frontend."""

    frontend_url: str
    tasklist_id: str
    sync_interval_min: int
    scheduler_enabled: bool
    scheduler_interval_minutes: int
    scheduler_max_concurrent_runs: int
    scheduler_retry_delay_seconds: int
    scheduler_user_id: int | None

    model_config = ConfigDict(extra="forbid")


class SettingsUpdateRequest(BaseModel):
    """Request payload for updating runtime-facing scheduler settings."""

    sync_interval_min: int | None = None
    scheduler_enabled: bool | None = None
    scheduler_interval_minutes: int | None = None
    scheduler_max_concurrent_runs: int | None = None
    scheduler_retry_delay_seconds: int | None = None
    scheduler_user_id: int | None = None

    model_config = ConfigDict(extra="forbid")
