"""CLI package for Hardstop agent.

Re-exports all public names for backwards compatibility with tests
that import from ``hardstop.cli`` directly.
"""

# Entry point
from hardstop.cli._parser import main

# Command handlers
from hardstop.cli.doctor import cmd_doctor
from hardstop.cli.output import cmd_brief, cmd_export
from hardstop.cli.pipeline import cmd_fetch, cmd_ingest_external, cmd_run
from hardstop.cli.setup import cmd_demo, cmd_incidents_replay, cmd_ingest, cmd_init
from hardstop.cli.sources import cmd_sources_health, cmd_sources_list, cmd_sources_test

# Helpers (used by tests via monkeypatch)
from hardstop.cli._helpers import (
    _derive_seed,
    _find_incident_artifacts,
    _hash_parts,
    _load_run_records,
    _log_run_record_failure,
    _resolve_source_defaults,
    _run_group_ref,
    _safe_raw_batch_hash,
    _safe_source_runs_hash,
    logger,
)

# Re-export names that tests monkeypatch on the cli module.
# These allow ``monkeypatch.setattr(cli, "load_config", ...)`` to keep working.
from hardstop.config.loader import (
    get_all_sources,
    get_source_with_defaults,
    get_suppression_rules_for_source,
    load_config,
    load_sources_config,
    load_suppression_config,
)
from hardstop.database.migrate import (
    ensure_alert_correlation_columns,
    ensure_event_external_fields,
    ensure_raw_items_table,
    ensure_source_runs_table,
    ensure_suppression_columns,
    ensure_trust_tier_columns,
)
from hardstop.database.raw_item_repo import save_raw_item, summarize_suppression_reasons
from hardstop.database.schema import Alert, Event, RawItem, SourceRun
from hardstop.database.source_run_repo import create_source_run, get_all_source_health, list_recent_runs
from hardstop.database.sqlite_client import session_context
from hardstop.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    fingerprint_config,
    resolve_config_snapshot,
)
from hardstop.ops.run_status import evaluate_run_status
from hardstop.api.brief_api import _parse_since
from hardstop.retrieval.fetcher import FetchResult, SourceFetcher
from hardstop.runners.ingest_external import main as ingest_external_main
from hardstop.runners.load_network import main as load_network_main
from hardstop.runners.run_demo import main as run_demo_main
from hardstop.output.daily_brief import generate_brief, render_json, render_markdown
from hardstop.ops.artifacts import compute_raw_item_batch_digest, compute_source_runs_digest

from pathlib import Path  # noqa: F401 — tests monkeypatch hardstop.cli.Path
