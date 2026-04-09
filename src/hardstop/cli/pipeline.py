"""Core pipeline CLI commands: fetch, ingest-external, run."""

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hardstop.api.brief_api import _parse_since
from hardstop.config.loader import (
    get_all_sources,
    load_config,
    load_sources_config,
    load_suppression_config,
)
from hardstop.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_event_external_fields,
    ensure_raw_items_table,
    ensure_source_runs_table,
    ensure_suppression_columns,
    ensure_trust_tier_columns,
)
from hardstop.database.raw_item_repo import save_raw_item
from hardstop.database.schema import SourceRun
from hardstop.database.source_run_repo import create_source_run, get_all_source_health, list_recent_runs
from hardstop.database.sqlite_client import session_context
from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    fingerprint_config,
    resolve_config_snapshot,
)
from hardstop.ops.run_status import evaluate_run_status
from hardstop.retrieval.fetcher import FetchResult, SourceFetcher
from hardstop.runners.ingest_external import main as ingest_external_main
from hardstop.utils.logging import get_logger

from ._helpers import (
    _derive_seed,
    _hash_parts,
    _log_run_record_failure,
    _resolve_source_defaults,
    _run_group_ref,
    _safe_raw_batch_hash,
    _safe_source_runs_hash,
)

logger = get_logger(__name__)


def cmd_fetch(args: argparse.Namespace, run_group_id: Optional[str] = None) -> None:
    """Fetch items from external sources."""

    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    config_snapshot = resolve_config_snapshot()
    started_at = datetime.now(timezone.utc).isoformat()
    mode = "strict" if getattr(args, "strict", False) else "best-effort"
    output_refs: List[ArtifactRef] = []
    errors: List[Diagnostic] = []
    best_effort_metadata: dict = {}

    if run_group_id is None:
        run_group_id = str(uuid.uuid4())
    input_refs: List[ArtifactRef] = [
        _run_group_ref(run_group_id),
        ArtifactRef(
            id=f"fetch-window:{args.since or 'all'}",
            hash=_hash_parts(str(args.since or "all")),
            kind="FetchWindow",
        ),
    ]
    results: List[FetchResult] = []
    total_fetched = 0
    total_stored = 0

    from hardstop.database.sqlite_client import get_engine
    get_engine(sqlite_path)

    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)
    ensure_source_runs_table(sqlite_path)

    rng_seed = _derive_seed(run_group_id)
    fetcher = SourceFetcher(strict=mode == "strict", rng_seed=rng_seed)

    since_hours = None
    if args.since:
        since_str = args.since.lower().strip()
        if since_str.endswith("h"):
            since_hours = int(since_str[:-1])
        elif since_str.endswith("d"):
            since_hours = int(since_str[:-1]) * 24

    try:
        if args.dry_run:
            print("DRY RUN: Would fetch from sources (no changes will be made)")
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            tier_filter = args.tier
            enabled_only = args.enabled_only

            filtered = []
            for source in all_sources:
                if tier_filter and source.get("tier") != tier_filter:
                    continue
                if enabled_only and not source.get("enabled", True):
                    continue
                filtered.append(source)

            print(f"Would fetch from {len(filtered)} sources:")
            for source in filtered:
                print(f"  - {source['id']} ({source.get('tier', 'unknown')} tier)")
            raw_batch_hash = _hash_parts("dry-run", str(len(filtered)))
            source_runs_hash = _hash_parts(run_group_id, "dry-run", str(len(filtered)))
            output_refs = [
                ArtifactRef(
                    id=f"raw-items:{run_group_id}",
                    hash=raw_batch_hash,
                    kind="RawItemBatch",
                ),
                ArtifactRef(
                    id=f"source-runs:fetch:{run_group_id}",
                    hash=source_runs_hash,
                    kind="SourceRun",
                ),
            ]
        else:
            results = fetcher.fetch_all(
                tier=args.tier,
                enabled_only=args.enabled_only,
                max_items_per_source=args.max_items_per_source,
                since=args.since,
                fail_fast=args.fail_fast,
            )

            with session_context(sqlite_path) as session:
                sources_config = load_sources_config()
                all_sources = {s["id"]: s for s in get_all_sources(sources_config)}

                for result in results:
                    source_id = result.source_id
                    candidates = result.items

                    source_config_raw = all_sources.get(source_id, {})
                    source_config = _resolve_source_defaults(source_config_raw, sources_config)
                    tier = source_config.get("tier", "unknown")
                    trust_tier = source_config.get("trust_tier", 2)

                    items_new = 0

                    for candidate in candidates:
                        try:
                            candidate_dict = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate

                            raw_item = save_raw_item(
                                session,
                                source_id=source_id,
                                tier=tier,
                                candidate=candidate_dict,
                                trust_tier=trust_tier,
                            )

                            if raw_item in session.new or raw_item.status == "NEW":
                                items_new += 1
                                total_stored += 1
                        except Exception as e:
                            logger.error("Failed to save raw item from %s: %s", source_id, e)

                    total_fetched += len(candidates)
                    logger.info("Fetched %s items from %s, %s new", len(candidates), source_id, items_new)

                    diagnostics_payload = {
                        "bytes_downloaded": getattr(result, "bytes_downloaded", 0) or 0,
                        "dedupe_dropped": max(len(candidates) - items_new, 0),
                        "items_seen": len(candidates),
                    }

                    create_source_run(
                        session,
                        run_group_id=run_group_id,
                        source_id=source_id,
                        phase="FETCH",
                        run_at_utc=result.fetched_at_utc,
                        status=result.status,
                        status_code=result.status_code,
                        error=result.error,
                        duration_seconds=result.duration_seconds,
                        items_fetched=len(candidates),
                        items_new=items_new,
                        diagnostics=diagnostics_payload,
                    )

                session.commit()

            print(f"Fetch complete: {total_fetched} items fetched, {total_stored} stored")
            raw_batch_hash = _safe_raw_batch_hash(
                sqlite_path,
                run_group_id,
                fallback_parts=(run_group_id, str(total_fetched), str(total_stored)),
            )
            source_runs_fallback = tuple(
                sorted(
                    f"{result.source_id}:{result.status}:{result.status_code or 0}"
                    for result in results
                )
            ) or ("none",)
            source_runs_hash = _safe_source_runs_hash(
                sqlite_path,
                run_group_id,
                phase="FETCH",
                fallback_parts=source_runs_fallback,
            )
            output_refs = [
                ArtifactRef(
                    id=f"raw-items:{run_group_id}",
                    hash=raw_batch_hash,
                    kind="RawItemBatch",
                ),
                ArtifactRef(
                    id=f"source-runs:fetch:{run_group_id}",
                    hash=source_runs_hash,
                    kind="SourceRun",
                ),
            ]
            best_effort_metadata = fetcher.best_effort_metadata()

    except Exception as e:
        logger.error("Error fetching: %s", e, exc_info=True)
        errors.append(Diagnostic(code="FETCH_ERROR", message=str(e)))
        raise
    finally:
        try:
            best_effort_metadata = best_effort_metadata or fetcher.best_effort_metadata()
            emit_run_record(
                operator_id="hardstop.fetch@1.0.0",
                mode=mode,
                config_snapshot=config_snapshot,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                input_refs=input_refs,
                output_refs=output_refs,
                errors=errors,
                best_effort=best_effort_metadata,
            )
        except Exception as record_error:
            _log_run_record_failure("fetch", record_error)


