#!/usr/bin/env python3
"""Validate Hardstop RunRecords against the published JSON schema."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


def _load_schema(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Unable to read schema file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Schema file {path} is not valid JSON: {exc}") from exc


def _load_record(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Unable to read RunRecord {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"RunRecord {path} is not valid JSON: {exc}") from exc


def _format_error_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    parts: Iterable[str] = ("$", *map(str, error.absolute_path))
    return ".".join(parts)


def _validate_determinism(record: dict) -> list[str]:
    issues: list[str] = []
    mode = record.get("mode")
    best_effort = record.get("best_effort") or {}
    if best_effort and mode != "best-effort":
        issues.append("best_effort metadata present but mode is not best-effort")
    return issues


def validate_records(records_dir: Path, schema_path: Path, fail_fast: bool) -> int:
    if not records_dir.exists():
        print(f"[hardstop] No RunRecords directory found at {records_dir}", file=sys.stderr)
        return 2

    run_record_files = sorted(records_dir.glob("*.json"))
    if not run_record_files:
        print(f"[hardstop] No RunRecord JSON files found in {records_dir}", file=sys.stderr)
        return 2

    schema = _load_schema(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    total = len(run_record_files)
    failures = 0
    processed = 0
    mode_counts: Counter[str] = Counter()
    records_with_best_effort = 0

    for path in run_record_files:
        processed += 1
        try:
            record = _load_record(path)
        except RuntimeError as exc:
            failures += 1
            print(f"[FAIL] {path}", file=sys.stderr)
            print(f"  - {exc}", file=sys.stderr)
            if fail_fast:
                break
            continue

        mode = record.get("mode", "<missing>")
        mode_counts[mode] += 1
        if record.get("best_effort"):
            records_with_best_effort += 1

        errors: list[str] = []
        try:
            validator.validate(record)
        except ValidationError as exc:
            pointer = _format_error_path(exc)
            errors.append(f"{pointer}: {exc.message}")

        errors.extend(_validate_determinism(record))

        if errors:
            failures += 1
            print(f"[FAIL] {path}", file=sys.stderr)
            for item in errors:
                print(f"  - {item}", file=sys.stderr)
            if fail_fast:
                break

    passed = processed - failures

    print(f"Validated {passed}/{total} RunRecords in {records_dir}")
    if processed != total:
        print(f"  Processed {processed} files before exiting early")
    print(f"  Modes: " + ", ".join(f"{mode}={count}" for mode, count in sorted(mode_counts.items())))
    print(f"  Records with determinism metadata: {records_with_best_effort}")

    return 0 if failures == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RunRecords against the JSON schema.")
    parser.add_argument(
        "--records-dir",
        type=Path,
        default=Path("run_records"),
        help="Directory containing RunRecord *.json files (default: run_records/)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/specs/run-record.schema.json"),
        help="Path to run-record JSON schema",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first validation failure",
    )

    args = parser.parse_args()
    try:
        return validate_records(args.records_dir, args.schema, args.fail_fast)
    except RuntimeError as exc:
        print(f"[hardstop] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
