"""Export API: structured data export for external consumption."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..ops.run_record import artifact_hash, fingerprint_config, resolve_config_snapshot
from ..utils.time import utc_now_z
from .alerts_api import list_alerts
from .brief_api import get_brief
from .sources_api import get_sources_health, list_sources


def _create_export_manifest(
    export_data: Dict[str, Any],
    artifact_refs: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a self-verifying manifest for the export bundle.
    
    Includes:
    - Config fingerprint (for replayability)
    - Artifact hashes (for verification)
    - Export metadata
    
    Args:
        export_data: The export data dictionary
        artifact_refs: Optional list of artifact references with hashes
        
    Returns:
        Manifest dictionary with config_hash, export_data_hash, artifact_hashes, etc.
    """
    config_snapshot = resolve_config_snapshot()
    config_hash = fingerprint_config(config_snapshot)
    
    # Extract artifact hashes from artifact refs
    artifact_hashes = []
    if artifact_refs:
        artifact_hashes = [ref.get("hash") for ref in artifact_refs if ref.get("hash")]
    
    # Also hash the export data itself for verification
    export_data_hash = artifact_hash(export_data)
    
    manifest = {
        "manifest_version": "1",
        "export_schema_version": export_data.get("export_schema_version", "1"),
        "exported_at_utc": export_data.get("exported_at_utc"),
        "config_hash": config_hash,
        "export_data_hash": export_data_hash,
        "artifact_hashes": sorted(artifact_hashes) if artifact_hashes else [],
        "config_snapshot": config_snapshot,  # Include full snapshot for client verification
    }
    return manifest


def export_brief(
    session: Session,
    since: str,
    include_class0: bool = False,
    limit: int = 20,
    format: str = "json",
    out: Path | None = None,
    include_manifest: bool = True,
) -> str:
    """
    Export brief data.
    
    Args:
        session: SQLAlchemy session
        since: Time window string (24h, 72h, 7d)
        include_class0: Whether to include classification 0 alerts
        limit: Maximum number of alerts to return
        format: Export format ("json")
        out: Output file path (if None, returns as string)
        include_manifest: Whether to include self-verifying manifest
        
    Returns:
        Exported data as string (if out is None) or writes to file
    """
    brief_data = get_brief(session, since=since, include_class0=include_class0, limit=limit)
    
    # Wrap in export schema
    export_data = {
        "export_schema_version": "1",
        "exported_at_utc": utc_now_z(),
        "data": brief_data,
    }
    
    if format == "json":
        output = json.dumps(export_data, indent=2, sort_keys=True)
        
        # Add manifest if requested
        if include_manifest and out:
            manifest = _create_export_manifest(export_data)
            manifest_path = out.parent / f"{out.stem}.manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        
        if out:
            out.write_text(output, encoding="utf-8")
            return f"Exported to {out}"
        return output
    else:
        raise ValueError(f"Unsupported format: {format}")


