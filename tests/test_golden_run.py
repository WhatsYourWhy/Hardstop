import hashlib
from pathlib import Path


def test_event_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/event_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "c6e92df540849f40c805a8dd55d7be7979e44284c5faa38c695c716d0b8d731e"
    ), "event_spill.json hash changed; update golden expectation if intentional"


def test_normalized_event_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/normalized_event_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "e44452d1547181c7a14f23eb56fab9f29aa205652f0bc5677db42995b9d94363"
    ), "normalized_event_spill.json hash changed; update golden expectation if intentional"


def test_incident_evidence_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/incident_evidence_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "4857a37c9a5719289b0c25bd57b91375704aa12709425562a56473c6a1c40236"
    ), "incident_evidence_spill.json hash changed; update golden expectation if intentional"
