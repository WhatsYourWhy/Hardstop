"""Source management CLI commands."""

import argparse
import uuid
from datetime import datetime
from typing import Any, Dict

from hardstop.config.loader import (
    get_all_sources,
    load_config,
    load_sources_config,
)
from hardstop.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_event_external_fields,
    ensure_raw_items_table,
    ensure_source_runs_table,
    ensure_trust_tier_columns,
)
from hardstop.database.raw_item_repo import save_raw_item, summarize_suppression_reasons
from hardstop.database.source_run_repo import create_source_run, get_all_source_health
from hardstop.database.sqlite_client import session_context
from hardstop.retrieval.fetcher import SourceFetcher
from hardstop.utils.logging import get_logger

from ._helpers import _resolve_source_defaults

logger = get_logger(__name__)


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
        logger.error("Sources config not found: %s", e)
        print("Error: Sources config file not found. Create config/sources.yaml")
    except Exception as e:
        logger.error("Error listing sources: %s", e, exc_info=True)
        raise


def cmd_sources_test(args: argparse.Namespace) -> None:
    """Test a single source by fetching (and optionally ingesting)."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")

    run_group_id = str(uuid.uuid4())

    from hardstop.database.sqlite_client import get_engine
    get_engine(sqlite_path)
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    ensure_trust_tier_columns(sqlite_path)
    ensure_source_runs_table(sqlite_path)

    fetcher = SourceFetcher()

    try:
        result = fetcher.fetch_one(
            source_id=args.source_id,
            since=args.since,
            max_items=args.max_items,
        )

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
                    logger.error("Failed to save raw item: %s", e)

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

        if result.items:
            print(f"\n  Sample Titles (top 3):")
            for i, item in enumerate(result.items[:3], 1):
                title = item.title or "(no title)"
                print(f"    {i}. {title[:80]}")

        if args.ingest:
            print(f"\nIngesting items from {args.source_id}...")
            from hardstop.cli.pipeline import cmd_ingest_external
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
        logger.error("Error testing source: %s", e, exc_info=True)
        raise


def cmd_sources_health(args: argparse.Namespace) -> None:
    """Display source health table."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")

    stale_hours = 48
    if args.stale:
        stale_str = args.stale.lower().strip()
        if stale_str.endswith("h"):
            stale_hours = int(stale_str[:-1])
        elif stale_str.endswith("d"):
            stale_hours = int(stale_str[:-1]) * 24

    lookback_n = args.lookback or 10

    sources_config = load_sources_config()
    all_sources_list = get_all_sources(sources_config)
    all_sources = {s["id"]: s for s in all_sources_list}
    source_ids = list(all_sources.keys())

    with session_context(sqlite_path) as session:
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
            stale_display = f"{stale_hours_value:.0f}h" if stale_hours_value is not None else "\u2014"
            status_code = health.get("last_status_code") or "-"
            suppression_ratio = health.get("suppression_ratio")
            suppression_pct = f"{suppression_ratio * 100:.0f}%" if suppression_ratio is not None else "\u2014"
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
                    print(f"      \u2022 {stamped} \u2014 {title}")
            print()
