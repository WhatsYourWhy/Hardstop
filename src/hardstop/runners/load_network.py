from pathlib import Path

from hardstop.config.loader import load_config
from hardstop.database.sqlite_client import get_session
from hardstop.ingestion.file_ingestor import ingest_all_csvs
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)


def main() -> None:
    """
    Load network data (facilities, lanes, shipments) from CSV files into SQLite.
    
    Reads paths from hardstop.config.yaml or uses defaults.
    """
    config = load_config()
    
    # Get CSV paths from config
    demo_config = config.get("demo", {})
    facilities_csv = Path(demo_config.get("facilities_csv", "tests/fixtures/facilities.csv"))
    lanes_csv = Path(demo_config.get("lanes_csv", "tests/fixtures/lanes.csv"))
    shipments_csv = Path(demo_config.get("shipments_csv", "tests/fixtures/shipments_snapshot.csv"))
    
    # Get database path
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    
    # Create session and load data
    session = get_session(sqlite_path)
    try:
        counts = ingest_all_csvs(facilities_csv, lanes_csv, shipments_csv, session)
        
        print(f"Loaded {counts['facilities']} facilities, {counts['lanes']} lanes, {counts['shipments']} shipments")
        logger.info(f"Network data loaded successfully: {counts}")
    finally:
        session.close()


if __name__ == "__main__":
    main()

