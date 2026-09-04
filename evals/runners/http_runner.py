"""HTTP eval runner — executes dataset cases against the FastAPI app."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from app.agent.state import get_state_store
from app.config import Settings, get_settings
from app.main import create_app
from app.models.planning import PlanStatus
from evals.datasets.loader import load_all_cases, load_dataset
from evals.datasets.models import EvalAction, EvalCase, EvalCategory, ExpectedOutcome
from evals.runners.results import EvalCaseResult, EvalRunSummary, EvalTurnResult

if TYPE_CHECKING:
    from app.agent.state import AgentState


def _booking_count(db_path: str) -> int:
    if not Path(db_path).exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        try:
            return int(conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _response_message(body: dict[str, object], http_status: int) -> str:
    if http_status >= 400:
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    message = body.get("message")
    return message if isinstance(message, str) else str(message or "")


def _observe_outcome(
    *,
    state: AgentState | None,
    last_status: int,
    last_turn: EvalTurnResult,
) -> ExpectedOutcome:
    if last_status in {400, 422, 429}:
        return ExpectedOutcome.BLOCKED

    if state is None:
        return ExpectedOutcome.BLOCKED if last_status >= 400 else ExpectedOutcome.FAILED

    if state.pending_question:
        return ExpectedOutcome.ASK_USER

    if state.pending_approval is not None:
        return ExpectedOutcome.PENDING_APPROVAL

    if last_turn.action == EvalAction.CANCEL and last_turn.success is True:
        return ExpectedOutcome.CANCELLED

    if state.plan.status == PlanStatus.FAILED:
        return ExpectedOutcome.FAILED

    if state.booking.booking_id and state.plan.status == PlanStatus.COMPLETED:
        return ExpectedOutcome.COMPLETED

    if state.plan.status == PlanStatus.COMPLETED and state.booking.booking_id is None:
        return ExpectedOutcome.CANCELLED

    if state.plan.status == PlanStatus.IN_PROGRESS:
        return ExpectedOutcome.PENDING_APPROVAL

    return ExpectedOutcome.FAILED


def _check_expectations(
    case: EvalCase,
    *,
    last_status: int,
    last_message: str,
    state: AgentState | None,
    booking_count: int,
    observed_outcome: ExpectedOutcome,
    pending_approval_present: bool | None,
) -> list[str]:
    expected = case.expectations
    failures: list[str] = []

    if last_status != expected.http_status:
        failures.append(
            f"expected http_status {expected.http_status}, got {last_status}",
        )

    if observed_outcome != expected.outcome:
        failures.append(
            f"expected outcome {expected.outcome.value}, observed {observed_outcome.value}",
        )

    for fragment in expected.message_contains:
        if fragment not in last_message:
            failures.append(f"expected message to contain {fragment!r}")

    for fragment in expected.message_not_contains:
        if fragment in last_message:
            failures.append(f"expected message not to contain {fragment!r}")

    if expected.pending_approval is not None:
        if state is not None:
            actual_pending = state.pending_approval is not None
        elif last_status >= 400:
            actual_pending = False
        else:
            actual_pending = bool(pending_approval_present)
        if actual_pending != expected.pending_approval:
            failures.append(
                f"expected pending_approval={expected.pending_approval}, "
                f"got {actual_pending}",
            )

    if expected.plan_status is not None:
        actual_plan_status = state.plan.status.value if state is not None else None
        if actual_plan_status != expected.plan_status:
            failures.append(
                f"expected plan_status {expected.plan_status!r}, got {actual_plan_status!r}",
            )

    if expected.booking_created is not None:
        if state is not None:
            booking_created = state.booking.booking_id is not None
        else:
            booking_created = booking_count > 0
        if booking_created != expected.booking_created:
            failures.append(
                f"expected booking_created={expected.booking_created}, got {booking_created}",
            )

    return failures


def _case_booking_db_path(
    case: EvalCase,
    booking_db_path: str | Path | None,
) -> Path | None:
    if booking_db_path is None:
        return None
    root = Path(booking_db_path)
    if root.suffix == ".db":
        return root.with_name(f"{case.id}.db")
    return root / f"{case.id}.db"


class EvalHttpRunner:
    """Execute eval cases through HTTP endpoints with isolated mock settings."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        booking_db_path: str | Path | None = None,
    ) -> None:
        resolved_settings = (settings or Settings(
            flight_api_use_mock=True,
            planner_use_mock=True,
        )).model_copy(update={"rate_limit_enabled": False})
        if booking_db_path is not None:
            resolved_settings = resolved_settings.model_copy(
                update={"booking_db_path": str(booking_db_path)},
            )
        self.settings = resolved_settings
        self._sync_runtime_settings(resolved_settings)
        self.client = TestClient(create_app(self.settings))

    @staticmethod
    def _sync_runtime_settings(settings: Settings) -> None:
        """Align process settings with the runner's isolated booking store."""
        import os

        os.environ["BOOKING_DB_PATH"] = settings.booking_db_path
        get_settings.cache_clear()
        from app.agent.workers import reset_worker_registry
        from app.tools.adapters import clear_tool_adapter_cache

        clear_tool_adapter_cache()
        reset_worker_registry()

    def run_case(self, case: EvalCase, *, category: EvalCategory | None = None) -> EvalCaseResult:
        conversation_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
        turn_results: list[EvalTurnResult] = []
        last_status = 500
        last_message = ""
        last_body: dict[str, object] = {}
        pending_approval_present: bool | None = None

        for turn in case.turns:
            if turn.action == EvalAction.CHAT:
                response = self.client.post(
                    "/chat",
                    json={"message": turn.message, "conversation_id": conversation_id},
                )
            elif turn.action == EvalAction.CONFIRM:
                response = self.client.post(
                    "/approvals/confirm",
                    json={"conversation_id": conversation_id},
                )
            else:
                response = self.client.post(
                    "/approvals/cancel",
                    json={"conversation_id": conversation_id},
                )

            last_status = response.status_code
            last_body = response.json()
            last_message = _response_message(last_body, last_status)
            success_value = last_body.get("success")
            success = success_value if isinstance(success_value, bool) else None
            if turn.action == EvalAction.CHAT and last_status < 400:
                pending_approval_present = last_body.get("pending_approval") is not None

            turn_results.append(
                EvalTurnResult(
                    action=turn.action,
                    http_status=last_status,
                    message=last_message,
                    success=success,
                ),
            )

        state = get_state_store().get(conversation_id)
        observed_outcome = _observe_outcome(
            state=state,
            last_status=last_status,
            last_turn=turn_results[-1],
        )
        booking_count = _booking_count(self.settings.booking_db_path)
        failures = _check_expectations(
            case,
            last_status=last_status,
            last_message=last_message,
            state=state,
            booking_count=booking_count,
            observed_outcome=observed_outcome,
            pending_approval_present=pending_approval_present,
        )

        result = EvalCaseResult(
            case_id=case.id,
            category=category,
            passed=not failures,
            failures=failures,
            turns=turn_results,
            conversation_id=conversation_id,
            observed_outcome=observed_outcome,
        )
        from evals.metrics.scoring import score_case

        return result.model_copy(update={"metrics": score_case(case, result, state)})


