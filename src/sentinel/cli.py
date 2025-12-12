"""CLI entrypoint for Sentinel agent."""

import argparse
from datetime import date

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
    """Generate daily brief (stub implementation)."""
    today = date.today()
    print(f"Sentinel Daily Brief — {today}")
    print()
    print("Daily brief generation is not yet implemented.")
    print("This command will summarize open alerts and notable changes.")
    print()
    print("Coming in a future release.")


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

