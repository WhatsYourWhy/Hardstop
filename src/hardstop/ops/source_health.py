"""Source health scoring helpers (P1 execution)."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class HealthScoreResult:
    """Represents the derived health state for a source."""

    score: int
    budget_state: str  # HEALTHY | WATCH | BLOCKED
    factors: List[str]


def compute_health_score(
    metrics: Dict[str, Any],
    *,
    stale_threshold_hours: int,
) -> HealthScoreResult:
    """
    Compute a bounded (0-100) health score plus failure-budget state.

    Args:
        metrics: Dict from source_run_repo.get_source_health
        stale_threshold_hours: Stale window configured by CLI/user

    Returns:
        HealthScoreResult with score, budget_state, and contributing factors.
    """

    score = 100
    factors: List[str] = []

    def _deduct(amount: int, reason: str) -> None:
        nonlocal score
        if amount <= 0:
            return
        score -= amount
        factors.append(reason)

    success_rate = float(metrics.get("success_rate", 0.0) or 0.0)
    if success_rate < 0.25:
        _deduct(50, "success_rate<25%")
    elif success_rate < 0.5:
        _deduct(35, "success_rate<50%")
    elif success_rate < 0.7:
        _deduct(20, "success_rate<70%")
    elif success_rate < 0.9:
        _deduct(10, "success_rate<90%")

    stale_hours: Optional[float] = metrics.get("stale_hours")
    if stale_hours is None:
        _deduct(15, "no_success_history")
    else:
        if stale_hours > stale_threshold_hours:
            _deduct(25, "stale_over_threshold")
        elif stale_hours > stale_threshold_hours / 2:
            _deduct(10, "stale_trending")

    consecutive_failures = int(metrics.get("consecutive_failures", 0) or 0)
    if consecutive_failures >= 3:
        _deduct(25, "failure_streak>=3")
    elif consecutive_failures == 2:
        _deduct(10, "failure_streak_two")

    status_code = metrics.get("last_status_code")
    if isinstance(status_code, int):
        if status_code >= 500:
            _deduct(20, "last_status_5xx")
        elif status_code >= 400:
            _deduct(10, "last_status_4xx")

    if metrics.get("last_error"):
        _deduct(10, "recent_error")

    avg_bytes = metrics.get("avg_bytes_downloaded")
    if avg_bytes is not None:
        if avg_bytes == 0:
            _deduct(5, "zero_bytes")
        elif avg_bytes < 500:
            _deduct(3, "tiny_payloads")

    dedupe_rate = metrics.get("dedupe_rate")
    if dedupe_rate is not None and dedupe_rate > 0.9:
        _deduct(5, "dedupe>90%")

    suppression_ratio = metrics.get("suppression_ratio")
    if suppression_ratio is not None:
        if suppression_ratio > 0.85:
            _deduct(10, "suppression>85%")
        elif suppression_ratio > 0.6:
            _deduct(5, "suppression>60%")

    latency = metrics.get("avg_duration_seconds")
    if latency is not None and latency > 15:
        _deduct(5, "slow_fetch>15s")

    score = max(0, min(100, score))

    if score >= 80:
        budget_state = "HEALTHY"
    elif score >= 50:
        budget_state = "WATCH"
    else:
        budget_state = "BLOCKED"

    return HealthScoreResult(score=score, budget_state=budget_state, factors=factors)
