from datetime import datetime
from time import perf_counter
from typing import List, Sequence

from app.schemas.agent_execution import AgentExecutionResult, EmailFailureDetail
from app.schemas.google_tasks import TaskSyncResult
from app.schemas.task_candidate import TaskCandidate
from app.services.gemini_service import GeminiService
from app.services.gmail_service import GmailService
from app.services.google_tasks_service import GoogleTasksService
from app.utils.gmail_parser import ParsedEmail
from app.utils.logger import logger


class EmailTaskAgent:
    """
    Orchestration layer for the Observe -> Reason -> Act -> Verify workflow.

    The agent coordinates existing services but deliberately avoids owning
    Gmail parsing, Gemini prompting, Google Tasks API details, or database
    business logic. That separation keeps the module testable and prepares it
    for scheduler-driven execution in the next module.
    """

    def __init__(
        self,
        gmail_service: GmailService,
        gemini_service: GeminiService,
        google_tasks_service: GoogleTasksService,
        user_id: int,
        max_emails_per_run: int = 10,
    ) -> None:
        self.gmail_service = gmail_service
        self.gemini_service = gemini_service
        self.google_tasks_service = google_tasks_service
        self.user_id = user_id
        self.max_emails_per_run = max_emails_per_run

    def run(self) -> AgentExecutionResult:
        """Run one full Observe -> Reason -> Act -> Verify cycle."""
        started_at = datetime.utcnow()
        started_at_perf = perf_counter()
        failures: List[EmailFailureDetail] = []

        logger.info(
            "Agent Started",
            extra={"user_id": self.user_id, "max_emails_per_run": self.max_emails_per_run},
        )

        emails, observe_retry_count, observe_failure = self._observe()
        emails_checked = len(emails)
        new_emails = len(emails)
        emails_processed = 0
        emails_skipped = 0
        tasks_created = 0
        tasks_updated = 0
        tasks_failed = 0

        if observe_failure is not None:
            failures.append(observe_failure)

        for email in emails:
            try:
                task_candidates = self._reason(email)
            except Exception as exc:  # noqa: BLE001 - error recorded in execution summary
                failures.append(
                    EmailFailureDetail(
                        gmail_message_id=email.gmail_message_id,
                        subject=email.subject,
                        stage="reason",
                        error_message=str(exc),
                    )
                )
                emails_skipped += 1
                continue

            if not task_candidates:
                logger.info(
                    "Reason stage produced no actionable tasks.",
                    extra={"gmail_message_id": email.gmail_message_id},
                )
                emails_skipped += 1
                continue

            try:
                sync_results = self._act(task_candidates)
            except Exception as exc:  # noqa: BLE001 - error recorded in execution summary
                failures.append(
                    EmailFailureDetail(
                        gmail_message_id=email.gmail_message_id,
                        subject=email.subject,
                        stage="act",
                        error_message=str(exc),
                    )
                )
                tasks_failed += len(task_candidates)
                emails_skipped += 1
                continue

            tasks_created += sum(1 for result in sync_results if result.success and result.google_task_id)
            tasks_updated += sum(
                1
                for result in sync_results
                if result.success and result.google_task_id and result.local_task_id is not None
            )
            tasks_failed += sum(1 for result in sync_results if not result.success)

            if not self._is_successful_sync(sync_results):
                failures.append(
                    EmailFailureDetail(
                        gmail_message_id=email.gmail_message_id,
                        subject=email.subject,
                        stage="act",
                        error_message="One or more task synchronizations failed.",
                    )
                )
                emails_skipped += 1
                continue

            try:
                self._verify(email)
            except Exception as exc:  # noqa: BLE001 - error recorded in execution summary
                failures.append(
                    EmailFailureDetail(
                        gmail_message_id=email.gmail_message_id,
                        subject=email.subject,
                        stage="verify",
                        error_message=str(exc),
                    )
                )
                emails_skipped += 1
                continue

            emails_processed += 1

        finished_at = datetime.utcnow()
        execution_time_ms = int((perf_counter() - started_at_perf) * 1000)
        total_failures = len(failures) + tasks_failed
        execution_status = self._determine_execution_status(
            observe_failure=observe_failure,
            emails_processed=emails_processed,
            total_failures=total_failures,
            new_emails=new_emails,
            tasks_created=tasks_created,
            tasks_updated=tasks_updated,
        )

        result = AgentExecutionResult(
            started_at=started_at,
            finished_at=finished_at,
            emails_checked=emails_checked,
            new_emails=new_emails,
            emails_processed=emails_processed,
            emails_skipped=emails_skipped,
            tasks_created=tasks_created,
            tasks_updated=tasks_updated,
            tasks_failed=tasks_failed,
            total_failures=total_failures,
            execution_status=execution_status,
            execution_time_ms=execution_time_ms,
            failures=failures,
            observe_retry_count=observe_retry_count,
        )

        logger.info(
            "Execution Summary",
            extra={
                "execution_id": result.execution_id,
                "emails_checked": result.emails_checked,
                "emails_processed": result.emails_processed,
                "emails_skipped": result.emails_skipped,
                "tasks_failed": result.tasks_failed,
                "execution_status": result.execution_status,
                "execution_time_ms": result.execution_time_ms,
            },
        )
        return result

    def _observe(self) -> tuple[List[ParsedEmail], int, EmailFailureDetail | None]:
        """Load new emails with one retry for transient observe-stage failures."""
        logger.info("Observe Started", extra={"user_id": self.user_id})
        observe_retry_count = 0

        for attempt in range(2):
            try:
                emails = self.gmail_service.list_new_emails(
                    user_id=self.user_id,
                    max_results=self.max_emails_per_run,
                )
                logger.info(
                    "Observe Finished",
                    extra={"user_id": self.user_id, "new_email_count": len(emails), "attempt": attempt + 1},
                )
                return emails, observe_retry_count, None
            except Exception as exc:  # noqa: BLE001 - converted into typed execution detail
                if attempt == 0:
                    observe_retry_count += 1
                    logger.warning(
                        "Observe retry triggered after failure.",
                        extra={"user_id": self.user_id, "attempt": attempt + 1},
                        exc_info=True,
                    )
                    continue

                logger.error(
                    "Observe Finished with failure.",
                    extra={"user_id": self.user_id},
                    exc_info=True,
                )
                return (
                    [],
                    observe_retry_count,
                    EmailFailureDetail(
                        gmail_message_id="observe",
                        subject="",
                        stage="observe",
                        error_message=str(exc),
                    ),
                )

        return [], observe_retry_count, None

    def _reason(self, email: ParsedEmail) -> List[TaskCandidate]:
        """Run the reasoning stage by sending a parsed email to Gemini."""
        logger.info(
            "Reason Started",
            extra={"gmail_message_id": email.gmail_message_id, "subject": email.subject},
        )
        task_candidates = self.gemini_service.extract_tasks(email)
        logger.info(
            "Reason Finished",
            extra={"gmail_message_id": email.gmail_message_id, "task_candidate_count": len(task_candidates)},
        )
        return task_candidates

    def _act(self, task_candidates: Sequence[TaskCandidate]) -> List[TaskSyncResult]:
        """Run the action stage by synchronizing task candidates to Google Tasks."""
        logger.info(
            "Act Started",
            extra={"user_id": self.user_id, "task_candidate_count": len(task_candidates)},
        )
        sync_results = self.google_tasks_service.sync_tasks(self.user_id, task_candidates)
        logger.info(
            "Act Finished",
            extra={
                "user_id": self.user_id,
                "sync_result_count": len(sync_results),
                "success_count": sum(1 for result in sync_results if result.success),
            },
        )
        return sync_results

    def _verify(self, email: ParsedEmail) -> None:
        """Mark a Gmail message as processed only after successful synchronization."""
        logger.info(
            "Verify Started",
            extra={"gmail_message_id": email.gmail_message_id, "subject": email.subject},
        )
        self.gmail_service.mark_email_processed(self.user_id, email)
        logger.info(
            "Verify Finished",
            extra={"gmail_message_id": email.gmail_message_id, "subject": email.subject},
        )

    @staticmethod
    def _is_successful_sync(sync_results: Sequence[TaskSyncResult]) -> bool:
        """Return True only when every task sync result succeeded."""
        return bool(sync_results) and all(result.success for result in sync_results)

    @staticmethod
    def _determine_execution_status(
        observe_failure: EmailFailureDetail | None,
        emails_processed: int,
        total_failures: int,
        new_emails: int,
        tasks_created: int,
        tasks_updated: int,
    ) -> str:
        """Summarize the overall agent run outcome."""
        if observe_failure is not None and emails_processed == 0:
            return "failed"
        if total_failures > 0:
            made_progress = emails_processed > 0 or tasks_created > 0 or tasks_updated > 0 or new_emails == 0
            return "partial_success" if made_progress else "failed"
        return "success"
