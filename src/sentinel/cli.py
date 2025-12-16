"""CLI entrypoint for Sentinel agent."""

import argparse
from pathlib import Path

import requests

from sentinel.config.loader import get_all_sources, load_config, load_sources_config
from sentinel.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_event_external_fields,
    ensure_raw_items_table,
)
from sentinel.database.raw_item_repo import save_raw_item
from sentinel.database.schema import Alert, Event, RawItem
from sentinel.database.sqlite_client import session_context
from sentinel.output.daily_brief import (
    _parse_since,
    generate_brief,
    render_json,
    render_markdown,
)
from sentinel.retrieval.fetcher import SourceFetcher
from sentinel.runners.ingest_external import main as ingest_external_main
from sentinel.runners.load_network import main as load_network_main
from sentinel.runners.run_demo import main as run_demo_main
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def cmd_demo(args: argparse.Namespace) -> None:
    """Run the demo pipeline."""
    run_demo_main()


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


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch items from external sources."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "sentinel.db")
    
    # Ensure migrations
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    
    # Create fetcher
    fetcher = SourceFetcher()
    
    # Parse since argument
    since_hours = None
    if args.since:
        since_str = args.since.lower().strip()
        if since_str.endswith("h"):
            since_hours = int(since_str[:-1])
        elif since_str.endswith("d"):
            since_hours = int(since_str[:-1]) * 24
    
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
        return
    
    # Fetch items
    try:
        results = fetcher.fetch_all(
            tier=args.tier,
            enabled_only=args.enabled_only,
            max_items_per_source=args.max_items_per_source,
            since=args.since,
            fail_fast=args.fail_fast,
        )
        
        # Save to database
        total_fetched = 0
        total_stored = 0
        
        with session_context(sqlite_path) as session:
            for source_id, candidates in results.items():
                # Get source config for tier
                sources_config = load_sources_config()
                all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
                source_config = all_sources.get(source_id, {})
                tier = source_config.get("tier", "unknown")
                
                for candidate in candidates:
                    try:
                        candidate_dict = candidate.model_dump() if hasattr(candidate, "model_dump") else candidate
                        save_raw_item(
                            session,
                            source_id=source_id,
                            tier=tier,
                            candidate=candidate_dict,
                        )
                        total_stored += 1
                    except Exception as e:
                        logger.error(f"Failed to save raw item from {source_id}: {e}")
                
                total_fetched += len(candidates)
                logger.info(f"Fetched {len(candidates)} items from {source_id}")
            
            session.commit()
        
        print(f"Fetch complete: {total_fetched} items fetched, {total_stored} stored")
        
    except Exception as e:
        logger.error(f"Error fetching: {e}", exc_info=True)
        raise


def cmd_ingest_external(args: argparse.Namespace) -> None:
    """Ingest external raw items into events and alerts."""
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "sentinel.db")
    
    # Ensure migrations
    ensure_raw_items_table(sqlite_path)
    ensure_event_external_fields(sqlite_path)
    ensure_alert_correlation_columns(sqlite_path)
    
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
            )
            
            print(f"Ingestion complete:")
            print(f"  Processed: {stats['processed']}")
            print(f"  Events: {stats['events']}")
            print(f"  Alerts: {stats['alerts']}")
            print(f"  Errors: {stats['errors']}")
    
    except Exception as e:
        logger.error(f"Error ingesting: {e}", exc_info=True)
        raise