def run_eval_case(
    case: EvalCase,
    *,
    category: EvalCategory | None = None,
    booking_db_path: str | Path | None = None,
    settings: Settings | None = None,
) -> EvalCaseResult:
    """Run one eval case in an isolated runner instance."""
    runner = EvalHttpRunner(
        settings=settings,
        booking_db_path=_case_booking_db_path(case, booking_db_path),
    )
    return runner.run_case(case, category=category)


def run_eval_cases(
    cases: list[EvalCase],
    *,
    category: EvalCategory | None = None,
    booking_db_path: str | Path | None = None,
    settings: Settings | None = None,
) -> EvalRunSummary:
    """Run a list of eval cases sequentially."""
    results = [
        run_eval_case(
            case,
            category=category,
            booking_db_path=booking_db_path,
            settings=settings,
        )
        for case in cases
    ]
    passed = sum(1 for result in results if result.passed)
    summary = EvalRunSummary(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )
    from evals.metrics.scoring import score_results

    return summary.model_copy(
        update={"metrics": score_results(cases, summary)},
    )


def run_category_evals(
    category: EvalCategory,
    *,
    booking_db_path: str | Path | None = None,
    settings: Settings | None = None,
) -> EvalRunSummary:
    """Run all cases from one dataset category."""
    dataset = load_dataset(category)
    return run_eval_cases(
        dataset.cases,
        category=category,
        booking_db_path=booking_db_path,
        settings=settings,
    )


def run_all_evals(
    *,
    booking_db_path: str | Path | None = None,
    settings: Settings | None = None,
) -> EvalRunSummary:
    """Run every registered eval case."""
    results: list[EvalCaseResult] = []
    cases: list[EvalCase] = []
    for category in EvalCategory:
        dataset = load_dataset(category)
        for case in dataset.cases:
            cases.append(case)
            results.append(
                run_eval_case(
                    case,
                    category=category,
                    booking_db_path=booking_db_path,
                    settings=settings,
                ),
            )

    passed = sum(1 for result in results if result.passed)
    summary = EvalRunSummary(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )
    from evals.metrics.scoring import score_results

    return summary.model_copy(
        update={"metrics": score_results(cases, summary)},
    )
