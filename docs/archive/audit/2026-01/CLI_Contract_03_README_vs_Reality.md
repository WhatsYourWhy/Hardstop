# CLI Contract 03 — README Workflow vs Reality

- **Run date:** 2026-01-01
- **Host OS:** linux 6.1.147 (Ubuntu 24.04 container)
- **Repo branch:** `cursor/WHA-25-readme-workflow-verification-2593`

| README command | Works? | Actual behavior | Exit code | Notes / Fix recommendation |
| --- | --- | --- | --- | --- |
| `hardstop ingest` | Yes (after PATH fix) | Loads network fixtures (7 facilities, 12 lanes, 15 shipments). Initial attempt failed because the `hardstop` binary was not on PATH. | 127 → 0 | README should call out that `pip install -e .` installs scripts in `$HOME/.local/bin`; operators need to add it to PATH or run `python -m hardstop`. |
| `hardstop run --since 24h` | Yes | Fetches 11 items across 6 sources, ingests them into 11 events/alerts, emits quiet-day brief, and reports run status HEALTHY. | 0 | Matches README; outcome is empty brief because no alerts matched the current network. |
| `hardstop brief --today --since 24h` | Yes | Renders a quiet-day brief with no alerts (consistent with upstream run output). | 0 | Consider mentioning in README that empty briefs are normal when no alerts exist. |
| `hardstop sources list` | Yes | Prints 8 configured sources (6 enabled) with tiers, enablement, types, and tags. | 0 | Behavior matches README. |
| `hardstop sources health` | No (initial) → Yes (after fix) | First run crashed with `NameError: name 'Dict' is not defined`. After importing `Dict` from `typing`, the health table renders scores/states for all sources. | 1 → 0 | Bug fixed in `src/hardstop/cli.py` by adding the missing `Dict` import; ensure change lands in mainline. |
| `hardstop sources test nws_active_us --since 72h` | Yes | Fetches 20 items (10 stored) and prints representative titles plus HTTP 200 status. | 0 | README could mention an example source ID (e.g., `nws_active_us`) for new operators. |