def cmd_ingest_external(args: argparse.Namespace, run_group_id: Optional[str] = None) -> None:
    """Ingest external raw items into events and alerts."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    config_snapshot = resolve_config_snapshot()
    started_at = datetime.now(timezone.utc).isoformat()
    mode = "strict" if getattr(args, "strict", False) else "best-effort"
    errors: List[Diagnostic] = []
    output_refs: List[ArtifactRef] = []

    if run_group_id is None:
        run_group_id = str(uuid.uuid4())
    raw_batch_hash = _safe_raw_batch_hash(
        sqlite_path,
        run_group_id,
        fallback_parts=(run_group_id, str(args.source_id or "all"), str(args.limit or "all")),
    )
    input_refs: List[ArtifactRef] = [
        _run_group_ref(run_group_id),
        ArtifactRef(
            id=f"raw-items:{run_group_id}",
            hash=raw_batch_hash,
            kind="RawItemBatch",
        ),
    ]

    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)
    ensure_suppression_columns(sqlite_path)
    ensure_source_runs_table(sqlite_path)

    min_tier = args.min_tier

    since_hours = None
    if args.since:
        try:
            since_hours = _parse_since(args.since)
        except ValueError:
            logger.warning("Invalid --since value: %s, ignoring", args.since)

    try:
        with session_context(sqlite_path) as session:
            stats = ingest_external_main(
                session=session,
                limit=args.limit,
                min_tier=min_tier,
                source_id=args.source_id,
                since_hours=since_hours,
                no_suppress=getattr(args, 'no_suppress', False),
                explain_suppress=getattr(args, 'explain_suppress', False),
                run_group_id=run_group_id,
                fail_fast=getattr(args, 'fail_fast', False),
                allow_ingest_errors=getattr(args, 'allow_ingest_errors', False),
            )

            print(f"Ingestion complete:")
            print(f"  Processed: {stats['processed']}")
            print(f"  Events: {stats['events']}")
            print(f"  Alerts: {stats['alerts']}")
            if stats.get('suppressed', 0) > 0:
                print(f"  Suppressed: {stats['suppressed']}")
            print(f"  Errors: {stats['errors']}")
        ingest_hash = _safe_source_runs_hash(
            sqlite_path,
            run_group_id,
            phase="INGEST",
            fallback_parts=(
                run_group_id,
                str(stats.get("processed", 0)),
                str(stats.get("events", 0)),
                str(stats.get("alerts", 0)),
                str(stats.get("errors", 0)),
            ),
        )
        output_refs = [
            ArtifactRef(
                id=f"source-runs:ingest:{run_group_id}",
                hash=ingest_hash,
                kind="SourceRun",
            )
        ]

    except Exception as e:
        logger.error("Error ingesting: %s", e, exc_info=True)
        errors.append(Diagnostic(code="INGEST_ERROR", message=str(e)))
        raise
    finally:
        try:
            emit_run_record(
                operator_id="hardstop.ingest@1.0.0",
                mode=mode,
                config_snapshot=config_snapshot,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                input_refs=input_refs,
                output_refs=output_refs,
                errors=errors,
            )
        except Exception as record_error:
            _log_run_record_failure("ingest", record_error)


def cmd_run(args: argparse.Namespace) -> None:
    """Convenience command: fetch -> ingest external -> brief -> evaluate status."""
    from hardstop.cli.output import cmd_brief

    since_str = args.since or "24h"
    stale_threshold = args.stale if hasattr(args, 'stale') else "48h"
    strict_mode = getattr(args, 'strict', False)

    run_group_id = str(uuid.uuid4())
    config_snapshot = resolve_config_snapshot()

    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")

    # Step 1: Fetch
    print("Step 1: Fetching from sources...")
    fetch_args = argparse.Namespace(
        tier=None,
        enabled_only=True,
        max_items_per_source=10,
        since=since_str,
        dry_run=False,
        fail_fast=False,
        strict=strict_mode,
    )
    try:
        cmd_fetch(fetch_args, run_group_id=run_group_id)
    except Exception as e:
        logger.error("Fetch failed: %s", e, exc_info=True)

    # Step 2: Ingest external
    print("\nStep 2: Ingesting external items...")
    ingest_args = argparse.Namespace(
        limit=200,
        min_tier=None,
        source_id=None,
        since=since_str,
        no_suppress=getattr(args, 'no_suppress', False),
        explain_suppress=False,
        fail_fast=getattr(args, 'fail_fast', False),
        strict=strict_mode,
        allow_ingest_errors=getattr(args, "allow_ingest_errors", False),
    )
    try:
        cmd_ingest_external(ingest_args, run_group_id=run_group_id)
    except Exception as e:
        logger.error("Ingest failed: %s", e, exc_info=True)

    # Step 3: Brief
    print("\nStep 3: Generating brief...")
    brief_args = argparse.Namespace(
        today=True,
        since=since_str,
        format="md",
        limit=20,
        include_class0=False,
        strict=strict_mode,
    )
    try:
        cmd_brief(brief_args, run_group_id=run_group_id)
    except Exception as e:
        logger.error("Brief failed: %s", e, exc_info=True)

    # Step 4: Evaluate run status
    print("\nStep 4: Evaluating run status...")

    fetch_results: Optional[List[FetchResult]] = None
    ingest_runs: Optional[List[SourceRun]] = None
    doctor_findings: Dict = {}
    stale_sources: List[str] = []

    try:
        with session_context(sqlite_path) as session:
            fetch_runs = list_recent_runs(session, limit=100, phase="FETCH")
            fetch_runs = [r for r in fetch_runs if r.run_group_id == run_group_id]

            fetch_results = []
            for run in fetch_runs:
                diagnostics = {}
                if run.diagnostics_json:
                    try:
                        diagnostics = json.loads(run.diagnostics_json)
                    except (json.JSONDecodeError, TypeError):
                        diagnostics = {}
                items_count = None
                for key in ("items_seen", "items_new"):
                    value = diagnostics.get(key)
                    if value is not None:
                        try:
                            items_count = int(value)
                            break
                        except (TypeError, ValueError):
                            continue
                if items_count is None:
                    for value in (run.items_fetched, run.items_new):
                        if value:
                            try:
                                items_count = int(value)
                                break
                            except (TypeError, ValueError):
                                continue
                fetch_results.append(
                    FetchResult(
                        source_id=run.source_id,
                        fetched_at_utc=run.run_at_utc,
                        status=run.status,
                        status_code=run.status_code,
                        error=run.error,
                        duration_seconds=run.duration_seconds,
                        items=[],
                        items_count=items_count,
                    )
                )

            ingest_runs = list_recent_runs(session, limit=100, phase="INGEST")
            ingest_runs = [r for r in ingest_runs if r.run_group_id == run_group_id]

            try:
                stale_hours_val = _parse_since(stale_threshold)
                if stale_hours_val:
                    stale_threshold_dt = datetime.now(timezone.utc) - timedelta(hours=stale_hours_val)
                    stale_threshold_iso = stale_threshold_dt.isoformat()
                    all_fetch_runs = list_recent_runs(session, limit=1000, phase="FETCH")
                    source_last_success = {}
                    for run in all_fetch_runs:
                        if run.status == "SUCCESS":
                            if run.source_id not in source_last_success:
                                source_last_success[run.source_id] = run.run_at_utc

                    for source_id, last_success_utc in source_last_success.items():
                        if last_success_utc < stale_threshold_iso:
                            stale_sources.append(source_id)
            except Exception as e:
                logger.warning("Error calculating stale sources: %s", e)
    except Exception as e:
        logger.error("Error collecting run data: %s", e, exc_info=True)

    # Run doctor checks for findings
    try:
        try:
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            enabled_sources = [s for s in all_sources if s.get("enabled", True)]
            doctor_findings["enabled_sources_count"] = len(enabled_sources)
        except FileNotFoundError:
            doctor_findings["config_error"] = "sources.yaml not found"
        except Exception as e:
            doctor_findings["config_error"] = f"Config parse error: {str(e)}"

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
                doctor_findings["suppression_warnings"] = suppression_warnings
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("Error checking suppression config: %s", e)

        try:
            stale_hours_value = _parse_since(stale_threshold) if stale_threshold else 48
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
                doctor_findings["health_budget_blockers"] = blocked
            if watch:
                doctor_findings["health_budget_warnings"] = watch
        except Exception as e:
            logger.warning("Error evaluating health budgets: %s", e)

        try:
            import sqlite3
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
                    doctor_findings["schema_drift"] = missing_tables
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Error checking schema: %s", e)
    except Exception as e:
        logger.warning("Error running doctor checks: %s", e)

    # Evaluate run status
    stale_hours = _parse_since(stale_threshold) if stale_threshold else 48
    exit_code, messages = evaluate_run_status(
        fetch_results=fetch_results,
        ingest_runs=ingest_runs,
        doctor_findings=doctor_findings,
        stale_sources=stale_sources,
        stale_threshold_hours=stale_hours or 48,
        strict=strict_mode,
    )

    # Print footer
    status_names = {0: "HEALTHY", 1: "WARNING", 2: "BROKEN"}
    status_name = status_names.get(exit_code, "UNKNOWN")
    print(f"\n{'=' * 50}")
    print(f"Run status: {status_name}")
    if messages:
        print("\nTop issues:")
        for msg in messages[:3]:
            print(f"  - {msg}")
    print(f"{'=' * 50}\n")

    try:
        diagnostics: List[Diagnostic] = [
            Diagnostic(code=f"RUN_STATUS::{exit_code}", message=msg)
            for msg in messages
        ]
        emit_run_record(
            operator_id="hardstop.run@1.0.0",
            mode="strict" if strict_mode else "best-effort",
            config_snapshot=config_snapshot,
            input_refs=[
                ArtifactRef(
                    id=f"run-group:{run_group_id}",
                    hash=hashlib.sha256(run_group_id.encode("utf-8")).hexdigest(),
                    kind="RunGroup",
                )
            ],
            output_refs=[
                ArtifactRef(
                    id=f"run-status:{run_group_id}",
                    hash=hashlib.sha256("||".join(messages).encode("utf-8")).hexdigest(),
                    kind="RunStatus",
                )
            ],
            warnings=diagnostics if exit_code == 1 else [],
            errors=diagnostics if exit_code == 2 else [],
        )
    except Exception as record_error:
        _log_run_record_failure("run-status", record_error)

    sys.exit(exit_code)
