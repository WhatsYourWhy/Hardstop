"""CLI entrypoint for Hardstop agent."""

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from hardstop.config.loader import (
    get_all_sources,
    get_source_with_defaults,
    get_suppression_rules_for_source,
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
from hardstop.database.raw_item_repo import save_raw_item, summarize_suppression_reasons
from hardstop.database.schema import Alert, Event, RawItem, SourceRun
from hardstop.database.source_run_repo import create_source_run, get_all_source_health, list_recent_runs
from hardstop.database.sqlite_client import session_context
from hardstop.output.daily_brief import generate_brief, render_json, render_markdown
from hardstop.ops.artifacts import compute_raw_item_batch_digest, compute_source_runs_digest
from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    fingerprint_config,
    resolve_config_snapshot,
)
from hardstop.ops.run_status import evaluate_run_status
from hardstop.api.brief_api import _parse_since
from hardstop.retrieval.fetcher import FetchResult, SourceFetcher
from hardstop.runners.ingest_external import main as ingest_external_main
from hardstop.runners.load_network import main as load_network_main
from hardstop.runners.run_demo import main as run_demo_main
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_source_defaults(source_config_raw, sources_config):
    """
    Resolve source config defaults while remaining tolerant to patched helpers
    that only accept a single positional argument (e.g., during tests).
    """
    if not source_config_raw:
        return {}
    try:
        return get_source_with_defaults(source_config_raw, sources_config)
    except TypeError:
        return get_source_with_defaults(source_config_raw)


def _hash_parts(*parts: str) -> str:
    """Stable SHA-256 hash for artifact refs."""
    payload = "||".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _derive_seed(label: str) -> int:
    """Derive a deterministic seed from a stable label (e.g., run_group_id)."""
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _run_group_ref(run_group_id: str) -> ArtifactRef:
    return ArtifactRef(
        id=f"run-group:{run_group_id}",
        hash=_hash_parts(run_group_id),
        kind="RunGroup",
    )


def _log_run_record_failure(context: str, error: Exception) -> None:
    logger.warning("Failed to emit %s run record: %s", context, error)
    print(f"[hardstop] RunRecord emission failure ({context}): {error}", file=sys.stderr)


def _safe_raw_batch_hash(sqlite_path: str, run_group_id: str, fallback_parts: Iterable[str]) -> str:
    try:
        return compute_raw_item_batch_digest(sqlite_path, run_group_id)
    except Exception as exc:
        logger.debug("Falling back to legacy raw batch hash: %s", exc, exc_info=True)
        return _hash_parts(*fallback_parts)


def _safe_source_runs_hash(
    sqlite_path: str,
    run_group_id: str,
    *,
    phase: str,
    fallback_parts: Iterable[str],
) -> str:
    try:
        return compute_source_runs_digest(sqlite_path, run_group_id, phase)
    except Exception as exc:
        logger.debug("Falling back to legacy source-runs hash: %s", exc, exc_info=True)
        return _hash_parts(*fallback_parts)


