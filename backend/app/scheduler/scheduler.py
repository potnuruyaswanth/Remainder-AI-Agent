from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import perf_counter, sleep
from typing import Any, Callable, Optional

from app.schemas.agent_execution import AgentExecutionResult
from app.utils.logger import logger

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:  # pragma: no cover - exercised only when optional deps are missing
    BackgroundScheduler = None  # type: ignore[assignment]


@dataclass(slots=True)
class SchedulerConfig:
    """Configuration values consumed by the background scheduler wrapper."""

    enabled: bool
    interval_minutes: int
    max_concurrent_runs: int
    retry_delay_seconds: int


class AgentScheduler:
    """
    Thin scheduler wrapper that only triggers EmailTaskAgent.run().

    It owns lifecycle concerns such as registration, overlap prevention,
    startup/shutdown, and infrastructure-level retry behavior. It does not
    know how Gmail, Gemini, or Google Tasks work internally.
    """

    JOB_ID = "email-task-agent-run"

    def __init__(
        self,
        agent_runner: Callable[[], AgentExecutionResult],
        config: SchedulerConfig,
        scheduler_factory: Optional[Callable[[], Any]] = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.agent_runner = agent_runner
        self.config = config
        self.scheduler_factory = scheduler_factory or self._default_scheduler_factory
        self.sleep_fn = sleep_fn
        self._scheduler: Any | None = None
        self._is_running = False
        self._execution_lock = Lock()

    @property
    def scheduler(self) -> Any | None:
        """Expose the underlying scheduler instance for tests and diagnostics."""
        return self._scheduler

    def start(self) -> None:
        """Initialize and start the background scheduler if enabled."""
        if not self.config.enabled:
            logger.info("Scheduler disabled by configuration.")
            return

        if self._scheduler is None:
            self._scheduler = self.scheduler_factory()
            self._register_job()

        if self._is_running:
            return

        self._scheduler.start()
        self._is_running = True
        logger.info(
            "Scheduler Started",
            extra={
                "interval_minutes": self.config.interval_minutes,
                "max_concurrent_runs": self.config.max_concurrent_runs,
            },
        )

    def shutdown(self) -> None:
        """Stop the scheduler gracefully during application shutdown."""
        if self._scheduler is None or not self._is_running:
            return

        self._scheduler.shutdown(wait=False)
        self._is_running = False
        logger.info("Scheduler Stopped")

    def trigger_job(self) -> AgentExecutionResult | None:
        """Run the scheduled job once, respecting overlap prevention."""
        if not self._execution_lock.acquire(blocking=False):
            logger.warning("Skipped Execution", extra={"reason": "agent run already in progress"})
            return None

        started_at = perf_counter()
        logger.info("Job Started")

        try:
            result = self._execute_with_retry()
            logger.info(
                "Execution Summary",
                extra={
                    "execution_id": result.execution_id,
                    "execution_status": result.execution_status,
                    "emails_processed": result.emails_processed,
                    "tasks_failed": result.tasks_failed,
                    "execution_time_ms": result.execution_time_ms,
                },
            )
            return result
        except Exception:
            logger.error("Job Finished with failure.", exc_info=True)
            return None
        finally:
            job_time_ms = int((perf_counter() - started_at) * 1000)
            logger.info("Job Finished", extra={"execution_time_ms": job_time_ms})
            self._execution_lock.release()

    def _execute_with_retry(self) -> AgentExecutionResult:
        """Retry one failed scheduler-triggered agent execution after a delay."""
        last_exception: Exception | None = None

        for attempt in range(2):
            try:
                return self.agent_runner()
            except Exception as exc:  # noqa: BLE001 - normalized by scheduler layer
                last_exception = exc
                if attempt == 0 and self.config.retry_delay_seconds > 0:
                    logger.warning(
                        "Retry Attempts",
                        extra={
                            "attempt": attempt + 1,
                            "retry_delay_seconds": self.config.retry_delay_seconds,
                        },
                        exc_info=True,
                    )
                    self.sleep_fn(float(self.config.retry_delay_seconds))
                    continue
                raise

        raise RuntimeError("Scheduled execution failed after retry.") from last_exception

    def _register_job(self) -> None:
        """Register the repeating EmailTaskAgent.run() job."""
        self._scheduler.add_job(
            self.trigger_job,
            trigger="interval",
            minutes=self.config.interval_minutes,
            id=self.JOB_ID,
            max_instances=self.config.max_concurrent_runs,
            coalesce=True,
            replace_existing=True,
        )

    @staticmethod
    def _default_scheduler_factory() -> Any:
        """Create the real APScheduler BackgroundScheduler when available."""
        if BackgroundScheduler is None:
            raise RuntimeError(
                "APScheduler is not installed. Install apscheduler to enable background scheduling."
            )
        return BackgroundScheduler()
