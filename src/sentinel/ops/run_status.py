"""Run status evaluation for exit codes (v1.0)."""

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sentinel.database.schema import SourceRun
from sentinel.retrieval.fetcher import FetchResult


def evaluate_run_status(
    *,
    fetch_results: Optional[List[FetchResult]] = None,
    ingest_runs: Optional[List[SourceRun]] = None,
    doctor_findings: Optional[Dict] = None,
    stale_sources: Optional[List[str]] = None,
    stale_threshold_hours: int = 48,
    strict: bool = False,
) -> Tuple[int, List[str]]:
    """
    Evaluate run status and return exit code with messages.
    
    Args:
        fetch_results: List of FetchResult objects from fetch operation
        ingest_runs: List of SourceRun objects from ingest operation (INGEST phase)
        doctor_findings: Dict with doctor check results (issues, warnings, etc.)
        stale_sources: List of source IDs that are stale
        stale_threshold_hours: Hours threshold for stale detection (default 48)
        strict: If True, treat warnings as broken (exit code 2)
        
    Returns:
        Tuple of (exit_code, messages)
        - exit_code: 0=Healthy, 1=Warning, 2=Broken
        - messages: List of status messages (top 1-3 for display)
    """
    messages: List[str] = []
    exit_code = 0  # Start healthy
    
    doctor_findings = doctor_findings or {}
    stale_sources = stale_sources or []
    fetch_results = fetch_results or []
    ingest_runs_provided = ingest_runs
    ingest_runs = ingest_runs or []
    ingest_data_available = ingest_runs_provided is not None
    
    # Check for BROKEN conditions (exit code 2)
    
    # 1. Config parse error
    if doctor_findings.get("config_error"):
        messages.append(f"Config error: {doctor_findings['config_error']}")
        return (2, messages)
    
    # 2. Schema drift detected
    if doctor_findings.get("schema_drift"):
        messages.append(f"Schema drift: {doctor_findings['schema_drift']}")
        return (2, messages)
    
    # 3. Zero sources enabled
    enabled_count = doctor_findings.get("enabled_sources_count", 0)
    if enabled_count == 0:
        messages.append("No enabled sources configured")
        return (2, messages)
    
    # 5. Failure budget blockers from health scoring
    health_blockers = doctor_findings.get("health_budget_blockers") or []
    if health_blockers:
        messages.append(f"{len(health_blockers)} source(s) exhausted failure budget")
        return (2, messages)
    
    # 4. All enabled sources failed fetch (no successes) AND none fetched quietly
    if fetch_results:
        successful_fetches = [r for r in fetch_results if r.status == "SUCCESS"]
        failed_fetches = [r for r in fetch_results if r.status == "FAILURE"]
        quiet_successes = [r for r in successful_fetches if len(r.items) == 0]
        
        if len(successful_fetches) == 0 and len(failed_fetches) > 0:
            # All failed, no quiet successes
            messages.append(f"All {len(failed_fetches)} sources failed to fetch")
            return (2, messages)
    
    # 5. Ingest crashed before processing any source
    # Check if we have items to ingest but no ingest runs
    if fetch_results and ingest_data_available and not ingest_runs:
        successful_fetches_with_items = [r for r in fetch_results if r.status == "SUCCESS" and len(r.items) > 0]
        if successful_fetches_with_items:
            # We have items to ingest but no ingest runs - likely a crash
            messages.append("Ingest crashed before processing any source")
            return (2, messages)
    
    # Check for WARNING conditions (exit code 1)
    warning_messages: List[str] = []
    ingest_error_runs: List[SourceRun] = []
    ingest_error_total = 0

    def _get_ingest_error_count(run: SourceRun) -> int:
        diagnostics_json = getattr(run, "diagnostics_json", None)
        if not diagnostics_json:
            return 0
        try:
            diagnostics = json.loads(diagnostics_json)
        except (json.JSONDecodeError, TypeError):
            return 0
        errors = diagnostics.get("errors")
        if errors is None:
            return 0
        try:
            return int(errors)
        except (TypeError, ValueError):
            return 0
    
    # 1. Some enabled sources failed fetch
    if fetch_results:
        failed_fetches = [r for r in fetch_results if r.status == "FAILURE"]
        if failed_fetches:
            warning_messages.append(f"{len(failed_fetches)} source(s) failed to fetch")
    
    # 2. Some enabled sources are stale
    if stale_sources:
        warning_messages.append(f"{len(stale_sources)} source(s) stale (no success in {stale_threshold_hours}h)")
    
    # 3. Ingest failure for one or more sources
    if ingest_runs:
        failed_ingests = [r for r in ingest_runs if r.status == "FAILURE"]
        if failed_ingests:
            warning_messages.append(f"{len(failed_ingests)} source(s) failed during ingest")
        for run in ingest_runs:
            error_count = _get_ingest_error_count(run)
            if error_count > 0:
                ingest_error_runs.append(run)
                ingest_error_total += error_count
        if ingest_error_runs:
            warning_messages.append(
                f"{len(ingest_error_runs)} source(s) had ingest errors ({ingest_error_total} total)"
            )
    
    # 4. Suppression config warnings (optional)
    if doctor_findings.get("suppression_warnings"):
        for warning in doctor_findings["suppression_warnings"]:
            warning_messages.append(f"Suppression: {warning}")
    
    health_watch = doctor_findings.get("health_budget_warnings") or []
    if health_watch:
        warning_messages.append(f"{len(health_watch)} source(s) near failure budget")
    
    # If we have warnings, set exit code to 1 (unless strict mode)
    if warning_messages:
        messages.extend(warning_messages[:3])  # Top 3 warnings
        exit_code = 2 if strict else 1
    
    # HEALTHY (exit code 0) if we get here and no warnings
    if exit_code == 0:
        # Verify we have at least one success
        if fetch_results:
            successful_fetches = [r for r in fetch_results if r.status == "SUCCESS"]
            quiet_successes = [r for r in successful_fetches if len(r.items) == 0]
            if successful_fetches:
                messages.append("All systems healthy")
            else:
                # This shouldn't happen if broken checks passed, but be safe
                messages.append("No successful fetches")
                exit_code = 1
        else:
            # No fetch results - can't determine health
            messages.append("No fetch results available")
            exit_code = 1
    
    return (exit_code, messages)
