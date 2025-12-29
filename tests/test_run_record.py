import json
from pathlib import Path

import jsonschema

from sentinel.ops.run_record import (
    ArtifactRef,
    Diagnostic,
    emit_run_record,
    fingerprint_config,
)


def test_fingerprint_config_stable():
    snapshot = {
        "runtime": {
            "version": "1.2.3",
            "flags": {"strict": True, "batch_size": 50},
        },
        "sources": {
            "tiers": {
                "global": [
                    {"id": "source-a", "enabled": True},
                    {"enabled": False, "id": "source-b"},
                ]
            }
        },
    }
    expected = "820342a4ce6727751edc1507f62bf997a4bd74fc51cb5dea9163c060ed61d58b"
    assert fingerprint_config(snapshot) == expected


def test_emit_run_record_matches_schema(tmp_path: Path):
    input_ref = ArtifactRef(
        id="run-group-123",
        hash="d2b2ce9d8c9e4fd6958be1c179c3f5f9d7cc696ef7e0f0cc8f71bb5c8a0697ec",
        kind="RunGroup",
    )
    output_ref = ArtifactRef(
        id="run-status-123",
        hash="4f0a9399a1820ca128f61a9bc3dfc1390dca8f700c3687342a1cd87f5f9f8b1d",
        kind="RunStatus",
    )
    warning = Diagnostic(code="WARN001", message="Example warning")
    record = emit_run_record(
        operator_id="sentinel.run@1.0.0",
        mode="strict",
        config_snapshot={"runtime": {"version": "1.0.0"}},
        input_refs=[input_ref],
        output_refs=[output_ref],
        warnings=[warning],
        dest_dir=tmp_path,
    )
    files = list(tmp_path.glob("*.json"))
    assert files, "expected run record file to be created"
    data = json.loads(files[0].read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/specs/run-record.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)
    assert record.config_hash == fingerprint_config({"runtime": {"version": "1.0.0"}})
