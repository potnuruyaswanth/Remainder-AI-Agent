from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, List

from app.scheduler.scheduler import AgentScheduler, SchedulerConfig
from app.schemas.agent_execution import AgentExecutionResult


class FakeBackgroundScheduler:
    """Minimal scheduler double for lifecycle and registration tests."""

    def __init__(self) -> None:
        self.jobs: List[dict[str, Any]] = []
        self.started = False
        self.shutdown_called = False

    def add_job(self, func: Callable[..., Any], **kwargs: Any) -> None:
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = False) -> None:
        self.shutdown_called = True


def make_result(status: str = "success") -> AgentExecutionResult:
    return AgentExecutionResult(
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        emails_checked=1,
        new_emails=1,
        emails_processed=1 if status == "success" else 0,
        emails_skipped=0,
        tasks_created=1,
        tasks_updated=0,
        tasks_failed=0 if status == "success" else 1,
        total_failures=0 if status == "success" else 1,
        execution_status=status,
        execution_time_ms=100,
    )


def build_scheduler(
    agent_runner: Callable[[], AgentExecutionResult],
    config: SchedulerConfig | None = None,
    scheduler_factory: Callable[[], FakeBackgroundScheduler] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> AgentScheduler:
    return AgentScheduler(
        agent_runner=agent_runner,
        config=config
        or SchedulerConfig(
            enabled=True,
            interval_minutes=5,
            max_concurrent_runs=1,
            retry_delay_seconds=1,
        ),
        scheduler_factory=scheduler_factory or FakeBackgroundScheduler,
        sleep_fn=sleep_fn or (lambda _: None),
    )


def test_scheduler_startup_registers_and_starts_job():
    scheduler = build_scheduler(agent_runner=lambda: make_result())

    scheduler.start()

    assert scheduler.scheduler is not None
    assert scheduler.scheduler.started is True
    assert len(scheduler.scheduler.jobs) == 1
    assert scheduler.scheduler.jobs[0]["id"] == AgentScheduler.JOB_ID


def test_scheduler_shutdown_stops_background_scheduler():
    scheduler = build_scheduler(agent_runner=lambda: make_result())
    scheduler.start()

    scheduler.shutdown()

    assert scheduler.scheduler.shutdown_called is True


def test_job_registration_uses_configuration_values():
    scheduler = build_scheduler(
        agent_runner=lambda: make_result(),
        config=SchedulerConfig(
            enabled=True,
            interval_minutes=9,
            max_concurrent_runs=1,
            retry_delay_seconds=3,
        ),
    )

    scheduler.start()

    job = scheduler.scheduler.jobs[0]
    assert job["trigger"] == "interval"
    assert job["minutes"] == 9
    assert job["max_instances"] == 1
    assert job["replace_existing"] is True


def test_single_execution_runs_agent_once():
    call_count = {"count": 0}

    def agent_runner():
        call_count["count"] += 1
        return make_result()

    scheduler = build_scheduler(agent_runner=agent_runner)

    result = scheduler.trigger_job()

    assert result is not None
    assert call_count["count"] == 1


def test_prevent_overlapping_execution_skips_when_lock_is_held():
    scheduler = build_scheduler(agent_runner=lambda: make_result())
    acquired = scheduler._execution_lock.acquire(blocking=False)
    assert acquired is True

    try:
        result = scheduler.trigger_job()
    finally:
        scheduler._execution_lock.release()

    assert result is None


def test_configuration_loading_disables_scheduler_start():
    fake_scheduler = FakeBackgroundScheduler()
    scheduler = build_scheduler(
        agent_runner=lambda: make_result(),
        config=SchedulerConfig(
            enabled=False,
            interval_minutes=5,
            max_concurrent_runs=1,
            retry_delay_seconds=1,
        ),
        scheduler_factory=lambda: fake_scheduler,
    )

    scheduler.start()

    assert scheduler.scheduler is None
    assert fake_scheduler.started is False


def test_failure_handling_retries_once_then_returns_none():
    call_count = {"count": 0}
    sleep_calls: List[float] = []

    def agent_runner():
        call_count["count"] += 1
        raise RuntimeError("boom")

    scheduler = build_scheduler(
        agent_runner=agent_runner,
        sleep_fn=lambda seconds: sleep_calls.append(seconds),
    )

    result = scheduler.trigger_job()

    assert result is None
    assert call_count["count"] == 2
    assert sleep_calls == [1.0]


def test_mock_email_task_agent_run_success_path():
    statuses: List[str] = []

    def agent_runner():
        result = make_result(status="partial_success")
        statuses.append(result.execution_status)
        return result

    scheduler = build_scheduler(agent_runner=agent_runner)
    result = scheduler.trigger_job()

    assert result is not None
    assert statuses == ["partial_success"]
