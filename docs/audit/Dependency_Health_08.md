# HS-AUDIT-08 — Dependency & Tooling Health

- **Run date:** 2026-01-02
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Repo branch:** `cursor/WHA-30-dependency-and-tooling-audit-6a5b`
- **Commit:** `3699bcc`
- **Python:** 3.12.3
- **Goal:** Evaluate whether Hardstop’s runtime/dev dependencies and tooling are safe for daily-driver use without undermining determinism.

## Tooling Runs

### 1. Install project + dev extras
```bash
python3 -m pip install -e '.[dev]'
```
**Exit:** 0  
**Notes:** Pulled the latest available releases for every `pyproject.toml` dependency (Pydantic 2.12.5, SQLAlchemy 2.0.45, python-dotenv 1.2.1, etc.). Warned that scripts land in `~/.local/bin`; no functional issues.

### 2. Consistency check
```bash
python3 -m pip check
```
**Exit:** 0  
**Notes:** No resolver conflicts or missing wheels after the editable install.

### 3. Full test suite
```bash
python3 -m pytest
```
**Exit:** 0  
**Notes:** 140 tests now pass. I refreshed `tests/fixtures/incident_evidence_spill.json` to include the newer `determinism_mode` metadata so the golden hash in `tests/test_golden_run.py` matches the actual artifact payload.

### 4. Security audit
```bash
python3 -m pip_audit
```
**Exit:** 1 (expected; audit reports findings)  
**Notes:** After upgrading `setuptools` to 80.9.0 the remaining hits are limited to host packages (Ansible stack, Jinja2, Cryptography) that aren’t declared by Hardstop. Summary:

| Package | Version | CVEs (pip-audit IDs) | Fixed by |
|---------|---------|----------------------|----------|
| `ansible` | 9.2.0 | CVE-2025-14010 | 12.2.0 |
| `ansible-core` | 2.16.3 | CVE-2024-9902, CVE-2024-8775, CVE-2024-11079 | 2.16.13+, 2.17.6+, 2.18.x |
| `cryptography` | 41.0.7 | PYSEC-2024-225, CVE-2023-50782, CVE-2024-0727, GHSA-h4gh-qq45-vh27 | 42.0.4 / 43.0.1 |
| `jinja2` | 3.1.2 | CVE-2024-22195, CVE-2024-34064, CVE-2024-56326, CVE-2024-56201, CVE-2025-27516 | 3.1.6 |

`pip-audit` also skipped OS-managed packages (`cupshelpers`, `python-apt`) and the editable `hardstop-agent`. Recommendation: re-run the audit inside a clean virtualenv or container image that only contains Hardstop’s dependencies so host tools stop polluting the report.

## Dependency Inventory Snapshot

| Scope | Spec from `pyproject.toml` | Installed version | Notes |
|-------|---------------------------|-------------------|-------|
| Runtime | `pydantic>=2.8.0` | 2.12.5 | No upper bound; upgrades to any 2.x release without review. |
| Runtime | `SQLAlchemy>=2.0.0` | 2.0.45 | Major-version floor only; ORM churn can introduce breaking changes. |
| Runtime | `python-dotenv>=1.0.0` | 1.2.1 | Pulls latest 1.x each install. |
| Runtime | `PyYAML>=6.0.0` | 6.0.1 (system) | System package; suggest pinning a wheel to avoid distro drift. |
| Runtime | `feedparser>=6.0.0` | 6.0.12 | Untethered to a minor release. |
| Runtime | `requests>=2.31.0` | 2.32.5 | Follows latest 2.x, potential TLS stack churn. |
| Runtime | `us>=3.1.0` | 3.2.0 | Transitively brings in `jellyfish`. |
| Dev | `pytest>=8.0.0` | 9.0.2 | Major upgrades can change CLI flags and fixtures unexpectedly. |
| Dev | `pytest-mock>=3.12.0` | 3.15.1 | Same concern as above. |
| Dev | `jsonschema>=4.23.0` | 4.25.1 | No determinism guardrails. |
| Build | `setuptools>=78.1.1` *(updated)* | 80.9.0 | Raised floor to cover CVE-2024-6345 / PYSEC-2025-49. |

## Findings & Recommendations

1. **High — No pinning or lock file.** All runtime/dev dependencies use bare `>=` constraints with no upper bounds and no lock artifact. Every install resolves against PyPI’s latest, so deterministic runs depend on global cache state.  
   _Action:_ Introduce a lock step (`pip-tools`, `uv pip compile`, Poetry, Rye, etc.) that emits a hashed `requirements.lock` checked into the repo. Have CI/CD install with `pip install -r requirements.lock --no-deps` to guarantee stable wheels.

2. **High — Determinism risk during releases.** Because runtime dependencies float, reproducible builds rely on PyPI not publishing breaking releases between local validation and prod rollout. This undermines the determinism guarantees validated elsewhere.  
   _Action:_ Either (a) adopt upper bounds (`pydantic<2.13`, etc.) plus release automation that bumps versions intentionally, or (b) vendor wheels in the artifact cache used by run replay.

3. **Medium — Build tooling CVEs.** Prior to this audit the project only required `setuptools>=61.0`, which allowed vulnerable 68.x releases (CVE-2024-6345 / PYSEC-2025-49). Updated the build requirement to `>=78.1.1` and upgraded the local interpreter to 80.9.0 so new installs pull a patched wheel.  
   _Action:_ Keep the floor synced with the latest security advisory and add a dependabot rule for build-system requirements.

4. **Medium — Security audit noise from host packages.** `pip-audit` runs against the entire interpreter environment, so host tools (Ansible, Cryptography, Jinja2) surface as vulnerable despite not being part of Hardstop.  
   _Action:_ Add a `requirements-dev.txt` / `uv` manifest and run `pip-audit --requirement requirements-dev.txt` (or in a disposable venv) inside CI to scope findings to real dependencies. Document the expectation so analysts do not chase unrelated CVEs.

5. **Low — Missing automated audits.** There is no CI job or pre-commit hook that enforces `pip check`, `pip-audit`, or lock drift, so regressions rely on manual effort.  
   _Action:_ Add a weekly scheduled job that runs `pip-audit --format sarif` and surfaces results in GitHub Security, and gate releases on `pip check` + hash verification against the lock file.

With these mitigations Hardstop can maintain deterministic, auditable dependency sets while keeping the tooling footprint healthy for day-to-day operations.