def _load_run_records(run_records_dir: Path) -> List[dict]:
    records: List[dict] = []
    if not run_records_dir.exists():
        return records
    for path in sorted(run_records_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            records.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _find_incident_artifacts(
    incident_id: str,
    *,
    artifacts_dir: Path,
    correlation_key: Optional[str] = None,
) -> List[tuple[str, Path, dict]]:
    matches: List[tuple[str, Path, dict]] = []
    if not artifacts_dir.exists():
        return matches
    for path in artifacts_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        inputs = payload.get("inputs") or {}
        if inputs.get("alert_id") != incident_id:
            continue
        if correlation_key and payload.get("correlation_key") != correlation_key:
            continue
        generated_at = payload.get("generated_at_utc") or ""
        matches.append((generated_at, path, payload))
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches


def cmd_demo(args: argparse.Namespace) -> None:
    """Run the demo pipeline."""
    run_demo_main()


def cmd_incidents_replay(args: argparse.Namespace) -> dict:
    """Replay an incident by loading recorded evidence and RunRecords."""

    incident_id = args.incident_id
    correlation_key = getattr(args, "correlation_key", None)
    artifacts_dir = Path(getattr(args, "artifacts_dir", "output/incidents"))
    run_records_dir = Path(getattr(args, "records_dir", "run_records"))
    mode = "strict" if getattr(args, "strict", False) else "best-effort"
    started_at = datetime.now(timezone.utc).isoformat()

    config_snapshot = resolve_config_snapshot()
    config_hash = fingerprint_config(config_snapshot)
    warnings: List[Diagnostic] = []
    errors: List[Diagnostic] = []
    best_effort_meta: dict = {}
    input_refs: List[ArtifactRef] = []
    output_refs: List[ArtifactRef] = []

    artifact_payload = None
    artifact_path: Optional[Path] = None
    artifact_hash_value: Optional[str] = None
    matching_run_record: Optional[dict] = None
    replay_exception: Optional[Exception] = None

    try:
        matches = _find_incident_artifacts(
            incident_id,
            artifacts_dir=artifacts_dir,
            correlation_key=correlation_key,
        )
        if not matches:
            message = f"Incident evidence not found for {incident_id}"
            diag = Diagnostic(code="INCIDENT_ARTIFACT_MISSING", message=message)
            if mode == "strict":
                errors.append(diag)
                raise FileNotFoundError(message)
            warnings.append(diag)
            logger.warning(message)
        else:
            _, artifact_path, artifact_payload = matches[0]
            from hardstop.ops.run_record import artifact_hash as _artifact_hash  # Local import to avoid cycles

            artifact_hash_value = artifact_payload.get("artifact_hash") or _artifact_hash(
                {k: v for k, v in artifact_payload.items() if k != "artifact_hash"}
            )
            expected_hash = _artifact_hash({k: v for k, v in artifact_payload.items() if k != "artifact_hash"})
            if artifact_hash_value != expected_hash:
                message = (
                    f"Artifact hash mismatch for {incident_id}: stored={artifact_hash_value} expected={expected_hash}"
                )
                diag = Diagnostic(code="INCIDENT_ARTIFACT_MISMATCH", message=message)
                if mode == "strict":
                    errors.append(diag)
                    raise ValueError(message)
                warnings.append(diag)
                logger.warning(message)
            artifact_payload["artifact_hash"] = expected_hash

            bytes_len = len(json.dumps(artifact_payload, sort_keys=True).encode("utf-8"))
            incident_ref = ArtifactRef(
                id=f"incident:{incident_id}",
                hash=expected_hash,
                kind=artifact_payload.get("kind", "IncidentEvidence"),
                schema=artifact_payload.get("artifact_version"),
                bytes=bytes_len,
            )
            input_refs.append(incident_ref)
            output_refs.append(incident_ref)

        run_records = _load_run_records(run_records_dir)
        for record in run_records:
            for ref in record.get("output_refs", []):
                ref_hash = ref.get("hash")
                ref_id = ref.get("id", "")
                if artifact_hash_value and ref_hash == artifact_hash_value:
                    matching_run_record = record
                    break
                if incident_id in ref_id:
                    matching_run_record = record
                    break
            if matching_run_record:
                break

        if not matching_run_record:
            message = f"No RunRecord found for incident {incident_id}"
            diag = Diagnostic(code="RUN_RECORD_MISSING", message=message)
            if mode == "strict":
                errors.append(diag)
                raise FileNotFoundError(message)
            warnings.append(diag)
            logger.warning(message)
        else:
            if matching_run_record.get("config_hash") and matching_run_record["config_hash"] != config_hash:
                message = (
                    f"Config hash mismatch for incident {incident_id}: "
                    f"record={matching_run_record['config_hash']} current={config_hash}"
                )
                diag = Diagnostic(code="CONFIG_FINGERPRINT_MISMATCH", message=message)
                if mode == "strict":
                    errors.append(diag)
                    raise ValueError(message)
                warnings.append(diag)
                logger.warning(message)
    except Exception as exc:  # Capture for RunRecord emission while preserving failure
        replay_exception = exc
    finally:
        try:
            emit_run_record(
                operator_id="hardstop.incidents.replay@1.0.0",
                mode=mode,
                config_snapshot=config_snapshot,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                input_refs=input_refs,
                output_refs=output_refs,
                warnings=warnings,
                errors=errors,
                best_effort=best_effort_meta or None,
                dest_dir=run_records_dir,
            )
        except Exception as record_error:
            _log_run_record_failure("incidents.replay", record_error)

    if replay_exception:
        raise replay_exception

    result = {
        "incident_id": incident_id,
        "artifact_path": str(artifact_path) if artifact_path else None,
        "artifact_hash": artifact_hash_value,
        "config_hash": config_hash,
        "run_record_id": matching_run_record.get("run_id") if matching_run_record else None,
        "warnings": [w.message for w in warnings],
    }
    if getattr(args, "format", "json") == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Incident {incident_id}:")
        if artifact_path:
            print(f"  Artifact: {artifact_path}")
        if matching_run_record:
            print(f"  RunRecord: {matching_run_record.get('_path')}")
        if warnings:
            for warn in warnings:
                print(f"  WARN: {warn.message}")
    return result


def cmd_ingest(args: argparse.Namespace) -> None:
    """Load network data from CSV files."""
    load_network_main()


def cmd_sources_list(args: argparse.Namespace) -> None:
    """List configured sources."""
    try:
        sources_config = load_sources_config()
        all_sources = get_all_sources(sources_config)
        
        if not all_sources:
            print("No sources configured.")
            return
        
        print(f"{'ID':<30} {'Tier':<12} {'Enabled':<10} {'Type':<15} {'Tags':<30}")
        print("-" * 100)
        
        for source in all_sources:
            source_id = source.get("id", "unknown")
            tier = source.get("tier", "unknown")
            enabled = "Yes" if source.get("enabled", True) else "No"
            source_type = source.get("type", "unknown")
            tags = ", ".join(source.get("tags", []))
            
            print(f"{source_id:<30} {tier:<12} {enabled:<10} {source_type:<15} {tags:<30}")
    
    except FileNotFoundError as e:
        logger.error(f"Sources config not found: {e}")
        print("Error: Sources config file not found. Create config/sources.yaml")
    except Exception as e:
        logger.error(f"Error listing sources: {e}", exc_info=True)
        raise


def cmd_sources_test(args: argparse.Namespace) -> None:
    """Test a single source by fetching (and optionally ingesting)."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    
    # Generate run_group_id
    run_group_id = str(uuid.uuid4())
    
    # Ensure migrations
    from hardstop.database.sqlite_client import get_engine
    get_engine(sqlite_path)
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)
    ensure_source_runs_table(sqlite_path)
    
    # Create fetcher
    fetcher = SourceFetcher()
    
    # Fetch single source
    try:
        result = fetcher.fetch_one(
            source_id=args.source_id,
            since=args.since,
            max_items=args.max_items,
        )
        
        # Print fetch summary
        print(f"\nFetch Results for {args.source_id}:")
        print(f"  Status: {result.status}")
        if result.status_code:
            print(f"  HTTP Status: {result.status_code}")
        if result.duration_seconds:
            print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Items Fetched: {len(result.items)}")
        
        if result.status == "FAILURE":
            print(f"  Error: {result.error}")
            return
        
        # Save items to database
        sources_config = load_sources_config()
        all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
        source_config_raw = all_sources.get(args.source_id, {})
        source_config = _resolve_source_defaults(source_config_raw, sources_config)
        tier = source_config.get("tier", "unknown")
        trust_tier = source_config.get("trust_tier", 2)
        
        items_new = 0
        with session_context(sqlite_path) as session:
            for candidate in result.items:
                try:
                    candidate_dict = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate
                    raw_item = save_raw_item(
                        session,
                        source_id=args.source_id,
                        tier=tier,
                        candidate=candidate_dict,
                        trust_tier=trust_tier,
                    )
                    if raw_item in session.new or raw_item.status == "NEW":
                        items_new += 1
                except Exception as e:
                    logger.error(f"Failed to save raw item: {e}")
            
            # Create FETCH SourceRun record
            diagnostics_payload = {
                "bytes_downloaded": getattr(result, "bytes_downloaded", 0) or 0,
                "dedupe_dropped": max(len(result.items) - items_new, 0),
                "items_seen": len(result.items),
            }

            create_source_run(
                session,
                run_group_id=run_group_id,
                source_id=args.source_id,
                phase="FETCH",
                run_at_utc=result.fetched_at_utc,
                status=result.status,
                status_code=result.status_code,
                error=result.error,
                duration_seconds=result.duration_seconds,
                items_fetched=len(result.items),
                items_new=items_new,
                diagnostics=diagnostics_payload,
            )
            session.commit()
        
        print(f"  Items New (stored): {items_new}")
        
        # Show sample titles
        if result.items:
            print(f"\n  Sample Titles (top 3):")
            for i, item in enumerate(result.items[:3], 1):
                title = item.title or "(no title)"
                print(f"    {i}. {title[:80]}")
        
        # If --ingest flag, run ingest for this source
        if args.ingest:
            print(f"\nIngesting items from {args.source_id}...")
            ingest_args = argparse.Namespace(
                limit=200,
                min_tier=None,
                source_id=args.source_id,
                since=args.since,
                no_suppress=False,
                explain_suppress=False,
                fail_fast=getattr(args, 'fail_fast', False),
            )
            cmd_ingest_external(ingest_args, run_group_id=run_group_id)
    
    except ValueError as e:
        print(f"Error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error testing source: {e}", exc_info=True)
        raise


def cmd_sources_health(args: argparse.Namespace) -> None:
    """Display source health table."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    
    # Parse stale threshold
    stale_hours = 48  # default
    if args.stale:
        stale_str = args.stale.lower().strip()
        if stale_str.endswith("h"):
            stale_hours = int(stale_str[:-1])
        elif stale_str.endswith("d"):
            stale_hours = int(stale_str[:-1]) * 24
    
    lookback_n = args.lookback or 10
    
    # Get source configs for tier info
    sources_config = load_sources_config()
    all_sources_list = get_all_sources(sources_config)
    all_sources = {s["id"]: s for s in all_sources_list}
    source_ids = list(all_sources.keys())
    
    with session_context(sqlite_path) as session:
        from hardstop.database.source_run_repo import get_all_source_health
        
        health_list = get_all_source_health(
            session,
            lookback_n=lookback_n,
            stale_threshold_hours=stale_hours,
            source_ids=source_ids,
        )
        
        if not health_list:
            print("No source health data available. Run 'hardstop fetch' first.")
            return
        
        print(f"\nSource Health (last {lookback_n} runs, stale threshold: {stale_hours}h)")
        print("=" * 140)
        print(f"{'ID':<25} {'Tier':<6} {'Score':>5} {'SR%':>6} {'Last Success':<19} {'Stale':>7} {'Fail':>4} {'Code':>6} {'Supp%':>7} {'State':>8}")
        print("-" * 140)
        
        tier_order = {"global": 0, "regional": 1, "local": 2}
        state_order = {"BLOCKED": 0, "WATCH": 1, "HEALTHY": 2}
        
        def sort_key(health: Dict[str, Any]) -> Any:
            state = health.get("health_budget_state", "WATCH")
            tier = all_sources.get(health["source_id"], {}).get("tier", "unknown")
            return (
                state_order.get(state, 1),
                tier_order.get(tier, 99),
                -(health.get("health_score") or 0),
            )
        
        health_list.sort(key=sort_key)
        
        for health in health_list:
            source_id = health["source_id"]
            tier = all_sources.get(source_id, {}).get("tier", "unknown")[:1].upper()
            last_success = health.get("last_success_utc")
            last_success_display = "Never"
            if last_success:
                try:
                    dt = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
                    last_success_display = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    last_success_display = last_success
            success_rate = health.get("success_rate", 0.0) * 100
            stale_hours_value = health.get("stale_hours")
            stale_display = f"{stale_hours_value:.0f}h" if stale_hours_value is not None else "—"
            status_code = health.get("last_status_code") or "-"
            suppression_ratio = health.get("suppression_ratio")
            suppression_pct = f"{suppression_ratio * 100:.0f}%" if suppression_ratio is not None else "—"
            state = health.get("health_budget_state", "WATCH")
            score = health.get("health_score", 0)
            consecutive_failures = health.get("consecutive_failures", 0)
            
            print(
                f"{source_id:<25} "
                f"{tier:<6} "
                f"{score:>5} "
                f"{success_rate:>5.0f}% "
                f"{last_success_display:<19} "
                f"{stale_display:>7} "
                f"{consecutive_failures:>4} "
                f"{status_code!s:>6} "
                f"{suppression_pct:>7} "
                f"{state:>8}"
            )
        
        print()
        
        if args.explain_suppress:
            source_id = args.explain_suppress
            if source_id not in all_sources:
                print(f"[WARN] Unknown source id '{source_id}' for suppression explanation.")
                return
            summary = summarize_suppression_reasons(
                session,
                source_id=source_id,
                since_hours=stale_hours,
            )
            print(f"Suppression summary for {source_id} (last {stale_hours}h):")
            total = summary.get("total", 0)
            if total == 0:
                print("  No suppressed items in the selected window.")
                return
            for reason in summary.get("reasons", []):
                reason_code = reason.get("reason_code")
                count = reason.get("count", 0)
                rule_ids = reason.get("rule_ids", [])
                print(f"  - {reason_code} :: {count} hits (rules: {', '.join(rule_ids) or 'n/a'})")
                for sample in reason.get("samples", []):
                    title = (sample.get("title") or "(no title)")[:60]
                    stamped = sample.get("suppressed_at_utc", "")
                    print(f"      • {stamped} — {title}")
            print()


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
    
    # Generate run_group_id if not provided
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
    
    # Ensure base tables exist first (creates all tables from schema)
    from hardstop.database.sqlite_client import get_engine
    get_engine(sqlite_path)
    
    # Then run migrations to add any missing columns
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)  # v0.7: trust tier columns
    ensure_source_runs_table(sqlite_path)  # v0.9: source runs table
    
    # Create fetcher
    rng_seed = _derive_seed(run_group_id)
    fetcher = SourceFetcher(strict=mode == "strict", rng_seed=rng_seed)
    
    # Parse since argument
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
            # Still load sources to show what would be fetched
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
            
            # Save to database
            with session_context(sqlite_path) as session:
                # Get source configs once
                sources_config = load_sources_config()
                all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
                
                for result in results:  # results is now List[FetchResult]
                    source_id = result.source_id
                    candidates = result.items
                    
                    # Get source config for tier and trust_tier
                    source_config_raw = all_sources.get(source_id, {})
                    source_config = _resolve_source_defaults(source_config_raw, sources_config)
                    tier = source_config.get("tier", "unknown")
                    trust_tier = source_config.get("trust_tier", 2)
                    
                    # Track items actually inserted (new, not duplicates)
                    items_new = 0
                    
                    for candidate in candidates:
                        try:
                            candidate_dict = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate
                            
                            # Check if item is new by checking if it's in session.new after save
                            # We'll check the raw_id pattern or use a simpler approach: track count before/after
                            raw_item = save_raw_item(
                                session,
                                source_id=source_id,
                                tier=tier,
                                candidate=candidate_dict,
                                trust_tier=trust_tier,
                            )
                            
                            # Check if this is a new item (was just added to session)
                            # New items have status="NEW" and are in session.new
                            if raw_item in session.new or raw_item.status == "NEW":
                                items_new += 1
                                total_stored += 1
                        except Exception as e:
                            logger.error(f"Failed to save raw item from {source_id}: {e}")
                    
                    total_fetched += len(candidates)
                    logger.info(f"Fetched {len(candidates)} items from {source_id}, {items_new} new")
                    
                    # Create FETCH phase SourceRun record
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
        logger.error(f"Error fetching: {e}", exc_info=True)
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
    
    # Generate run_group_id if not provided
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
    
    # Ensure migrations
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)  # v0.7: trust tier columns
    ensure_suppression_columns(sqlite_path)  # v0.8: suppression columns
    ensure_source_runs_table(sqlite_path)  # v0.9: source runs table
    
    # Parse min_tier
    min_tier = args.min_tier
    
    # Parse since_hours if provided
    since_hours = None
    if args.since:
        try:
            since_hours = _parse_since(args.since)
        except ValueError:
            logger.warning(f"Invalid --since value: {args.since}, ignoring")
    
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
        logger.error(f"Error ingesting: {e}", exc_info=True)
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
    """Convenience command: fetch → ingest external → brief → evaluate status."""
    since_str = args.since or "24h"
    stale_threshold = args.stale if hasattr(args, 'stale') else "48h"
    strict_mode = getattr(args, 'strict', False)
    
    # Generate single run_group_id for entire execution (v0.9)
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
        logger.error(f"Fetch failed: {e}", exc_info=True)
        # Will be caught by run status evaluation
    
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
        logger.error(f"Ingest failed: {e}", exc_info=True)
        # Will be caught by run status evaluation
    
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
        logger.error(f"Brief failed: {e}", exc_info=True)
    
    # Step 4: Evaluate run status (v1.0)
    print("\nStep 4: Evaluating run status...")
    
    # Collect fetch results from SourceRun table
    fetch_results: Optional[List[FetchResult]] = None
    ingest_runs: Optional[List[SourceRun]] = None
    doctor_findings: Dict = {}
    stale_sources: List[str] = []
    
    try:
        with session_context(sqlite_path) as session:
            # Get FETCH phase runs for this run_group_id
            fetch_runs = list_recent_runs(session, limit=100, phase="FETCH")
            fetch_runs = [r for r in fetch_runs if r.run_group_id == run_group_id]
            
            # Convert to FetchResult format
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
                        items=[],  # We don't store items in FetchResult for status evaluation
                        items_count=items_count,
                    )
                )
            
            # Get INGEST phase runs for this run_group_id
            ingest_runs = list_recent_runs(session, limit=100, phase="INGEST")
            ingest_runs = [r for r in ingest_runs if r.run_group_id == run_group_id]
            
            # Calculate stale sources
            try:
                stale_hours = _parse_since(stale_threshold)
                if stale_hours:
                    stale_threshold_dt = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
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
                logger.warning(f"Error calculating stale sources: {e}")
    except Exception as e:
        logger.error(f"Error collecting run data: {e}", exc_info=True)
    
    # Run doctor checks to get findings (v1.0)
    try:
        # Check config
        try:
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            enabled_sources = [s for s in all_sources if s.get("enabled", True)]
            doctor_findings["enabled_sources_count"] = len(enabled_sources)
        except FileNotFoundError:
            doctor_findings["config_error"] = "sources.yaml not found"
        except Exception as e:
            doctor_findings["config_error"] = f"Config parse error: {str(e)}"
        
        # Check suppression config
        try:
            from hardstop.config.loader import load_suppression_config
            suppression_config = load_suppression_config()
            suppression_warnings = []
            if not suppression_config.get("enabled", True):
                suppression_warnings.append("Suppression disabled")
            # Check for duplicate rule IDs (simplified check)
            rules = suppression_config.get("rules", [])
            rule_ids = [r.get("id") for r in rules if isinstance(r, dict) and r.get("id")]
            if len(rule_ids) != len(set(rule_ids)):
                suppression_warnings.append("Duplicate rule IDs found")
            if suppression_warnings:
                doctor_findings["suppression_warnings"] = suppression_warnings
        except FileNotFoundError:
            pass  # Suppression config optional
        except Exception as e:
            logger.warning(f"Error checking suppression config: {e}")
        
        # Health budget summary
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
            logger.warning(f"Error evaluating health budgets: {e}")
        
        # Check schema drift (check for required tables)
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
            logger.warning(f"Error checking schema: {e}")
    except Exception as e:
        logger.warning(f"Error running doctor checks: {e}")
    
    # Evaluate run status (v1.0)
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
    
    # Exit with code
    sys.exit(exit_code)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run health checks on Hardstop system."""
    print("Hardstop Doctor - Health Check")
    print("=" * 50)
    
    issues = []
    warnings = []
    
    # Check 1: DB exists and migrations applied
    print("\n[1] Database Check...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)
        
        if not db_path.exists():
            issues.append(f"Database not found: {sqlite_path}")
            print(f"  [X] Database not found: {sqlite_path}")
        else:
            print(f"  [OK] Database exists: {sqlite_path}")
            
            # Check for schema drift - specific missing columns
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            try:
                missing_columns = []
                
                # Check alerts table columns (v0.7: includes trust_tier, tier, source_id)
                alerts_required = [
                    "classification", "correlation_key", "correlation_action",
                    "first_seen_utc", "last_seen_utc", "update_count",
                    "root_event_ids_json", "impact_score", "scope_json",
                    "trust_tier", "tier", "source_id"  # v0.7
                ]
                for col in alerts_required:
                    cur = conn.execute("PRAGMA table_info(alerts);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"alerts.{col}")
                
                # Check events table columns (v0.7: includes trust_tier, v0.8: includes suppression)
                events_required = [
                    "source_id", "raw_id", "event_time_utc",
                    "location_hint", "entities_json", "event_payload_json",
                    "trust_tier",  # v0.7
                    "suppression_primary_rule_id", "suppression_rule_ids_json", "suppressed_at_utc",  # v0.8
                ]
                for col in events_required:
                    cur = conn.execute("PRAGMA table_info(events);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"events.{col}")
                
                # Check raw_items table exists and has trust_tier column
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_items';"
                )
                if not cur.fetchone():
                    missing_columns.append("table: raw_items")
                else:
                    # Check for trust_tier and suppression columns in raw_items (v0.7, v0.8)
                    cur = conn.execute("PRAGMA table_info(raw_items);")
                    cols = [row[1] for row in cur.fetchall()]
                    if "trust_tier" not in cols:
                        missing_columns.append("raw_items.trust_tier")
                    # v0.8: suppression columns
                    suppression_cols = ["suppression_status", "suppression_primary_rule_id", "suppression_rule_ids_json", "suppressed_at_utc", "suppression_stage"]
                    for col in suppression_cols:
                        if col not in cols:
                            missing_columns.append(f"raw_items.{col}")
                
                # Check source_runs table exists (v0.9)
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='source_runs';"
                )
                if not cur.fetchone():
                    missing_columns.append("table: source_runs")
                
                if missing_columns:
                    issues.append(f"Schema drift detected: {len(missing_columns)} missing columns/tables")
                    print(f"  [X] Schema drift detected:")
                    for col in missing_columns:
                        print(f"      - Missing: {col}")
                    print(f"  [INFO] Recommended fix: Delete {sqlite_path} and re-run `hardstop run --since 24h`")
                    print(f"        (Migrations are additive, but fresh DB ensures clean schema)")
                else:
                    print("  [OK] Schema is up to date")
            finally:
                conn.close()
            
            # Try to apply migrations
            try:
                ensure_raw_items_table(sqlite_path)
                ensure_event_external_fields(sqlite_path)
                ensure_alert_correlation_columns(sqlite_path)
                ensure_trust_tier_columns(sqlite_path)  # v0.7: trust tier columns
                ensure_suppression_columns(sqlite_path)  # v0.8: suppression columns
                ensure_source_runs_table(sqlite_path)  # v0.9: source runs table
                print("  [OK] Migrations applied")
            except Exception as e:
                issues.append(f"Migration error: {e}")
                print(f"  [X] Migration error: {e}")
            
            # Check table counts
            try:
                with session_context(sqlite_path) as session:
                    raw_count = session.query(RawItem).count()
                    event_count = session.query(Event).count()
                    alert_count = session.query(Alert).count()
                    
                    print(f"  [OK] raw_items: {raw_count}")
                    print(f"  [OK] events: {event_count}")
                    print(f"  [OK] alerts: {alert_count}")
                    
                    # Check status distribution
                    if raw_count > 0:
                        new_count = session.query(RawItem).filter(RawItem.status == "NEW").count()
                        normalized_count = session.query(RawItem).filter(RawItem.status == "NORMALIZED").count()
                        failed_count = session.query(RawItem).filter(RawItem.status == "FAILED").count()
                        suppressed_count = session.query(RawItem).filter(RawItem.suppression_status == "SUPPRESSED").count()
                        print(f"    - NEW: {new_count}, NORMALIZED: {normalized_count}, FAILED: {failed_count}, SUPPRESSED: {suppressed_count}")
                        if new_count > 0:
                            warnings.append(f"{new_count} raw items pending ingestion")
            except Exception as e:
                issues.append(f"Database query error: {e}")
                print(f"  [X] Database query error: {e}")
    except Exception as e:
        issues.append(f"Config/database error: {e}")
        print(f"  [X] Config/database error: {e}")
    
    # Check 2: sources.yaml is readable
    print("\n[2] Sources Configuration...")
    try:
        sources_config = load_sources_config()
        all_sources = get_all_sources(sources_config)
        enabled_sources = [s for s in all_sources if s.get("enabled", True)]
        
        print(f"  [OK] Sources config loaded")
        print(f"  [OK] Total sources: {len(all_sources)}")
        print(f"  [OK] Enabled sources: {len(enabled_sources)}")
        
        # Count by tier
        tier_counts = {"global": 0, "regional": 0, "local": 0}
        for source in all_sources:
            tier = source.get("tier", "unknown")
            if tier in tier_counts:
                tier_counts[tier] += 1
        
        print(f"    - Global: {tier_counts['global']}, Regional: {tier_counts['regional']}, Local: {tier_counts['local']}")
        
        if len(enabled_sources) == 0:
            warnings.append("No enabled sources configured")
    except FileNotFoundError:
        issues.append("sources.yaml not found")
        print("  [X] sources.yaml not found")
    except Exception as e:
        issues.append(f"Sources config error: {e}")
        print(f"  [X] Sources config error: {e}")
    
    # Check 3: Network connectivity (basic)
    print("\n[3] Network Connectivity...")
    
    # Test NWS API with proper headers
    try:
        sources_config = load_sources_config()
        defaults = sources_config.get("defaults", {})
        user_agent = defaults.get("user_agent", "hardstop-agent/0.6")
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json",
        }
        response = requests.get("https://api.weather.gov/alerts/active", headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"  [OK] NWS API: Reachable (status {response.status_code})")
        elif response.status_code == 403:
            print(f"  [WARN] NWS API: Forbidden (status {response.status_code}) - check User-Agent header")
            warnings.append("NWS API returned 403 - verify User-Agent is set correctly")
        else:
            print(f"  [WARN] NWS API: Status {response.status_code}")
            warnings.append(f"NWS API returned status {response.status_code}")
    except requests.RequestException as e:
        warnings.append("Network connectivity test failed (may affect fetching)")
        print(f"  [WARN] NWS API: Connection failed - {e}")
    
    # Check 4: Suppression configuration (v0.8)
    print("\n[4] Suppression Configuration...")
    try:
        suppression_config = load_suppression_config()
        suppression_enabled = suppression_config.get("enabled", True)
        global_rules = suppression_config.get("rules", [])
        
        print(f"  [OK] Suppression config loaded")
        print(f"  [OK] Suppression enabled: {'yes' if suppression_enabled else 'no'}")
        print(f"  [OK] Global rules: {len(global_rules)}")
        
        # Count per-source rules
        try:
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            per_source_rules_count = 0
            all_rule_ids = set()
            duplicate_rule_ids = set()
            
            # Collect global rule IDs
            for rule in global_rules:
                rule_id = rule.get("id") if isinstance(rule, dict) else getattr(rule, "id", None)
                if rule_id:
                    if rule_id in all_rule_ids:
                        duplicate_rule_ids.add(rule_id)
                    all_rule_ids.add(rule_id)
            
            # Collect per-source rule IDs
            for source in all_sources:
                source_rules = get_suppression_rules_for_source(source)
                per_source_rules_count += len(source_rules)
                for rule in source_rules:
                    rule_id = rule.get("id") if isinstance(rule, dict) else getattr(rule, "id", None)
                    if rule_id:
                        if rule_id in all_rule_ids:
                            duplicate_rule_ids.add(rule_id)
                        all_rule_ids.add(rule_id)
            
            print(f"  [OK] Per-source rules: {per_source_rules_count} total")
            print(f"  [OK] Total rules: {len(all_rule_ids)}")
            
            if duplicate_rule_ids:
                warnings.append(f"Duplicate rule IDs found: {', '.join(sorted(duplicate_rule_ids))}")
                print(f"  [WARN] Duplicate rule IDs: {', '.join(sorted(duplicate_rule_ids))}")
            
            # Show suppressed count if DB exists
            if db_path.exists():
                try:
                    with session_context(sqlite_path) as session:
                        from datetime import datetime, timedelta, timezone
                        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                        cutoff_iso = cutoff.isoformat()
                        suppressed_24h = session.query(RawItem).filter(
                            RawItem.suppression_status == "SUPPRESSED",
                            RawItem.suppressed_at_utc >= cutoff_iso,
                        ).count()
                        if suppressed_24h > 0:
                            print(f"  [OK] Suppressed (last 24h): {suppressed_24h}")
                except Exception:
                    pass  # Ignore DB errors in suppression check
        except Exception as e:
            warnings.append(f"Error counting per-source rules: {e}")
            print(f"  [WARN] Error counting per-source rules: {e}")
    except FileNotFoundError:
        print("  [INFO] Suppression config not found (suppression disabled)")
    except Exception as e:
        warnings.append(f"Suppression config error: {e}")
        print(f"  [WARN] Suppression config error: {e}")
    
    # Check 5: Source health tracking (v0.9)
    print("\n[5] Source Health Tracking...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)
        
        if not db_path.exists():
            print("  [INFO] Database not found - source health tracking unavailable")
        else:
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            try:
                # Check if source_runs table exists
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='source_runs';"
                )
                if not cur.fetchone():
                    print("  [INFO] source_runs table not found")
                    print("  [INFO] Recommended: Run 'hardstop fetch' once to initialize source health tracking")
                else:
                    print("  [OK] source_runs table exists")
                    
                    try:
                        sources_config = load_sources_config()
                        configured_sources = [s["id"] for s in get_all_sources(sources_config)]
                    except Exception:
                        configured_sources = None
                    
                    # Count stale sources (no successful fetch in last 48h)
                    try:
                        with session_context(sqlite_path) as session:
                            from hardstop.database.source_run_repo import get_all_source_health
                            
                            health_list = get_all_source_health(
                                session,
                                lookback_n=10,
                                stale_threshold_hours=48,
                                source_ids=configured_sources,
                            )
                            stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                            stale_cutoff_iso = stale_cutoff.isoformat()
                            
                            stale_count = 0
                            for health in health_list:
                                last_success = health.get("last_success_utc")
                                if not last_success or last_success < stale_cutoff_iso:
                                    stale_count += 1
                            
                            if stale_count > 0:
                                warnings.append(f"{stale_count} sources have not succeeded in last 48h")
                                print(f"  [WARN] Stale sources (no success in 48h): {stale_count}")
                            else:
                                print(f"  [OK] All sources healthy (last 48h)")
                            
                            blocked = [h for h in health_list if h.get("health_budget_state") == "BLOCKED"]
                            watch = [h for h in health_list if h.get("health_budget_state") == "WATCH"]
                            if blocked:
                                blocked_ids = ", ".join(h["source_id"] for h in blocked)
                                issues.append(f"{len(blocked)} source(s) exhausted failure budget: {blocked_ids}")
                                print(f"  [X] Failure budget exhausted for: {blocked_ids}")
                            if watch and not blocked:
                                watch_ids = ", ".join(h["source_id"] for h in watch)
                                warnings.append(f"{len(watch)} source(s) near failure budget: {watch_ids}")
                                print(f"  [WARN] Failure budget warning for: {watch_ids}")
                            
                            if health_list:
                                print(f"  [OK] Tracking health for {len(health_list)} sources")
                    except Exception as e:
                        warnings.append(f"Error checking source health: {e}")
                        print(f"  [WARN] Error checking source health: {e}")
            finally:
                conn.close()
    except Exception as e:
        warnings.append(f"Source health check error: {e}")
        print(f"  [WARN] Source health check error: {e}")
    
    # C2: Last run group summary (v1.0)
    print("\n[6] Last Run Group Summary...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)
        
        if db_path.exists():
            try:
                with session_context(sqlite_path) as session:
                    # Get most recent run_group_id
                    most_recent_run = session.query(SourceRun).order_by(SourceRun.run_at_utc.desc()).first()
                    if most_recent_run:
                        run_group_id = most_recent_run.run_group_id
                        print(f"  [INFO] Most recent run_group_id: {run_group_id[:8]}...")
                        
                        # Get all runs for this group
                        group_runs = session.query(SourceRun).filter(
                            SourceRun.run_group_id == run_group_id
                        ).all()
                        
                        fetch_runs = [r for r in group_runs if r.phase == "FETCH"]
                        ingest_runs = [r for r in group_runs if r.phase == "INGEST"]
                        
                        fetch_success = sum(1 for r in fetch_runs if r.status == "SUCCESS")
                        fetch_fail = sum(1 for r in fetch_runs if r.status == "FAILURE")
                        fetch_quiet = sum(1 for r in fetch_runs if r.status == "SUCCESS" and r.items_fetched == 0)
                        
                        ingest_success = sum(1 for r in ingest_runs if r.status == "SUCCESS")
                        ingest_fail = sum(1 for r in ingest_runs if r.status == "FAILURE")
                        
                        total_alerts_touched = sum(r.items_alerts_touched for r in ingest_runs)
                        total_suppressed = sum(r.items_suppressed for r in ingest_runs)
                        
                        print(f"  [INFO] Fetch: {fetch_success} success / {fetch_fail} fail / {fetch_quiet} quiet success")
                        print(f"  [INFO] Ingest: {ingest_success} success / {ingest_fail} fail")
                        if total_alerts_touched > 0:
                            print(f"  [INFO] Alerts touched: {total_alerts_touched}")
                        if total_suppressed > 0:
                            print(f"  [INFO] Suppressed: {total_suppressed}")
                    else:
                        print("  [INFO] No run data available. Run 'hardstop run --since 24h' first.")
            except Exception as e:
                print(f"  [WARN] Error retrieving last run group: {e}")
        else:
            print("  [INFO] Database not found - no run data available")
    except Exception as e:
        print(f"  [WARN] Error checking last run group: {e}")
    
    # Summary
    print("\n" + "=" * 50)
    if issues:
        print(f"[X] Issues found: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("[OK] No critical issues found")
    
    if warnings:
        print(f"\n[WARN] Warnings: {len(warnings)}")
        for warning in warnings:
            print(f"  - {warning}")
    
    if not issues and not warnings:
        print("\n[OK] All checks passed!")
    
    # C1: What would I do next? (v1.0)
    print("\n" + "=" * 50)
    print("What would I do next?")
    print("-" * 50)
    
    next_action = None
    
    # Priority 1: Schema drift
    if issues:
        for issue in issues:
            if "schema drift" in issue.lower() or "missing" in issue.lower():
                next_action = "Delete hardstop.db and rerun `hardstop run --since 24h`"
                break
    
    # Priority 2: Stale sources
    if not next_action:
        for warning in warnings:
            if "stale" in warning.lower():
                # Try to get a stale source ID
                try:
                    config = load_config()
                    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
                    with session_context(sqlite_path) as session:
                        from hardstop.database.source_run_repo import get_all_source_health
                        health_list = get_all_source_health(session, lookback_n=10)
                        stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                        stale_cutoff_iso = stale_cutoff.isoformat()
                        for health in health_list:
                            last_success = health.get("last_success_utc")
                            if not last_success or last_success < stale_cutoff_iso:
                                source_id = health.get("source_id")
                                if source_id:
                                    next_action = f"Run `hardstop sources test {source_id} --since 72h`"
                                    break
                except Exception:
                    pass
                if not next_action:
                    next_action = "Run `hardstop sources test <id> --since 72h` for stale sources"
                break
    
    # Priority 3: All fetch failing
    if not next_action:
        for issue in issues:
            if "failed" in issue.lower() and "fetch" in issue.lower():
                next_action = "Check network / user agent / endpoint URLs in config/sources.yaml"
                break
    
    # Priority 4: Suppression config invalid
    if not next_action:
        for warning in warnings:
            if "suppression" in warning.lower() and ("invalid" in warning.lower() or "regex" in warning.lower()):
                # Try to extract rule ID
                import re
                rule_match = re.search(r'rule[:\s]+([^\s,]+)', warning, re.IGNORECASE)
                if rule_match:
                    rule_id = rule_match.group(1)
                    next_action = f"Fix suppression.yaml regex: {rule_id}"
                else:
                    next_action = "Fix suppression.yaml configuration"
                break
    
    # Priority 5: Config error
    if not next_action:
        for issue in issues:
            if "config" in issue.lower() or "sources.yaml" in issue.lower():
                next_action = "Fix config/sources.yaml or config/suppression.yaml"
                break
    
    # Default: all good
    if not next_action:
        next_action = "System is healthy. Run `hardstop run --since 24h` to fetch and process new data."
    
    print(f"  → {next_action}")
    print("=" * 50)


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize Hardstop configuration files from examples (v1.0)."""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)
    
    sources_example = config_dir / "sources.example.yaml"
    sources_config = config_dir / "sources.yaml"
    suppression_example = config_dir / "suppression.example.yaml"
    suppression_config = config_dir / "suppression.yaml"
    
    created = []
    skipped = []
    
    # Check if example files exist
    if not sources_example.exists():
        logger.error(f"Example file not found: {sources_example}")
        logger.error("Please ensure config/sources.example.yaml exists")
        return
    
    if not suppression_example.exists():
        logger.error(f"Example file not found: {suppression_example}")
        logger.error("Please ensure config/suppression.example.yaml exists")
        return
    
    # Create sources.yaml
    if sources_config.exists() and not args.force:
        skipped.append("sources.yaml (already exists, use --force to overwrite)")
    else:
        try:
            shutil.copy(sources_example, sources_config)
            created.append("sources.yaml")
            print(f"Created {sources_config}")
        except Exception as e:
            logger.error(f"Failed to create sources.yaml: {e}")
            return
    
    # Create suppression.yaml
    if suppression_config.exists() and not args.force:
        skipped.append("suppression.yaml (already exists, use --force to overwrite)")
    else:
        try:
            shutil.copy(suppression_example, suppression_config)
            created.append("suppression.yaml")
            print(f"Created {suppression_config}")
        except Exception as e:
            logger.error(f"Failed to create suppression.yaml: {e}")
            return
    
    # Summary
    if created:
        print(f"\n✓ Initialized {len(created)} config file(s): {', '.join(created)}")
        print("  Next steps:")
        print("  1. Review and customize config/sources.yaml")
        print("  2. Review and customize config/suppression.yaml")
        print("  3. Run: hardstop run --since 24h")
    
    if skipped:
        print(f"\n⚠ Skipped {len(skipped)} file(s):")
        for item in skipped:
            print(f"  - {item}")


