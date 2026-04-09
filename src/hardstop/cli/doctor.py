"""Health check CLI command."""

import argparse
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import requests

from hardstop.config.loader import (
    get_all_sources,
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
from hardstop.database.schema import Alert, Event, RawItem, SourceRun
from hardstop.database.source_run_repo import get_all_source_health
from hardstop.database.sqlite_client import session_context
from hardstop.utils.logging import get_logger

logger = get_logger(__name__)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run health checks on Hardstop system."""
    print("Hardstop Doctor - Health Check")
    print("=" * 50)

    issues: List[str] = []
    warnings: List[str] = []

    # Check 0: CLI access & PATH hygiene
    print("\n[0] CLI Access & PATH...")
    try:
        user_bin = Path.home() / ".local" / "bin"
        path_entries = [
            entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry
        ]
        hardstop_path = shutil.which("hardstop")
        if hardstop_path:
            print(f"  [OK] hardstop CLI found at: {hardstop_path}")
        else:
            warning_msg = "hardstop CLI not found on PATH (activate your venv or add ~/.local/bin)"
            warnings.append(warning_msg)
            print(f"  [WARN] {warning_msg}")
        if user_bin.exists():
            if str(user_bin) in path_entries:
                print(f"  [OK] PATH includes user-level scripts: {user_bin}")
            else:
                msg = f"{user_bin} not on PATH (pip --user installs land here)"
                warnings.append(msg)
                print(f"  [WARN] {msg}")
                print('        Add `export PATH="$HOME/.local/bin:$PATH"` to your shell rc or re-activate your virtualenv.')
    except Exception as e:
        warn_msg = f"PATH check failed: {e}"
        warnings.append(warn_msg)
        print(f"  [WARN] {warn_msg}")

    # Check 1: DB exists and migrations applied
    print("\n[1] Database Check...")
    db_path = None
    sqlite_path = None
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)

        if not db_path.exists():
            issue_msg = (
                f"Database not found: {sqlite_path} "
                "(run `hardstop init` then `hardstop run --since 24h` to create it)"
            )
            issues.append(issue_msg)
            print(f"  [X] {issue_msg}")
            print("        Follow the README first-time setup commands to create a fresh SQLite database.")
        else:
            print(f"  [OK] Database exists: {sqlite_path}")

            conn = sqlite3.connect(sqlite_path)
            try:
                missing_columns = []

                alerts_required = [
                    "classification", "correlation_key", "correlation_action",
                    "first_seen_utc", "last_seen_utc", "update_count",
                    "root_event_ids_json", "impact_score", "scope_json",
                    "trust_tier", "tier", "source_id",
                    "diagnostics_json",
                ]
                for col in alerts_required:
                    cur = conn.execute("PRAGMA table_info(alerts);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"alerts.{col}")

                events_required = [
                    "source_id", "raw_id", "event_time_utc",
                    "location_hint", "entities_json", "event_payload_json",
                    "trust_tier",
                    "suppression_primary_rule_id", "suppression_rule_ids_json", "suppressed_at_utc",
                ]
                for col in events_required:
                    cur = conn.execute("PRAGMA table_info(events);")
                    cols = [row[1] for row in cur.fetchall()]
                    if col not in cols:
                        missing_columns.append(f"events.{col}")

                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='raw_items';"
                )
                if not cur.fetchone():
                    missing_columns.append("table: raw_items")
                else:
                    cur = conn.execute("PRAGMA table_info(raw_items);")
                    cols = [row[1] for row in cur.fetchall()]
                    if "trust_tier" not in cols:
                        missing_columns.append("raw_items.trust_tier")
                    suppression_cols = ["suppression_status", "suppression_primary_rule_id", "suppression_rule_ids_json", "suppressed_at_utc", "suppression_stage"]
                    for col in suppression_cols:
                        if col not in cols:
                            missing_columns.append(f"raw_items.{col}")

                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='source_runs';"
                )
                if not cur.fetchone():
                    missing_columns.append("table: source_runs")

                if missing_columns:
                    issues.append(f"Schema drift detected: {len(missing_columns)} missing columns/tables")
                    print(f"  [X] Schema drift detected:")
                    for col in missing_columns:
                        print(f"      - Missing: {col}")
                    print(f"  [INFO] Recommended fix: Delete {sqlite_path} and re-run `hardstop run --since 24h`")
                    print(f"        (Migrations are additive, but fresh DB ensures clean schema)")
                else:
                    print("  [OK] Schema is up to date")
            finally:
                conn.close()

            try:
                ensure_raw_items_table(sqlite_path)
                ensure_event_external_fields(sqlite_path)
                ensure_alert_correlation_columns(sqlite_path)
                ensure_trust_tier_columns(sqlite_path)
                ensure_suppression_columns(sqlite_path)
                ensure_source_runs_table(sqlite_path)
                print("  [OK] Migrations applied")
            except Exception as e:
                issues.append(f"Migration error: {e}")
                print(f"  [X] Migration error: {e}")

            try:
                with session_context(sqlite_path) as session:
                    raw_count = session.query(RawItem).count()
                    event_count = session.query(Event).count()
                    alert_count = session.query(Alert).count()

                    print(f"  [OK] raw_items: {raw_count}")
                    print(f"  [OK] events: {event_count}")
                    print(f"  [OK] alerts: {alert_count}")

                    if raw_count > 0:
                        new_count = session.query(RawItem).filter(RawItem.status == "NEW").count()
                        normalized_count = session.query(RawItem).filter(RawItem.status == "NORMALIZED").count()
                        failed_count = session.query(RawItem).filter(RawItem.status == "FAILED").count()
                        suppressed_count = session.query(RawItem).filter(RawItem.suppression_status == "SUPPRESSED").count()
                        print(f"    - NEW: {new_count}, NORMALIZED: {normalized_count}, FAILED: {failed_count}, SUPPRESSED: {suppressed_count}")
                        if new_count > 0:
                            warnings.append(f"{new_count} raw items pending ingestion")
            except Exception as e:
                issues.append(f"Database query error: {e}")
                print(f"  [X] Database query error: {e}")
    except Exception as e:
        issues.append(f"Config/database error: {e}")
        print(f"  [X] Config/database error: {e}")

    # Check 2: sources.yaml is readable
    print("\n[2] Sources Configuration...")
    try:
        sources_config = load_sources_config()
        all_sources = get_all_sources(sources_config)
        enabled_sources = [s for s in all_sources if s.get("enabled", True)]

        print(f"  [OK] Sources config loaded")
        print(f"  [OK] Total sources: {len(all_sources)}")
        print(f"  [OK] Enabled sources: {len(enabled_sources)}")

        tier_counts = {"global": 0, "regional": 0, "local": 0}
        for source in all_sources:
            tier = source.get("tier", "unknown")
            if tier in tier_counts:
                tier_counts[tier] += 1

        print(f"    - Global: {tier_counts['global']}, Regional: {tier_counts['regional']}, Local: {tier_counts['local']}")

        if len(enabled_sources) == 0:
            warnings.append("No enabled sources configured")
    except FileNotFoundError:
        issue_msg = "sources.yaml not found (run `hardstop init` to copy the example config)"
        issues.append(issue_msg)
        print(f"  [X] {issue_msg}")
    except Exception as e:
        issue_msg = (
            f"Sources config error: {e} "
            "(fix the file or run `hardstop init --force` to regenerate from the example)"
        )
        issues.append(issue_msg)
        print(f"  [X] {issue_msg}")

    # Check 3: Network connectivity
    print("\n[3] Network Connectivity...")
    try:
        sources_config = load_sources_config()
        defaults = sources_config.get("defaults", {})
        user_agent = defaults.get("user_agent", "hardstop-agent/0.6")
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json",
        }
        response = requests.get("https://api.weather.gov/alerts/active", headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"  [OK] NWS API: Reachable (status {response.status_code})")
        elif response.status_code == 403:
            print(f"  [WARN] NWS API: Forbidden (status {response.status_code}) - check User-Agent header")
            warnings.append("NWS API returned 403 - verify User-Agent is set correctly")
        else:
            print(f"  [WARN] NWS API: Status {response.status_code}")
            warnings.append(f"NWS API returned status {response.status_code}")
    except requests.RequestException as e:
        warnings.append("Network connectivity test failed (may affect fetching)")
        print(f"  [WARN] NWS API: Connection failed - {e}")

    # Check 4: Suppression configuration
    print("\n[4] Suppression Configuration...")
    try:
        suppression_config = load_suppression_config()
        suppression_enabled = suppression_config.get("enabled", True)
        global_rules = suppression_config.get("rules", [])

        print(f"  [OK] Suppression config loaded")
        print(f"  [OK] Suppression enabled: {'yes' if suppression_enabled else 'no'}")
        print(f"  [OK] Global rules: {len(global_rules)}")

        try:
            sources_config = load_sources_config()
            all_sources = get_all_sources(sources_config)
            per_source_rules_count = 0
            all_rule_ids = set()
            duplicate_rule_ids = set()

            for rule in global_rules:
                rule_id = rule.get("id") if isinstance(rule, dict) else getattr(rule, "id", None)
                if rule_id:
                    if rule_id in all_rule_ids:
                        duplicate_rule_ids.add(rule_id)
                    all_rule_ids.add(rule_id)

            for source in all_sources:
                source_rules = get_suppression_rules_for_source(source)
                per_source_rules_count += len(source_rules)
                for rule in source_rules:
                    rule_id = rule.get("id") if isinstance(rule, dict) else getattr(rule, "id", None)
                    if rule_id:
                        if rule_id in all_rule_ids:
                            duplicate_rule_ids.add(rule_id)
                        all_rule_ids.add(rule_id)

            print(f"  [OK] Per-source rules: {per_source_rules_count} total")
            print(f"  [OK] Total rules: {len(all_rule_ids)}")

            if duplicate_rule_ids:
                warnings.append(f"Duplicate rule IDs found: {', '.join(sorted(duplicate_rule_ids))}")
                print(f"  [WARN] Duplicate rule IDs: {', '.join(sorted(duplicate_rule_ids))}")

            if db_path and db_path.exists():
                try:
                    with session_context(sqlite_path) as session:
                        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                        cutoff_iso = cutoff.isoformat()
                        suppressed_24h = session.query(RawItem).filter(
                            RawItem.suppression_status == "SUPPRESSED",
                            RawItem.suppressed_at_utc >= cutoff_iso,
                        ).count()
                        if suppressed_24h > 0:
                            print(f"  [OK] Suppressed (last 24h): {suppressed_24h}")
                except Exception:
                    pass
        except Exception as e:
            warnings.append(f"Error counting per-source rules: {e}")
            print(f"  [WARN] Error counting per-source rules: {e}")
    except FileNotFoundError:
        print("  [INFO] Suppression config not found (suppression disabled)")
    except Exception as e:
        warnings.append(f"Suppression config error: {e}")
        print(f"  [WARN] Suppression config error: {e}")

    # Check 5: Source health tracking
    print("\n[5] Source Health Tracking...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)

        if not db_path.exists():
            print("  [INFO] Database not found - source health tracking unavailable")
        else:
            conn = sqlite3.connect(sqlite_path)
            try:
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='source_runs';"
                )
                if not cur.fetchone():
                    print("  [INFO] source_runs table not found")
                    print("  [INFO] Recommended: Run 'hardstop fetch' once to initialize source health tracking")
                else:
                    print("  [OK] source_runs table exists")

                    try:
                        sources_config = load_sources_config()
                        configured_sources = [s["id"] for s in get_all_sources(sources_config)]
                    except Exception:
                        configured_sources = None

                    try:
                        with session_context(sqlite_path) as session:
                            health_list = get_all_source_health(
                                session,
                                lookback_n=10,
                                stale_threshold_hours=48,
                                source_ids=configured_sources,
                            )
                            stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                            stale_cutoff_iso = stale_cutoff.isoformat()

                            stale_count = 0
                            for health in health_list:
                                last_success = health.get("last_success_utc")
                                if not last_success or last_success < stale_cutoff_iso:
                                    stale_count += 1

                            if stale_count > 0:
                                warnings.append(f"{stale_count} sources have not succeeded in last 48h")
                                print(f"  [WARN] Stale sources (no success in 48h): {stale_count}")
                            else:
                                print(f"  [OK] All sources healthy (last 48h)")

                            blocked = [h for h in health_list if h.get("health_budget_state") == "BLOCKED"]
                            watch = [h for h in health_list if h.get("health_budget_state") == "WATCH"]
                            if blocked:
                                blocked_ids = ", ".join(h["source_id"] for h in blocked)
                                issues.append(f"{len(blocked)} source(s) exhausted failure budget: {blocked_ids}")
                                print(f"  [X] Failure budget exhausted for: {blocked_ids}")
                            if watch and not blocked:
                                watch_ids = ", ".join(h["source_id"] for h in watch)
                                warnings.append(f"{len(watch)} source(s) near failure budget: {watch_ids}")
                                print(f"  [WARN] Failure budget warning for: {watch_ids}")

                            if health_list:
                                print(f"  [OK] Tracking health for {len(health_list)} sources")
                    except Exception as e:
                        warnings.append(f"Error checking source health: {e}")
                        print(f"  [WARN] Error checking source health: {e}")
            finally:
                conn.close()
    except Exception as e:
        warnings.append(f"Source health check error: {e}")
        print(f"  [WARN] Source health check error: {e}")

    # Check 6: Last run group summary
    print("\n[6] Last Run Group Summary...")
    try:
        config = load_config()
        sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
        db_path = Path(sqlite_path)

        if db_path.exists():
            try:
                with session_context(sqlite_path) as session:
                    most_recent_run = session.query(SourceRun).order_by(SourceRun.run_at_utc.desc()).first()
                    if most_recent_run:
                        run_group_id = most_recent_run.run_group_id
                        print(f"  [INFO] Most recent run_group_id: {run_group_id[:8]}...")

                        group_runs = session.query(SourceRun).filter(
                            SourceRun.run_group_id == run_group_id
                        ).all()

                        fetch_runs = [r for r in group_runs if r.phase == "FETCH"]
                        ingest_runs = [r for r in group_runs if r.phase == "INGEST"]

                        fetch_success = sum(1 for r in fetch_runs if r.status == "SUCCESS")
                        fetch_fail = sum(1 for r in fetch_runs if r.status == "FAILURE")
                        fetch_quiet = sum(1 for r in fetch_runs if r.status == "SUCCESS" and r.items_fetched == 0)

                        ingest_success = sum(1 for r in ingest_runs if r.status == "SUCCESS")
                        ingest_fail = sum(1 for r in ingest_runs if r.status == "FAILURE")

                        total_alerts_touched = sum(r.items_alerts_touched for r in ingest_runs)
                        total_suppressed = sum(r.items_suppressed for r in ingest_runs)

                        print(f"  [INFO] Fetch: {fetch_success} success / {fetch_fail} fail / {fetch_quiet} quiet success")
                        print(f"  [INFO] Ingest: {ingest_success} success / {ingest_fail} fail")
                        if total_alerts_touched > 0:
                            print(f"  [INFO] Alerts touched: {total_alerts_touched}")
                        if total_suppressed > 0:
                            print(f"  [INFO] Suppressed: {total_suppressed}")
                    else:
                        print("  [INFO] No run data available. Run 'hardstop run --since 24h' first.")
            except Exception as e:
                print(f"  [WARN] Error retrieving last run group: {e}")
        else:
            print("  [INFO] Database not found - no run data available")
    except Exception as e:
        print(f"  [WARN] Error checking last run group: {e}")

    # Summary
    print("\n" + "=" * 50)
    if issues:
        print(f"[X] Issues found: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("[OK] No critical issues found")

    if warnings:
        print(f"\n[WARN] Warnings: {len(warnings)}")
        for warning in warnings:
            print(f"  - {warning}")

    if not issues and not warnings:
        print("\n[OK] All checks passed!")

    # What would I do next?
    print("\n" + "=" * 50)
    print("What would I do next?")
    print("-" * 50)

    next_action = None

    if issues:
        for issue in issues:
            if "schema drift" in issue.lower() or "missing" in issue.lower():
                next_action = "Delete hardstop.db and rerun `hardstop run --since 24h`"
                break

    if not next_action:
        for warning in warnings:
            if "stale" in warning.lower():
                try:
                    config = load_config()
                    sqlite_path = config.get("storage", {}).get("sqlite_path", "hardstop.db")
                    with session_context(sqlite_path) as session:
                        health_list = get_all_source_health(session, lookback_n=10)
                        stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                        stale_cutoff_iso = stale_cutoff.isoformat()
                        for health in health_list:
                            last_success = health.get("last_success_utc")
                            if not last_success or last_success < stale_cutoff_iso:
                                source_id = health.get("source_id")
                                if source_id:
                                    next_action = f"Run `hardstop sources test {source_id} --since 72h`"
                                    break
                except Exception:
                    pass
                if not next_action:
                    next_action = "Run `hardstop sources test <id> --since 72h` for stale sources"
                break

    if not next_action:
        for issue in issues:
            if "failed" in issue.lower() and "fetch" in issue.lower():
                next_action = "Check network / user agent / endpoint URLs in config/sources.yaml"
                break

    if not next_action:
        for warning in warnings:
            if "suppression" in warning.lower() and ("invalid" in warning.lower() or "regex" in warning.lower()):
                rule_match = re.search(r'rule[:\s]+([^\s,]+)', warning, re.IGNORECASE)
                if rule_match:
                    rule_id = rule_match.group(1)
                    next_action = f"Fix suppression.yaml regex: {rule_id}"
                else:
                    next_action = "Fix suppression.yaml configuration"
                break

    if not next_action:
        for issue in issues:
            if "config" in issue.lower() or "sources.yaml" in issue.lower():
                next_action = "Fix config/sources.yaml or config/suppression.yaml"
                break

    if not next_action:
        next_action = "System is healthy. Run `hardstop run --since 24h` to fetch and process new data."

    print(f"  \u2192 {next_action}")
    print("=" * 50)