def export_alerts(
    session: Session,
    since: str | None = None,
    classification: int | None = None,
    tier: str | None = None,
    source_id: str | None = None,
    limit: int = 50,
    format: str = "json",
    out: Path | None = None,
    include_manifest: bool = True,
) -> str:
    """
    Export alerts data.
    
    Args:
        session: SQLAlchemy session
        since: Time window string (24h, 72h, 7d) or None for all
        classification: Filter by classification (0, 1, 2) or None for all
        tier: Filter by tier (global, regional, local) or None for all
        source_id: Filter by source_id or None for all
        limit: Maximum number of alerts to return
        format: Export format ("json" or "csv")
        out: Output file path (if None, returns as string)
        include_manifest: Whether to include self-verifying manifest
        
    Returns:
        Exported data as string (if out is None) or writes to file
    """
    alerts = list_alerts(
        session,
        since=since,
        classification=classification,
        tier=tier,
        source_id=source_id,
        limit=limit,
    )
    
    # Collect artifact hashes from alerts (incident evidence artifacts)
    artifact_refs = []
    for alert in alerts:
        if alert.evidence and alert.evidence.incident_evidence:
            incident = alert.evidence.incident_evidence
            if incident.artifact_hash:
                artifact_refs.append({
                    "id": f"incident:{alert.alert_id}",
                    "hash": incident.artifact_hash,
                    "kind": "IncidentEvidence",
                })
    
    if format == "json":
        export_data = {
            "export_schema_version": "1",
            "exported_at_utc": utc_now_z(),
            "data": [alert.model_dump() for alert in alerts],
        }
        output = json.dumps(export_data, indent=2, sort_keys=True)
        
        # Add manifest if requested
        if include_manifest and out:
            manifest = _create_export_manifest(export_data, artifact_refs=artifact_refs)
            manifest_path = out.parent / f"{out.stem}.manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        
        if out:
            out.write_text(output, encoding="utf-8")
            return f"Exported to {out}"
        return output
    elif format == "csv":
        # CSV: stable column order, no nested structures
        # Query Alert rows to get tier/source_id/update_count/timestamps
        # Use repo function (canonical surface rule)
        from ..database.alert_repo import find_alert_by_id
        
        alert_ids = [alert.alert_id for alert in alerts]
        alert_rows = {}
        if alert_ids:
            # Batch query would be better, but for now query individually
            # TODO: Add batch query function to alert_repo
            for alert_id in alert_ids:
                alert_row = find_alert_by_id(session, alert_id)
                if alert_row:
                    alert_rows[alert_id] = alert_row
        
        columns = [
            "alert_id",
            "classification",
            "impact_score",
            "tier",
            "trust_tier",
            "source_id",
            "correlation_action",
            "update_count",
            "first_seen_utc",
            "last_seen_utc",
            "summary",
        ]
        
        rows = []
        for alert in alerts:
            alert_row = alert_rows.get(alert.alert_id)
            
            # Extract correlation_action from evidence if available
            correlation_action = None
            if alert.evidence and alert.evidence.correlation:
                correlation_action = alert.evidence.correlation.get("action")
            elif alert_row:
                correlation_action = alert_row.correlation_action
            
            row = {
                "alert_id": alert.alert_id,
                "classification": alert.classification,
                "impact_score": alert.evidence.diagnostics.impact_score if alert.evidence and alert.evidence.diagnostics else (alert_row.impact_score if alert_row else None),
                "tier": alert_row.tier if alert_row else None,
                "trust_tier": alert_row.trust_tier if alert_row else None,
                "source_id": alert_row.source_id if alert_row else None,
                "correlation_action": correlation_action,
                "update_count": alert_row.update_count if alert_row else None,
                "first_seen_utc": alert_row.first_seen_utc if alert_row else None,
                "last_seen_utc": alert_row.last_seen_utc if alert_row else None,
                "summary": alert.summary,
            }
            rows.append(row)
        
        # Write CSV with proper escaping
        import csv as csv_module
        from io import StringIO
        
        output_buffer = StringIO()
        writer = csv_module.writer(output_buffer)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(col, "") for col in columns])
        
        output = output_buffer.getvalue()
        
        # Add manifest if requested (for CSV exports too)
        if include_manifest and out:
            # For CSV, create a minimal export data dict for manifest
            export_data_for_manifest = {
                "export_schema_version": "1",
                "exported_at_utc": utc_now_z(),
                "format": "csv",
                "row_count": len(alerts),
            }
            manifest = _create_export_manifest(export_data_for_manifest, artifact_refs=artifact_refs)
            manifest_path = out.parent / f"{out.stem}.manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        
        if out:
            out.write_text(output, encoding="utf-8", newline="")
            return f"Exported to {out}"
        return output
    else:
        raise ValueError(f"Unsupported format: {format}")


def export_sources(
    session: Session,
    lookback: str = "7d",
    stale: str = "72h",
    format: str = "json",
    out: Path | None = None,
    include_manifest: bool = True,
) -> str:
    """
    Export sources health data.
    
    Args:
        session: SQLAlchemy session
        lookback: Lookback window (e.g., "7d", "10")
        stale: Stale threshold (e.g., "72h", "48h")
        format: Export format ("json")
        out: Output file path (if None, returns as string)
        include_manifest: Whether to include self-verifying manifest
        
    Returns:
        Exported data as string (if out is None) or writes to file
    """
    sources_health = get_sources_health(session, lookback=lookback, stale=stale)
    
    export_data = {
        "export_schema_version": "1",
        "exported_at_utc": utc_now_z(),
        "data": sources_health,
    }
    
    if format == "json":
        output = json.dumps(export_data, indent=2, sort_keys=True)
        
        # Add manifest if requested
        if include_manifest and out:
            manifest = _create_export_manifest(export_data)
            manifest_path = out.parent / f"{out.stem}.manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        
        if out:
            out.write_text(output, encoding="utf-8")
            return f"Exported to {out}"
        return output
    else:
        raise ValueError(f"Unsupported format: {format}")