def cmd_export(args: argparse.Namespace) -> None:
    """Export structured data (v1.1)."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    
    try:
        with session_context(sqlite_path) as session:
            from hardstop.api.export import export_alerts, export_brief, export_sources
            
            export_type = args.export_type
            
            if export_type == "brief":
                result = export_brief(
                    session,
                    since=args.since,
                    include_class0=args.include_class0,
                    limit=args.limit,
                    format=args.format,
                    out=args.out,
                )
                if not args.out:
                    print(result)
            elif export_type == "alerts":
                result = export_alerts(
                    session,
                    since=getattr(args, "since", None),
                    classification=getattr(args, "classification", None),
                    tier=getattr(args, "tier", None),
                    source_id=getattr(args, "source_id", None),
                    limit=args.limit,
                    format=args.format,
                    out=args.out,
                )
                if not args.out:
                    print(result)
            elif export_type == "sources":
                result = export_sources(
                    session,
                    lookback=args.lookback,
                    stale=args.stale,
                    format=args.format,
                    out=args.out,
                )
                if not args.out:
                    print(result)
            else:
                logger.error(f"Unknown export type: {export_type}")
                return
    except Exception as e:
        logger.error(f"Error exporting: {e}", exc_info=True)
        raise


def cmd_brief(args: argparse.Namespace, run_group_id: Optional[str] = None) -> None:
    """Generate daily brief."""
    config_snapshot = resolve_config_snapshot()
    started_at = datetime.now(timezone.utc).isoformat()
    mode = "strict" if getattr(args, "strict", False) else "best-effort"
    errors: List[Diagnostic] = []
    output_refs: List[ArtifactRef] = []
    if run_group_id is None:
        run_group_id = getattr(args, "run_group_id", None) or str(uuid.uuid4())
    input_refs: List[ArtifactRef] = [_run_group_ref(run_group_id)]
    rendered_output = ""
    output_format = args.format or "md"
    
    try:
        if not args.today:
            raise ValueError("--today flag is required")
        
        # Parse --since argument
        since_str = args.since or "24h"
        try:
            since_hours = _parse_since(since_str)
        except ValueError as e:
            logger.error(str(e))
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(e)))
            raise
        
        # Get database path
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        ingest_ref = ArtifactRef(
            id=f"source-runs:ingest:{run_group_id}",
            hash=_safe_source_runs_hash(
                sqlite_path,
                run_group_id,
                phase="INGEST",
                fallback_parts=(run_group_id,),
            ),
            kind="SourceRun",
        )
        if len(input_refs) == 1:
            input_refs.append(ingest_ref)
        else:
            input_refs[1] = ingest_ref
        
        # Ensure migrations
        ensure_alert_correlation_columns(sqlite_path)
        ensure_trust_tier_columns(sqlite_path)  # v0.7: trust tier columns
        ensure_suppression_columns(sqlite_path)  # v0.8: suppression columns
        
        # Generate brief
        try:
            with session_context(sqlite_path) as session:
                brief_data = generate_brief(
                    session,
                    since_hours=since_hours,
                    include_class0=args.include_class0,
                    limit=args.limit,
                )
        except Exception as e:
            logger.error(f"Error generating brief: {e}")
            print("Error: Could not generate brief. Ensure database exists and is accessible.")
            print("Run `hardstop ingest` to create the database, then `hardstop demo` to generate alerts.")
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(e)))
            raise
        
        # Render output
        if output_format == "json":
            rendered_output = render_json(brief_data)
        else:
            rendered_output = render_markdown(brief_data)
        print(rendered_output)
        brief_hash = hashlib.sha256(rendered_output.encode("utf-8")).hexdigest()
        output_refs = [
            ArtifactRef(
                id=f"brief:{run_group_id}",
                hash=brief_hash,
                kind="Brief",
                bytes=len(rendered_output.encode("utf-8")),
                schema=f"brief::{output_format}",
            )
        ]
    except Exception as exc:
        if not errors:
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(exc)))
        raise
    finally:
        try:
            emit_run_record(
                operator_id="hardstop.brief@1.0.0",
                mode=mode,
                config_snapshot=config_snapshot,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                input_refs=input_refs,
                output_refs=output_refs,
                errors=errors,
            )
        except Exception as record_error:
            _log_run_record_failure("brief", record_error)


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="hardstop",
        description="Local-first event-to-alert risk agent",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # demo command
    demo_parser = subparsers.add_parser("demo", help="Run the demo pipeline")
    demo_parser.set_defaults(func=cmd_demo)

    # incidents commands
    incidents_parser = subparsers.add_parser("incidents", help="Incident utilities")
    incidents_subparsers = incidents_parser.add_subparsers(
        dest="incidents_subcommand",
        help="Incident subcommands",
        required=True,
    )
    incidents_replay_parser = incidents_subparsers.add_parser("replay", help="Replay an incident from artifacts")
    incidents_replay_parser.add_argument("incident_id", type=str, help="Incident/alert ID to replay")
    incidents_replay_parser.add_argument(
        "--correlation-key",
        type=str,
        help="Correlation key to disambiguate artifacts when multiple exist",
    )
    incidents_replay_parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("output/incidents"),
        help="Directory containing incident evidence artifacts",
    )
    incidents_replay_parser.add_argument(
        "--records-dir",
        type=Path,
        default=Path("run_records"),
        help="Directory containing RunRecord JSON files",
    )
    incidents_replay_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if required artifacts or RunRecords are missing",
    )
    incidents_replay_parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="json",
        help="Output format",
    )
    incidents_replay_parser.set_defaults(func=cmd_incidents_replay)
    
    # ingest command
    ingest_parser = subparsers.add_parser("ingest", help="Load network data from CSV files")
    ingest_parser.add_argument(
        "--fixtures",
        action="store_true",
        help="Use fixture files (default behavior)",
    )
    ingest_parser.set_defaults(func=cmd_ingest)
    
    # sources command
    sources_parser = subparsers.add_parser("sources", help="Source management commands")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_subcommand", help="Sources subcommands", required=True)
    sources_list_parser = sources_subparsers.add_parser("list", help="List configured sources")
    sources_list_parser.set_defaults(func=cmd_sources_list)
    
    # sources test command
    sources_test_parser = sources_subparsers.add_parser("test", help="Test a single source by fetching")
    sources_test_parser.add_argument("source_id", help="Source ID to test")
    sources_test_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    sources_test_parser.add_argument(
        "--max-items",
        type=int,
        default=20,
        help="Maximum items to fetch (default: 20)",
    )
    sources_test_parser.add_argument(
        "--ingest",
        action="store_true",
        help="Also ingest the fetched items",
    )
    sources_test_parser.set_defaults(func=cmd_sources_test)
    
    # sources health command
    sources_health_parser = sources_subparsers.add_parser("health", help="Display source health table")
    sources_health_parser.add_argument(
        "--stale",
        type=str,
        default="48h",
        help="Stale threshold: 24h, 48h, 72h, etc. (default: 48h)",
    )
    sources_health_parser.add_argument(
        "--lookback",
        type=int,
        default=10,
        help="Number of recent runs to consider for success rate (default: 10)",
    )
    sources_health_parser.add_argument(
        "--explain-suppress",
        metavar="SOURCE_ID",
        help="Show suppression reason summary for the specified source",
    )
    sources_health_parser.set_defaults(func=cmd_sources_health)
    
    # fetch command
    fetch_parser = subparsers.add_parser("fetch", help="Fetch items from external sources")
    fetch_parser.add_argument(
        "--tier",
        type=str,
        choices=["global", "regional", "local"],
        help="Filter by tier (default: all)",
    )
    fetch_parser.add_argument(
        "--enabled-only",
        action="store_true",
        default=True,
        help="Only fetch from enabled sources (default: true)",
    )
    fetch_parser.add_argument(
        "--max-items-per-source",
        type=int,
        default=10,
        help="Maximum items per source (default: 10)",
    )
    fetch_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without making changes",
    )
    fetch_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first error (default: continue on errors)",
    )
    fetch_parser.set_defaults(func=cmd_fetch)
    
    # ingest external command (separate from regular ingest)
    ingest_external_parser = subparsers.add_parser("ingest-external", help="Ingest external raw items into events and alerts")
    ingest_external_parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of raw items to process (default: 200)",
    )
    ingest_external_parser.add_argument(
        "--min-tier",
        type=str,
        choices=["global", "regional", "local"],
        help="Minimum tier (global > regional > local)",
    )
    ingest_external_parser.add_argument(
        "--source-id",
        type=str,
        help="Filter by specific source ID",
    )
    ingest_external_parser.add_argument(
        "--since",
        type=str,
        help="Only process items fetched within this time window (24h, 72h, 7d)",
    )
    ingest_external_parser.add_argument(
        "--no-suppress",
        action="store_true",
        help="Bypass suppression entirely (v0.8)",
    )
    ingest_external_parser.add_argument(
        "--explain-suppress",
        action="store_true",
        help="Print suppression decisions for each suppressed item (v0.8)",
    )
    ingest_external_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop processing on first source failure (v1.0)",
    )
    ingest_external_parser.add_argument(
        "--allow-ingest-errors",
        action="store_true",
        help="Allow item-level errors without failing the SourceRun (v1.3)",
    )
    ingest_external_parser.set_defaults(func=cmd_ingest_external)
    
    # run command
    run_parser = subparsers.add_parser("run", help="Run full pipeline: fetch → ingest → brief")
    run_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    run_parser.add_argument(
        "--no-suppress",
        action="store_true",
        help="Bypass suppression entirely (v0.8)",
    )
    run_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop processing on first source failure (v1.0)",
    )
    run_parser.add_argument(
        "--stale",
        type=str,
        default="48h",
        help="Threshold for stale sources (e.g., 48h, 72h) (v1.0)",
    )
    run_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as broken (exit code 2) (v1.0)",
    )
    run_parser.add_argument(
        "--allow-ingest-errors",
        action="store_true",
        help="Allow item-level ingest errors without failing the run (v1.3)",
    )
    run_parser.set_defaults(func=cmd_run)
    
    # brief command
    brief_parser = subparsers.add_parser("brief", help="Generate daily brief")
    brief_parser.add_argument(
        "--today",
        action="store_true",
        help="Generate brief for today (required)",
    )
    brief_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    brief_parser.add_argument(
        "--format",
        type=str,
        choices=["md", "json"],
        default="md",
        help="Output format: md or json (default: md)",
    )
    brief_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of alerts per section (default: 20)",
    )
    brief_parser.add_argument(
        "--include-class0",
        action="store_true",
        help="Include classification 0 (Interesting) alerts",
    )
    brief_parser.set_defaults(func=cmd_brief)
    
    # doctor command
    doctor_parser = subparsers.add_parser("doctor", help="Run health checks on Hardstop system")
    doctor_parser.set_defaults(func=cmd_doctor)
    
    # export command (v1.1)
    export_parser = subparsers.add_parser("export", help="Export structured data (v1.1)")
    export_subparsers = export_parser.add_subparsers(dest="export_type", required=True, help="Export type")
    
    # export brief
    export_brief_parser = export_subparsers.add_parser("brief", help="Export brief data")
    export_brief_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    export_brief_parser.add_argument(
        "--include-class0",
        action="store_true",
        help="Include classification 0 (Interesting) alerts",
    )
    export_brief_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of alerts per section (default: 20)",
    )
    export_brief_parser.add_argument(
        "--format",
        type=str,
        choices=["json"],
        default="json",
        help="Export format (default: json)",
    )
    export_brief_parser.add_argument(
        "--out",
        type=Path,
        help="Output file path (if not provided, prints to stdout)",
    )
    export_brief_parser.set_defaults(func=cmd_export)
    
    # export alerts
    export_alerts_parser = export_subparsers.add_parser("alerts", help="Export alerts data")
    export_alerts_parser.add_argument(
        "--since",
        type=str,
        help="Time window: 24h, 72h, or 7d (if not provided, no time filter)",
    )
    export_alerts_parser.add_argument(
        "--classification",
        type=int,
        choices=[0, 1, 2],
        help="Filter by classification (0, 1, 2)",
    )
    export_alerts_parser.add_argument(
        "--tier",
        type=str,
        choices=["global", "regional", "local"],
        help="Filter by tier",
    )
    export_alerts_parser.add_argument(
        "--source-id",
        type=str,
        help="Filter by source ID",
    )
    export_alerts_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of alerts (default: 50)",
    )
    export_alerts_parser.add_argument(
        "--format",
        type=str,
        choices=["json", "csv"],
        default="json",
        help="Export format (default: json)",
    )
    export_alerts_parser.add_argument(
        "--out",
        type=Path,
        help="Output file path (if not provided, prints to stdout)",
    )
    export_alerts_parser.set_defaults(func=cmd_export)
    
    # export sources
    export_sources_parser = export_subparsers.add_parser("sources", help="Export sources health data")
    export_sources_parser.add_argument(
        "--lookback",
        type=str,
        default="7d",
        help="Lookback window (default: 7d)",
    )
    export_sources_parser.add_argument(
        "--stale",
        type=str,
        default="72h",
        help="Stale threshold (default: 72h)",
    )
    export_sources_parser.add_argument(
        "--format",
        type=str,
        choices=["json"],
        default="json",
        help="Export format (default: json)",
    )
    export_sources_parser.add_argument(
        "--out",
        type=Path,
        help="Output file path (if not provided, prints to stdout)",
    )
    export_sources_parser.set_defaults(func=cmd_export)
    
    # init command (v1.0)
    init_parser = subparsers.add_parser("init", help="Initialize Hardstop configuration files from examples (v1.0)")
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config files",
    )
    init_parser.set_defaults(func=cmd_init)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        args.func(args)
    except Exception as e:
        logger.error(f"Error running command '{args.command}': {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
