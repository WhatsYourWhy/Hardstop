# Repro Log 02 — CLI Smoke Test

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Repo branch:** `cursor/WHA-24-cli-smoke-test-audit-3f10`
- **Goal:** Validate clean-room install of Hardstop CLI with dev extras and capture `--help`, `init`, and `doctor` behavior.

## Environment Prep & Install

### 1. Create virtual environment (initial attempt)
```bash
python3 -m venv /workspace/.venv_cli_smoke
```
**Exit:** 1  
**Excerpt:**
```
The virtual environment was not created successfully because ensurepip is not
available... apt install python3.12-venv
```

### 2. Install missing system dependency
```bash
sudo apt-get update
```
**Exit:** 0  
**Excerpt:** package lists refreshed from `noble`, `noble-updates`, `noble-security`.

```bash
sudo apt-get install -y python3.12-venv
```
**Exit:** 0  
**Excerpt:** installed `python3.12-venv` plus `python3-pip-whl` and `python3-setuptools-whl`.

### 3. Create virtual environment (retry)
```bash
python3 -m venv /workspace/.venv_cli_smoke
```
**Exit:** 0  
**Excerpt:** *(no output)*

### 4. Activate environment and confirm interpreter
```bash
source /workspace/.venv_cli_smoke/bin/activate
```
**Exit:** 0

```bash
which python
```
**Exit:** 0  
**Excerpt:** `/workspace/.venv_cli_smoke/bin/python`

### 5. Install Hardstop with dev extras
```bash
pip install -e ".[dev]"
```
**Exit:** 0  
**Excerpt:** built editable wheel for `hardstop-agent==0.3.0`; installed deps including `pytest 9.0.2`, `SQLAlchemy 2.0.45`, `pydantic 2.12.5`.

### 6. Capture toolchain versions
```bash
python --version
```
**Exit:** 0  
**Excerpt:** `Python 3.12.3`

```bash
pip --version
```
**Exit:** 0  
**Excerpt:** `pip 24.0 from /workspace/.venv_cli_smoke/... (python 3.12)`

## CLI Smoke Commands

### 7. Help text
```bash
hardstop --help
```
**Exit:** 0  
**Excerpt:** shows top-level commands: `demo`, `incidents`, `ingest`, `sources`, `fetch`, `ingest-external`, `run`, `brief`, `doctor`, `export`, `init`.

### 8. Init
```bash
hardstop init
```
**Exit:** 0  
**Excerpt:**
```
⚠ Skipped 2 file(s):
  - sources.yaml (already exists, use --force to overwrite)
  - suppression.yaml (already exists, use --force to overwrite)
```
**Notes:** No files were written because this repo already tracks the init targets; behavior is documented here so future runs can decide whether to use `--force` or a clean directory.

### 9. Doctor
```bash
hardstop doctor
```
**Exit:** 0  
**Excerpt:**
```
[X] Database not found: hardstop.db
[OK] Sources config loaded (8 total, 6 enabled)
[OK] Suppression config loaded (3 rules)
[INFO] Database not found - source health tracking unavailable

→ System is healthy. Run `hardstop run --since 24h` to fetch and process new data.
```
**Notes:** Since no sqlite DB exists yet, doctor reports one issue but still returns success.

## Created Artifacts

- `/workspace/.venv_cli_smoke` — virtual environment for this smoke session.
- No new config files were emitted because existing `sources.yaml` and `suppression.yaml` caused `hardstop init` to skip writes.

## Follow-ups / Friction

- Clean-room instructions should mention `sudo apt-get install python3.12-venv` (or the appropriate `python3-venv`) requirement; otherwise the first `python3 -m venv` fails on stock Ubuntu containers.
- `hardstop doctor` depends on `hardstop.db`; absence produces an issue banner even though exit code is zero. This is expected but worth noting for first-time operators.

