"""Brief and export CLI commands."""

import argparse
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
from hardstop.output.incidents.evidence import IncidentArtifactMismatchError
from hardstop.utils.logging import get_logger

from ._helpers import (
    _escalate_run_record_failure,
    _hash_parts,
    _log_run_record_failure,
    _run_group_ref,
    _safe_source_runs_hash,
)

logger = get_logger(__name__)


def cmd_brief(
    args: argparse.Namespace,
    run_group_id: Optional[str] = None,
    publication: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Generate daily brief.

    Args:
        args: Parsed CLI arguments
        run_group_id: Run group this brief belongs to
        publication: Optional v1.3 publication state. When supplied (only by
            cmd_run, and only when readiness is BROKEN in best-effort mode) the
            brief is marked non-authoritative. Omitted for authoritative
            briefs, so the brief.v1 payload is unchanged in the normal case.
    """
    config_snapshot = resolve_config_snapshot()
    started_at = datetime.now(timezone.utc).isoformat()
    strict = getattr(args, "strict", False)
    mode = "strict" if strict else "best-effort"
    errors: List[Diagnostic] = []
    warnings: List[Diagnostic] = []
    output_refs: List[ArtifactRef] = []
    record_failure: Optional[Exception] = None
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
                    strict=strict,
                )
        except IncidentArtifactMismatchError as e:
            # Ordered before the generic handler so a tampered evidence artifact
            # is not reported as "database missing or inaccessible".
            logger.error("Incident evidence failed verification: %s", e)
            print(f"Error: {e}")
            errors.append(Diagnostic(code="INCIDENT_ARTIFACT_MISMATCH", message=str(e)))
            raise
        except Exception as e:
            logger.error("Error generating brief: %s", e)
            print("Error: Could not generate brief. Ensure database exists and is accessible.")
            print("Run `hardstop ingest` to create the database, then `hardstop demo` to generate alerts.")
            errors.append(Diagnostic(code="BRIEF_ERROR", message=str(e)))
            raise

        if publication:
            brief_data["publication"] = publication
            warnings.append(
                Diagnostic(
                    code="BRIEF_DRAFT_ONLY",
                    message="; ".join(publication.get("reasons", []))
                    or "Brief published as DRAFT_ONLY",
                )
            )

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
                warnings=warnings,
                errors=errors,
            )
        except Exception as record_error:
            record_failure = record_error
            _log_run_record_failure("brief", record_error)

    # Escalation happens after the try/finally, never inside it: raising from a
    # finally block would mask the command's own exception. If the body raised,
    # this line is unreachable and the original error propagates as before.
    _escalate_run_record_failure("brief", record_failure, strict=strict)


def cmd_export(args: argparse.Namespace, run_group_id: Optional[str] = None) -> None:
    """
    Export structured data.

    Emits a RunRecord (v1.3). Before this, export was the only artifact-
    producing CLI surface with no provenance record, so an exported bundle
    could not be attributed to a run or a config.
    """
    config = load_config()
    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")

    config_snapshot = resolve_config_snapshot()
    started_at = datetime.now(timezone.utc).isoformat()
    strict = getattr(args, "strict", False)
    mode = "strict" if strict else "best-effort"
    if run_group_id is None:
        run_group_id = getattr(args, "run_group_id", None) or str(uuid.uuid4())
    export_type = getattr(args, "export_type", "unknown")
    export_format = getattr(args, "format", "json") or "json"

    errors: List[Diagnostic] = []
    output_refs: List[ArtifactRef] = []
    record_failure: Optional[Exception] = None

    filter_parts = [
        export_type,
        export_format,
        str(getattr(args, "since", None)),
        str(getattr(args, "classification", None)),
        str(getattr(args, "tier", None)),
        str(getattr(args, "source_id", None)),
        str(getattr(args, "limit", None)),
        str(getattr(args, "lookback", None)),
        str(getattr(args, "stale", None)),
    ]
    input_refs: List[ArtifactRef] = [
        _run_group_ref(run_group_id),
        ArtifactRef(
            id=f"export-filter:{export_type}",
            hash=_hash_parts(*filter_parts),
            kind="ExportFilter",
        ),
    ]

    try:
        with session_context(sqlite_path) as session:
            from hardstop.api.export import export_alerts, export_brief, export_sources

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

        # Hash the bytes that actually exist. Reading the file back is
        # deliberate: it certifies what landed on disk rather than what we
        # intended to write.
        out_path = getattr(args, "out", None)
        payload_bytes = out_path.read_bytes() if out_path else result.encode("utf-8")
        output_refs = [
            ArtifactRef(
                id=f"export:{export_type}:{run_group_id}",
                hash=hashlib.sha256(payload_bytes).hexdigest(),
                kind="Export",
                schema=f"export::{export_format}",
                bytes=len(payload_bytes),
            )
        ]
    except Exception as e:
        logger.error("Error exporting: %s", e, exc_info=True)
        errors.append(Diagnostic(code="EXPORT_ERROR", message=str(e)))
        raise
    finally:
        try:
            emit_run_record(
                operator_id="hardstop.export@1.0.0",
                mode=mode,
                config_snapshot=config_snapshot,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
                input_refs=input_refs,
                output_refs=output_refs,
                errors=errors,
            )
        except Exception as record_error:
            record_failure = record_error
            _log_run_record_failure("export", record_error)

    _escalate_run_record_failure("export", record_failure, strict=strict)
