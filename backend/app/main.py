from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.email_task_agent import EmailTaskAgent
from app.config import settings
from app.database import SessionLocal, init_db
from app.exceptions import register_exception_handlers
from app.routers.auth import router as auth_router
from app.routers.agent import router as agent_router
from app.routers.dashboard import router as dashboard_router
from app.routers.gmail import router as gmail_router
from app.routers.settings import router as settings_router
from app.routers.tasks import router as tasks_router
from app.scheduler.scheduler import AgentScheduler, SchedulerConfig
from app.services.gemini_service import GeminiService
from app.services.gmail_service import GmailService
from app.services.google_tasks_service import GoogleTasksService
from app.utils.logger import logger


def build_agent_runner():
    """Create the single callable that the scheduler is allowed to execute."""

    def run_agent():
        if settings.SCHEDULER_USER_ID is None:
            raise RuntimeError("SCHEDULER_USER_ID must be configured when the scheduler is enabled.")

        db = SessionLocal()
        try:
            agent = EmailTaskAgent(
                gmail_service=GmailService(db),
                gemini_service=GeminiService(),
                google_tasks_service=GoogleTasksService(db),
                user_id=settings.SCHEDULER_USER_ID,
            )
            return agent.run()
        finally:
            db.close()

    return run_agent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler = None
    if settings.SCHEDULER_ENABLED:
        scheduler = AgentScheduler(
            agent_runner=build_agent_runner(),
            config=SchedulerConfig(
                enabled=settings.SCHEDULER_ENABLED,
                interval_minutes=settings.SCHEDULER_INTERVAL_MINUTES,
                max_concurrent_runs=settings.SCHEDULER_MAX_CONCURRENT_RUNS,
                retry_delay_seconds=settings.SCHEDULER_RETRY_DELAY_SECONDS,
            ),
        )
        try:
            scheduler.start()
        except Exception:
            logger.error("Failed to start scheduler during application startup.", exc_info=True)
    _.state.agent_scheduler = scheduler
    yield
    if scheduler is not None:
        scheduler.shutdown()


app = FastAPI(
    title="AI Email Productivity Agent",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(tasks_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(gmail_router, prefix="/api/gmail", tags=["gmail"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(agent_router, prefix="/api/agent", tags=["agent"])

register_exception_handlers(app)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}
