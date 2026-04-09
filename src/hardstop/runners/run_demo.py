import argparse
import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, Literal, Optional

from hardstop.alerts.alert_builder import build_basic_alert
from hardstop.config.loader import load_config
from hardstop.database.migrate import ensure_alert_correlation_columns
from hardstop.database.sqlite_client import session_context
from hardstop.parsing.network_linker import link_event_to_network
from hardstop.parsing.normalizer import normalize_event
from hardstop.utils.id_generator import deterministic_id_context
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PINNED_TIMESTAMP = datetime(2025, 12, 29, 17, 0, 0, tzinfo=UTC)
DEFAULT_PINNED_SEED = "demo-pinned-seed.v1"
DEFAULT_PINNED_RUN_ID = "demo-golden-run.v1"


@dataclass
class DemoDeterminismConfig:
    mode: Literal["live", "pinned"] = "live"
    timestamp: Optional[datetime] = None
    seed: Optional[str] = None
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.mode == "pinned":
            self.timestamp = (self.timestamp or DEFAULT_PINNED_TIMESTAMP).astimezone(UTC)
            self.seed = self.seed or DEFAULT_PINNED_SEED
            self.run_id = self.run_id or DEFAULT_PINNED_RUN_ID

    @property
    def is_pinned(self) -> bool:
        return self.mode == "pinned"

    def timestamp_iso(self) -> Optional[str]:
        if not self.timestamp:
            return None
        return self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def context_payload(self) -> Optional[Dict[str, str]]:
        if not self.is_pinned:
            return None
        return {
            "seed": self.seed or "",
            "timestamp_utc": self.timestamp_iso() or "",
            "run_id": self.run_id or "",
        }

    def id_context(self):
        if not self.is_pinned:
            return nullcontext()
        return deterministic_id_context(now=self.timestamp, seed=self.seed or DEFAULT_PINNED_SEED)


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO8601 timestamp for pinned mode: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main(
    *,
    mode: Literal["live", "pinned"] = "live",
    pinned_seed: Optional[str] = None,
    pinned_timestamp: Optional[str] = None,
    pinned_run_id: Optional[str] = None,
) -> None:
    """
    Demo pipeline supporting live and pinned determinism modes.
    """
    determinism = DemoDeterminismConfig(
        mode=mode,
        seed=pinned_seed,
        run_id=pinned_run_id,
        timestamp=_parse_timestamp(pinned_timestamp) if pinned_timestamp else None,
    )

    event, alert = _run_demo(determinism)

    logger.info("Built alert (mode=%s):", determinism.mode)
    print(alert.model_dump_json(indent=2))

    if determinism.is_pinned:
        payload = determinism.context_payload() or {}
        logger.info(
            "Pinned context: run_id=%s seed=%s timestamp=%s",
            payload.get("run_id"),
            payload.get("seed"),
            payload.get("timestamp_utc"),
        )

    if alert.evidence and alert.evidence.linking_notes:
        logger.info("Linking and correlation notes:")
        for n in alert.evidence.linking_notes:
            logger.info("- %s", n)

    notes = event.get("linking_notes", [])
    if notes:
        logger.info("Event linking notes:")
        for n in notes:
            logger.info("- %s", n)

    confidence = event.get("link_confidence", {})
    provenance = event.get("link_provenance", {})
    if confidence or provenance:
        logger.info("Link confidence and provenance:")
        if confidence:
            logger.info("  Confidence: %s", confidence)
        if provenance:
            logger.info("  Provenance: %s", provenance)

    if event.get("shipments_truncated"):
        logger.info(
            "Shipments truncated: %s shown of %s total",
            len(event.get("shipments", [])),
            event.get("shipments_total_linked", 0),
        )


def _run_demo(determinism: DemoDeterminismConfig):
    config = load_config()
    demo_config = config.get("demo", {})
    event_path = Path(demo_config.get("event_json", "tests/fixtures/event_spill.json"))
    if not event_path.exists():
        raise FileNotFoundError(f"Fixture not found: {event_path}")

    raw = json.loads(event_path.read_text(encoding="utf-8"))
    raw["event_id"] = "EVT-DEMO-0001"

    event = normalize_event(raw)
    if determinism.is_pinned:
        timestamp_iso = determinism.timestamp_iso()
        event["event_time_utc"] = timestamp_iso
        event["published_at_utc"] = timestamp_iso
        event["scoring_now"] = determinism.timestamp

    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
    ensure_alert_correlation_columns(sqlite_path)

    with session_context(sqlite_path) as session:
        event = link_event_to_network(event, session=session)
        with determinism.id_context():
            alert = build_basic_alert(
                event,
                session=session,
                determinism_mode=determinism.mode,
                determinism_context=determinism.context_payload(),
            )
    return event, alert


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the demo pipeline (live or pinned determinism modes).")
    parser.add_argument(
        "--mode",
        choices=["live", "pinned"],
        default="live",
        help="Select demo determinism mode. Live preserves existing behavior; pinned freezes timestamp + IDs.",
    )
    parser.add_argument(
        "--timestamp",
        help="Override pinned timestamp (ISO8601). Only used when --mode pinned.",
    )
    parser.add_argument(
        "--seed",
        help="Override pinned UUID seed. Only used when --mode pinned.",
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        help="Override pinned run identifier. Only used when --mode pinned.",
    )
    return parser


def cli() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    main(
        mode=args.mode,
        pinned_seed=args.seed,
        pinned_timestamp=args.timestamp,
        pinned_run_id=args.run_id,
    )


if __name__ == "__main__":
    cli()

