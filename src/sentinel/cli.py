"""CLI entrypoint for Sentinel agent."""

import argparse

from sentinel.config.loader import load_config
from sentinel.database.migrate import ensure_alert_correlation_columns
from sentinel.database.sqlite_client import session_context
from sentinel.output.daily_brief import (
    _parse_since,
    generate_brief,
    render_json,
    render_markdown,
)
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

