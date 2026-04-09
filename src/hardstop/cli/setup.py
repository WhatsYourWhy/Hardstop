"""Setup, demo, and incident replay CLI commands."""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    fingerprint_config,
    resolve_config_snapshot,
)
from hardstop.runners.load_network import main as load_network_main
from hardstop.runners.run_demo import main as run_demo_main
from hardstop.utils.logging import get_logger

from ._helpers import (
    _find_incident_artifacts,
    _load_run_records,
    _log_run_record_failure,
)

logger = get_logger(__name__)


def cmd_demo(args: argparse.Namespace) -> None:
    """Run the demo pipeline."""
    run_demo_main(
        mode=getattr(args, "mode", "live"),
        pinned_seed=getattr(args, "seed", None),
        pinned_timestamp=getattr(args, "timestamp", None),
        pinned_run_id=getattr(args, "run_id", None),
    )


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
            from hardstop.ops.run_record import artifact_hash as _artifact_hash

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
    except Exception as exc:
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


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize Hardstop configuration files from examples."""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    sources_example = config_dir / "sources.example.yaml"
    sources_config = config_dir / "sources.yaml"
    suppression_example = config_dir / "suppression.example.yaml"
    suppression_config = config_dir / "suppression.yaml"

    created = []
    skipped = []

    if not sources_example.exists():
        logger.error("Example file not found: %s", sources_example)
        logger.error("Please ensure config/sources.example.yaml exists")
        return

    if not suppression_example.exists():
        logger.error("Example file not found: %s", suppression_example)
        logger.error("Please ensure config/suppression.example.yaml exists")
        return

    if sources_config.exists() and not args.force:
        skipped.append("sources.yaml (already exists, use --force to overwrite)")
    else:
        try:
            shutil.copy(sources_example, sources_config)
            created.append("sources.yaml")
            print(f"Created {sources_config}")
        except Exception as e:
            logger.error("Failed to create sources.yaml: %s", e)
            return

    if suppression_config.exists() and not args.force:
        skipped.append("suppression.yaml (already exists, use --force to overwrite)")
    else:
        try:
            shutil.copy(suppression_example, suppression_config)
            created.append("suppression.yaml")
            print(f"Created {suppression_config}")
        except Exception as e:
            logger.error("Failed to create suppression.yaml: %s", e)
            return

    if created:
        print(f"\n\u2713 Initialized {len(created)} config file(s): {', '.join(created)}")
        print("  Next steps:")
        print("  1. Review and customize config/sources.yaml")
        print("  2. Review and customize config/suppression.yaml")
        print("  3. Run: hardstop run --since 24h")

    if skipped:
        print(f"\n\u26a0 Skipped {len(skipped)} file(s):")
        for item in skipped:
            print(f"  - {item}")