def cmd_run(args: argparse.Namespace) -> None:
    """Convenience command: fetch → ingest external → brief."""
    since_str = args.since or "24h"
    
    # Step 1: Fetch
    print("Step 1: Fetching from sources...")
    fetch_args = argparse.Namespace(
        tier=None,
        enabled_only=True,
        max_items_per_source=50,
        since=since_str,
        dry_run=False,
        fail_fast=False,
    )
    cmd_fetch(fetch_args)
    
    # Step 2: Ingest external
    print("\nStep 2: Ingesting external items...")
    ingest_args = argparse.Namespace(
        limit=200,
        min_tier=None,
        source_id=None,
        since=since_str,
    )
    cmd_ingest_external(ingest_args)
    
    # Step 3: Brief
    print("\nStep 3: Generating brief...")
    brief_args = argparse.Namespace(
        today=True,
        since=since_str,
        format="md",
        limit=20,
        include_class0=False,
    )
    cmd_brief(brief_args)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run health checks on Sentinel system."""
    print("Sentinel Doctor - Health Check")
    print("=" * 50)
    
    issues = []
    warnings = []
    
    # Check 1: DB exists and migrations applied
    print("\n[1] Database Check...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "sentinel.db")
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
                
                # Check alerts table columns
                alerts_required = [
                    "classification", "correlation_key", "correlation_action",
                    "first_seen_utc", "last_seen_utc", "update_count",
                    "root_event_ids_json", "impact_score", "scope_json"
                ]
                for col in alerts_required:
                    cur = conn.execute("PRAGMA table_info(alerts);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"alerts.{col}")
                
                # Check events table columns
                events_required = [
                    "source_id", "raw_id", "event_time_utc",
                    "location_hint", "entities_json", "event_payload_json"
                ]
                for col in events_required:
                    cur = conn.execute("PRAGMA table_info(events);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"events.{col}")
                
                # Check raw_items table exists
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_items';"
                )
                if not cur.fetchone():
                    missing_columns.append("table: raw_items")
                
                if missing_columns:
                    issues.append(f"Schema drift detected: {len(missing_columns)} missing columns/tables")
                    print(f"  [X] Schema drift detected:")
                    for col in missing_columns:
                        print(f"      - Missing: {col}")
                    print(f"  [INFO] Run migrations or delete {sqlite_path} and re-run")
                else:
                    print("  [OK] Schema is up to date")
            finally:
                conn.close()
            
            # Try to apply migrations
            try:
                ensure_raw_items_table(sqlite_path)
                ensure_event_external_fields(sqlite_path)
                ensure_alert_correlation_columns(sqlite_path)
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
                        print(f"    - NEW: {new_count}, NORMALIZED: {normalized_count}, FAILED: {failed_count}")
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
    test_urls = [
        ("NWS API", "https://api.weather.gov/alerts/active"),
        ("Google DNS", "https://8.8.8.8"),  # Simple connectivity test
    ]
    
    network_ok = False
    for name, url in test_urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code < 500:
                print(f"  [OK] {name}: Reachable")
                network_ok = True
                break
        except requests.RequestException:
            continue
    
    if not network_ok:
        warnings.append("Network connectivity test failed (may affect fetching)")
        print("  [WARN] Network connectivity test failed")
    
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


def cmd_brief(args: argparse.Namespace) -> None:
    """Generate daily brief."""
    if not args.today:
        logger.error("--today flag is required")
        return
    
    # Parse --since argument
    since_str = args.since or "24h"
    try:
        since_hours = _parse_since(since_str)
    except ValueError as e:
        logger.error(str(e))
        return
    
    # Get database path
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "sentinel.db")
    
    # Ensure migration
    ensure_alert_correlation_columns(sqlite_path)
    
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
        print("Run `sentinel ingest` to create the database, then `sentinel demo` to generate alerts.")
        return
    
    # Render output
    output_format = args.format or "md"
    if output_format == "json":
        print(render_json(brief_data))
    else:
        print(render_markdown(brief_data))


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Local-first event-to-alert risk agent",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # demo command
    demo_parser = subparsers.add_parser("demo", help="Run the demo pipeline")
    demo_parser.set_defaults(func=cmd_demo)
    
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
        default=50,
        help="Maximum items per source (default: 50)",
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
    ingest_external_parser.set_defaults(func=cmd_ingest_external)
    
    # run command
    run_parser = subparsers.add_parser("run", help="Run full pipeline: fetch → ingest → brief")
    run_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
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
    doctor_parser = subparsers.add_parser("doctor", help="Run health checks on Sentinel system")
    doctor_parser.set_defaults(func=cmd_doctor)
    
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

