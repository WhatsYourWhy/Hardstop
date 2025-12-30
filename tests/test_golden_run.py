import hashlib
from pathlib import Path


def test_event_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/event_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "72e81b377b589cf377e6806cbc496faffb4183dce2c07978da310b37dd956da6"
    ), "event_spill.json hash changed; update golden expectation if intentional"


def test_normalized_event_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/normalized_event_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "4c8538e858ebd1bfa698393fcf595bb4117dadc01892c38b2a80c974117d2f3f"
    ), "normalized_event_spill.json hash changed; update golden expectation if intentional"


def test_incident_evidence_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/incident_evidence_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "90a49be2c3a598ce4ff1b23bdaf4823fc8119a799321eb1fcb90e5e9ed7444f1"
    ), "incident_evidence_spill.json hash changed; update golden expectation if intentional"
