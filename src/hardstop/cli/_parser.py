"""CLI argument parser and main entrypoint."""

import argparse
from pathlib import Path

from hardstop.utils.logging import get_logger

from .doctor import cmd_doctor
from .output import cmd_brief, cmd_export
from .pipeline import cmd_fetch, cmd_ingest_external, cmd_run
from .setup import cmd_demo, cmd_incidents_replay, cmd_ingest, cmd_init
from .sources import cmd_sources_health, cmd_sources_list, cmd_sources_test

logger = get_logger(__name__)


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="hardstop",
        description="Local-first event-to-alert risk agent",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # demo command
    demo_parser = subparsers.add_parser("demo", help="Run the demo pipeline")
    demo_parser.add_argument(
        "--mode",
        choices=["live", "pinned"],
        default="live",
        help="Live mode preserves real-time IDs; pinned mode freezes run context for audits.",
    )
    demo_parser.add_argument(
        "--timestamp",
        help="Override pinned timestamp (ISO8601). Only used when --mode pinned.",
    )
    demo_parser.add_argument(
        "--seed",
        help="Override pinned UUID seed. Only used when --mode pinned.",
    )
    demo_parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Override pinned run identifier. Only used when --mode pinned.",
    )
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

    # ingest external command
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
        help="Bypass suppression entirely",
    )
    ingest_external_parser.add_argument(
        "--explain-suppress",
        action="store_true",
        help="Print suppression decisions for each suppressed item",
    )
    ingest_external_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop processing on first source failure",
    )
    ingest_external_parser.add_argument(
        "--allow-ingest-errors",
        action="store_true",
        help="Allow item-level errors without failing the SourceRun",
    )
    ingest_external_parser.set_defaults(func=cmd_ingest_external)

    # run command
    run_parser = subparsers.add_parser("run", help="Run full pipeline: fetch \u2192 ingest \u2192 brief")
    run_parser.add_argument(
        "--since",
        type=str,
        default="24h",
        help="Time window: 24h, 72h, or 7d (default: 24h)",
    )
    run_parser.add_argument(
        "--no-suppress",
        action="store_true",
        help="Bypass suppression entirely",
    )
    run_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop processing on first source failure",
    )
    run_parser.add_argument(
        "--stale",
        type=str,
        default="48h",
        help="Threshold for stale sources (e.g., 48h, 72h)",
    )
    run_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as broken (exit code 2)",
    )
    run_parser.add_argument(
        "--allow-ingest-errors",
        action="store_true",
        help="Allow item-level ingest errors without failing the run",
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

    # export command
    export_parser = subparsers.add_parser("export", help="Export structured data")
    export_subparsers = export_parser.add_subparsers(dest="export_type", required=True, help="Export type")

    export_brief_parser = export_subparsers.add_parser("brief", help="Export brief data")
    export_brief_parser.add_argument("--since", type=str, default="24h", help="Time window (default: 24h)")
    export_brief_parser.add_argument("--include-class0", action="store_true", help="Include classification 0 alerts")
    export_brief_parser.add_argument("--limit", type=int, default=20, help="Max alerts per section (default: 20)")
    export_brief_parser.add_argument("--format", type=str, choices=["json"], default="json", help="Export format")
    export_brief_parser.add_argument("--out", type=Path, help="Output file path")
    export_brief_parser.set_defaults(func=cmd_export)

    export_alerts_parser = export_subparsers.add_parser("alerts", help="Export alerts data")
    export_alerts_parser.add_argument("--since", type=str, help="Time window (optional)")
    export_alerts_parser.add_argument("--classification", type=int, choices=[0, 1, 2], help="Filter by classification")
    export_alerts_parser.add_argument("--tier", type=str, choices=["global", "regional", "local"], help="Filter by tier")
    export_alerts_parser.add_argument("--source-id", type=str, help="Filter by source ID")
    export_alerts_parser.add_argument("--limit", type=int, default=50, help="Max alerts (default: 50)")
    export_alerts_parser.add_argument("--format", type=str, choices=["json", "csv"], default="json", help="Export format")
    export_alerts_parser.add_argument("--out", type=Path, help="Output file path")
    export_alerts_parser.set_defaults(func=cmd_export)

    export_sources_parser = export_subparsers.add_parser("sources", help="Export sources health data")
    export_sources_parser.add_argument("--lookback", type=str, default="7d", help="Lookback window (default: 7d)")
    export_sources_parser.add_argument("--stale", type=str, default="72h", help="Stale threshold (default: 72h)")
    export_sources_parser.add_argument("--format", type=str, choices=["json"], default="json", help="Export format")
    export_sources_parser.add_argument("--out", type=Path, help="Output file path")
    export_sources_parser.set_defaults(func=cmd_export)

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize Hardstop configuration files from examples")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing config files")
    init_parser.set_defaults(func=cmd_init)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        args.func(args)
    except Exception as e:
        logger.error("Error running command '%s': %s", args.command, e, exc_info=True)
        raise


if __name__ == "__main__":
    main()
