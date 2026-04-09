"""Brief and export CLI commands."""

import argparse
import hashlib
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from hardstop.api.brief_api import _parse_since
from hardstop.config.loader import load_config
from hardstop.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_suppression_columns,
    ensure_trust_tier_columns,
)
from hardstop.database.sqlite_client import session_context
from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    resolve_config_snapshot,
)
from hardstop.output.daily_brief import generate_brief, render_json, render_markdown
from hardstop.utils.logging import get_logger

from ._helpers import _log_run_record_failure, _run_group_ref, _safe_source_runs_hash

logger = get_logger(__name__)


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

        since_str = args.since or "24h"
        try:
            since_hours = _parse_since(since_str)
        except ValueError as e:
            logger.error(str(e))
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(e)))
            raise

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

        ensure_alert_correlation_columns(sqlite_path)
        ensure_trust_tier_columns(sqlite_path)
        ensure_suppression_columns(sqlite_path)

        try:
            with session_context(sqlite_path) as session:
                brief_data = generate_brief(
                    session,
                    since_hours=since_hours,
                    include_class0=args.include_class0,
                    limit=args.limit,
                )
        except Exception as e:
            logger.error("Error generating brief: %s", e)
            print("Error: Could not generate brief. Ensure database exists and is accessible.")
            print("Run `hardstop ingest` to create the database, then `hardstop demo` to generate alerts.")
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(e)))
            raise

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


def cmd_export(args: argparse.Namespace) -> None:
    """Export structured data."""
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
                logger.error("Unknown export type: %s", export_type)
                return
    except Exception as e:
        logger.error("Error exporting: %s", e, exc_info=True)
        raise
