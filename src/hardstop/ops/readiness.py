"""
Pre-publication readiness evaluation (v1.3).

Hardstop historically evaluated source and run health only *after* the brief
had already been generated and printed, so a run with a blocked source could
publish an authoritative brief and only afterwards exit non-zero. This module
extracts the doctor-style checks so they can also run before publication.

The checks here are a verbatim extraction of the doctor block that used to
live inline in ``cli.pipeline.cmd_run``; ``findings`` keeps the exact dict
shape that ``ops.run_status.evaluate_run_status`` expects for its
``doctor_findings`` argument. Evaluation is read-only and idempotent.

This module deliberately does not gate alert creation. Alerts are still built
and committed exactly as in v1.x, including from BLOCKED sources; only
publication of briefs and exports is affected.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from hardstop.config.loader import (
    get_all_sources,
    load_sources_config,
    load_suppression_config,
)
from hardstop.database.source_run_repo import get_all_source_health
from hardstop.database.sqlite_client import session_context
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)

READY = "READY"
DEGRADED = "DEGRADED"
BROKEN = "BROKEN"


@dataclass
class ReadinessResult:
    """Outcome of a pre-publication readiness check."""

    state: str
    findings: Dict[str, Any] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_publishable(self) -> bool:
        """True when nothing blocks authoritative publication."""
        return self.state != BROKEN


def _parse_since_default(value: str) -> Optional[int]:
    from hardstop.cli._helpers import _parse_since

    return _parse_since(value)


def evaluate_readiness(
    sqlite_path: str,
    *,
    stale_threshold: Optional[str] = "48h",
    load_sources_config=load_sources_config,
    get_all_sources=get_all_sources,
    load_suppression_config=load_suppression_config,
    get_all_source_health=get_all_source_health,
    session_context=session_context,
    parse_since=_parse_since_default,
) -> ReadinessResult:
    """
    Evaluate whether this run is fit to publish authoritative output.

    The collaborators are injectable keyword arguments so that callers can pass
    their own module-level names. ``cmd_run`` relies on this: its tests
    monkeypatch ``load_sources_config``/``session_context``/etc. on the
    pipeline module, and passing them explicitly keeps those patches effective.

    Args:
        sqlite_path: Path to the SQLite database
        stale_threshold: Staleness window (e.g. "48h") used for health lookback

    Returns:
        ReadinessResult with a state, the raw doctor findings, and
        human-readable blocker/warning messages.
    """
    findings: Dict[str, Any] = {}

    try:
        try:
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            enabled_sources = [s for s in all_sources if s.get("enabled", True)]
            findings["enabled_sources_count"] = len(enabled_sources)
        except FileNotFoundError:
            findings["config_error"] = "sources.yaml not found"
        except Exception as e:
            findings["config_error"] = f"Config parse error: {str(e)}"

        try:
            suppression_config = load_suppression_config()
            suppression_warnings = []
            if not suppression_config.get("enabled", True):
                suppression_warnings.append("Suppression disabled")
            rules = suppression_config.get("rules", [])
            rule_ids = [r.get("id") for r in rules if isinstance(r, dict) and r.get("id")]
            if len(rule_ids) != len(set(rule_ids)):
                suppression_warnings.append("Duplicate rule IDs found")
            if suppression_warnings:
                findings["suppression_warnings"] = suppression_warnings
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("Error checking suppression config: %s", e)

        try:
            stale_hours_value = parse_since(stale_threshold) if stale_threshold else 48
            if stale_hours_value is None:
                stale_hours_value = 48
            with session_context(sqlite_path) as session:
                health_list = get_all_source_health(
                    session,
                    lookback_n=10,
                    stale_threshold_hours=stale_hours_value,
                )
            blocked = [h["source_id"] for h in health_list if h.get("health_budget_state") == "BLOCKED"]
            watch = [h["source_id"] for h in health_list if h.get("health_budget_state") == "WATCH"]
            if blocked:
                findings["health_budget_blockers"] = blocked
            if watch:
                findings["health_budget_warnings"] = watch
        except Exception as e:
            logger.warning("Error evaluating health budgets: %s", e)

        try:
            conn = sqlite3.connect(sqlite_path)
            try:
                required_tables = ["raw_items", "events", "alerts", "source_runs"]
                missing_tables = []
                for table in required_tables:
                    cur = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
                        (table,)
                    )
                    if not cur.fetchone():
                        missing_tables.append(f"table: {table}")
                if missing_tables:
                    findings["schema_drift"] = missing_tables
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Error checking schema: %s", e)
    except Exception as e:
        logger.warning("Error running doctor checks: %s", e)

    return _classify(findings)


def _classify(findings: Dict[str, Any]) -> ReadinessResult:
    """
    Derive a readiness state from doctor findings.

    Mirrors the doctor-driven BROKEN conditions in
    ``ops.run_status.evaluate_run_status`` so that a run which will exit 2 for
    a doctor reason does not publish an authoritative brief first. Fetch- and
    ingest-driven BROKEN conditions stay in run_status; they are evaluated from
    data this function does not receive.
    """
    blockers: List[str] = []
    warnings: List[str] = []

    if findings.get("config_error"):
        blockers.append(f"Config error: {findings['config_error']}")

    if findings.get("schema_drift"):
        drift = findings["schema_drift"]
        blockers.append(f"Schema drift detected: {', '.join(drift)}")

    if findings.get("enabled_sources_count") == 0:
        blockers.append("No sources enabled")

    if findings.get("health_budget_blockers"):
        blocked = findings["health_budget_blockers"]
        blockers.append(
            f"{len(blocked)} source(s) exhausted failure budget: {', '.join(blocked)}"
        )

    if findings.get("suppression_warnings"):
        warnings.extend(findings["suppression_warnings"])

    if findings.get("health_budget_warnings"):
        watch = findings["health_budget_warnings"]
        warnings.append(f"{len(watch)} source(s) on WATCH: {', '.join(watch)}")

    if blockers:
        state = BROKEN
    elif warnings:
        state = DEGRADED
    else:
        state = READY

    return ReadinessResult(
        state=state, findings=findings, blockers=blockers, warnings=warnings
    )


__all__ = ["BROKEN", "DEGRADED", "READY", "ReadinessResult", "evaluate_readiness"]
