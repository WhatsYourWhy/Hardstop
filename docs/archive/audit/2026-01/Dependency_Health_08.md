# HS-AUDIT-08 — Dependency & Tooling Health

- **Run date:** 2026-01-02
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Repo branch:** `cursor/WHA-34-dependency-pinning-and-reproducibility-dfef`
- **Commit:** _lockfile introduction (see git history for WHA-34)_
- **Python:** 3.12.3
- **Goal:** Verify the newly introduced pinned dependency workflow and ensure the audit path (`pip check`, `pip-audit`, pytest) is reproducible from the lockfile alone.

## Tooling Runs

### 1. Install from the lockfile (runtime + dev)
```bash
python3 -m venv .venv_locked
source .venv_locked/bin/activate
pip install --require-hashes -r requirements.lock.txt
```
**Exit:** 0  
**Notes:** The hashed lockfile covers runtime and dev extras plus `pip-tools`, `pip-audit`, and the interpreter stack (`pip`, `setuptools`, `wheel`). No network drift observed; every wheel matched the recorded hashes.

### 2. Preserve editable workflow
```bash
pip install --no-deps -e .
```
**Exit:** 0  
**Notes:** Editable installs remain supported because they layer on top of the synchronized dependency set without re-resolving requirements.

### 3. Consistency + security checks
```bash
pip check
pip-audit --progress-spinner off
```
**Exit:** 0 for both  
**Notes:** `pip-audit` now runs inside the clean, locked environment so host-level packages (Ansible, system Jinja2, etc.) no longer appear. Result: “No known vulnerabilities found.”

### 4. Full test suite
```bash
pytest
```
**Exit:** 0  
**Notes:** 140 tests pass against the locked environment (runtime parity with previous audit).

## Dependency Inventory Snapshot

| Scope | Spec from `pyproject.toml` | Locked version (`requirements.lock.txt`) | Notes |
|-------|---------------------------|-----------------------------------------|-------|
| Runtime | `pydantic>=2.8.0` | 2.12.5 | Hash-pinned; pyproject spec remains `>=` but the lockfile enforces determinism. |
| Runtime | `SQLAlchemy>=2.0.0` | 2.0.45 | Same pattern—updates require regenerating the lockfile. |
| Runtime | `python-dotenv>=1.0.0` | 1.2.1 | Wheel pinned; no more implicit OS package usage. |
| Runtime | `PyYAML>=6.0.0` | 6.0.3 | Pulled as wheel via lockfile (no distro drift). |
| Runtime | `feedparser>=6.0.0` | 6.0.12 | |
| Runtime | `requests>=2.31.0` | 2.32.5 | |
| Runtime | `us>=3.1.0` | 3.2.0 | Transitively brings in `jellyfish` (also pinned). |
| Dev | `pytest>=8.0.0` | 9.0.2 | Included so CI + contributors get identical tooling. |
| Dev | `pytest-mock>=3.12.0` | 3.15.1 | |
| Dev | `jsonschema>=4.23.0` | 4.25.1 | |
| Dev | `pip-tools>=7.5.0` | 7.5.2 | Enables `pip-sync` + reproducible lock regeneration. |
| Dev | `pip-audit>=2.7.3` | 2.10.0 | Ensures security checks run against repo-owned deps. |
| Build | `setuptools>=78.1.1` | 80.9.0 | Still required by `build-system.requires`; pinned via lockfile too. |

## Findings & Recommendations

1. **Resolved (High) — No pinning or lock file.** Hardstop now ships `requirements.lock.txt`, a hashed artifact produced via `pip-compile --allow-unsafe --extra dev --generate-hashes`. Installing with `pip install --require-hashes -r requirements.lock.txt` yields the exact same wheels on any machine.  
   _Next step:_ Keep the lockfile in sync whenever `pyproject.toml` changes and document the regeneration command (see README).

2. **Resolved (High) — Determinism risk during releases.** Release builds can now depend on the lockfile instead of floating PyPI state. CI should consume the same artifact to ensure replayability between local audits and shared pipelines.

3. **Ongoing (Medium) — Build tooling CVEs.** The build-system floor remains at `setuptools>=78.1.1` and the lockfile pins 80.9.0. Continue monitoring advisories and bump both `pyproject.toml` and the lockfile together when new CVEs surface.

4. **Resolved (Medium) — Security audit noise from host packages.** Running `pip-audit` inside the locked environment produces “No known vulnerabilities found,” eliminating false positives from host-managed packages.

5. **Open (Low) — Missing automated audits.** A GitHub Actions job (or similar) should install via the lockfile, run `pip check`, `pip-audit --progress-spinner off`, and execute `pytest`. This remains recommended follow-up work (HS-10 optional task, HS-11 follow-up).

With these mitigations Hardstop can maintain deterministic, auditable dependency sets while keeping the tooling footprint healthy for day-to-day operations.
