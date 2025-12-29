import hashlib
from pathlib import Path


def test_event_fixture_hash_regression():
    fixture_path = Path("tests/fixtures/event_spill.json")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert (
        digest == "72e81b377b589cf377e6806cbc496faffb4183dce2c07978da310b37dd956da6"
    ), "event_spill.json hash changed; update golden expectation if intentional"
