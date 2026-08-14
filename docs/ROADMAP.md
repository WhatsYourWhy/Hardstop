# Roadmap

Where Hardstop is, what is deliberately deferred, and what to pick up next.

This file is the durable record of intent. If you are returning to the project
cold, read this first, then `CHANGELOG.md` for what actually shipped.

**Status:** v1.3 provenance hardening landed 2026-08-14 (PRs #104, #105).
The supply-chain v1 core remains frozen: behavior changes to classification,
impact score, scope, correlation, or suppression require a v1.x or v2 proposal.

---

## Next up: alert commit, version, and dependency layer

**The single highest-value change, and the reason v1.3 was scoped the way it
was.** v1.3 made inputs and outputs traceable. This makes the *decision* itself
transactional.

### The problem

`build_basic_alert()` in `src/hardstop/alerts/alert_builder.py` does three
different jobs in one function: it constructs the alert, applies quality caps
and correlation, and writes and commits the database row (`session.commit()` at
the create and update branches). There is no verification boundary between
calculation and authoritative persistence.

Consequences today:

- Correlated alerts are **mutated in place**. Summary, classification, scope and
  diagnostics are overwritten. `root_event_ids_json` preserves coarse
  provenance, but there is no way to tell which prior field value came from
  which event, which blocks exact dependency repair.
- `Alert.status` (`OPEN` / `UPDATED`) is a lifecycle state, not a commit state.
  There is no `PROPOSED` / `VERIFIED` / `REVIEW_REQUIRED` / `BLOCKED` /
  `COMMITTED` / `INVALIDATED` / `SUPERSEDED`.
- Incident evidence is written to disk *after* the database commit, so a
  filesystem failure can leave a committed alert with no evidence artifact.

### The shape

1. Split `build_basic_alert()` into three functions with strict rules:
   `build_alert_candidate()` (no DB writes), `evaluate_alert_candidate()`
   (no DB writes), `commit_alert_candidate()` (owns the whole transaction).
   `alert_builder.py` stops calling `session.commit()` internally; the ingest
   runner owns transaction boundaries.
2. Add immutable `alert_versions`, plus `alert_candidates`,
   `verification_verdicts` and `artifact_dependencies`. The existing `alerts`
   table stays as the current-state projection, for API compatibility.
3. Build the canonical IncidentEvidence payload in memory, hash it, store it
   *inside* the same transaction as the alert version, and write
   `output/incidents/*.json` afterwards as a derived artifact that can be
   regenerated from the stored payload.

Use the existing additive migration pattern in `database/migrate.py` (see
`ensure_run_raw_items_table` for the v1.3 example), and keep the existing
`config_hash` rather than introducing a separate policy hash.

### Acceptance test

The bounded test that exercises the whole layer at once:

> Given a committed Hardstop brief and a later-invalidated source, the system
> must identify every dependent claim, preserve claims with independent
> support, block affected exports, generate a superseding brief, and reproduce
> the same control decisions from the captured `RunRecord`.

### Before starting

This lands on the frozen v1 decision path, so plan it before writing code. The
guard rails that matter: building a candidate must perform zero database
writes; existing `alerts` API results must equal the latest committed
alert-version projection; and the pinned demo replay
(`tests/test_demo_pipeline.py`) must still produce identical alert IDs and
artifact hashes.

---

## Known limitations from v1.3

Each of these was a deliberate scope decision, not an oversight.

| Limitation | Follow-up |
|---|---|
| The publication gate covers the `hardstop run` pipeline only; a standalone `hardstop brief --today` is ungated | Have `cmd_brief` call `evaluate_readiness()` itself when no `publication` is passed in, with `cmd_run` passing its result to avoid double computation |
| A `BLOCKED` source still fetches, ingests and produces alerts; only publication is gated | Gating alert creation changes frozen v1 decision behavior. Needs a v1.x proposal, or a config flag defaulting to current behavior |
| Evidence hash verification hard-fails only in strict mode | Consider `--allow-unverified-evidence`, or keep brief-side verification warn-only permanently and leave hard-fail to `incidents replay` |

## Smaller hardening, unscheduled

Real but low-urgency. Fold into adjacent work rather than scheduling.

- **SQLite pragmas.** `database/sqlite_client.py` creates a plain engine: no
  WAL, no `foreign_keys`, no `busy_timeout`. No `ForeignKey` constraints are
  declared in `schema.py` either.
- **`create_all` on every session.** `get_session()` / `session_context()` each
  construct a new engine and re-run `Base.metadata.create_all`. This is also why
  the v1.3 batch-digest fallback keys off row count rather than table existence.
- **Silent provenance downgrade.** `_safe_raw_batch_hash` and
  `_safe_source_runs_hash` in `cli/_helpers.py` fall back to a count-only hash
  on any exception, logged at `debug`. Raising that to `warning` is a one-line
  change.
- **Tests write into the real `output/incidents/`** rather than `tmp_path`,
  accumulating artifacts in a working tree.
- **`config/sources.yaml` is untracked**, so a fresh clone has only the
  `.example`. Several tests depend on the real file existing.

## Deferred until Hardstop performs external actions

The Brief v2 spec defines integrations as read-only and excludes push execution,
so these have no execution path to protect yet: action receipts, idempotency
keys, authorization-consumption tracking, compensating actions, and
transactional rollback for third-party tools.

Likewise deferred until LLM-generated prose enters the authoritative output
path: atomic claim extraction, a claim ledger, an isolated model verifier, and a
human review queue. The current decision path is deterministic and structured;
it does not generate free-form factual prose, so claim-level controls would add
substantial machinery ahead of need. When prose does arrive, the deterministic
system should keep owning entity links, scope, impact score, classification,
source health, correlation key and the commit decision.

## v2 decision model

- Separate source credibility from impact score. Trust tier currently adjusts
  `impact_score` directly (tier 3 `+1`, tier 1 `-1`, manual bias `-2`..`+2`),
  so source credibility changes the calculated business impact of the same
  physical event. In v2, physical and business consequence should determine
  impact; source authority should determine evidence admissibility and review
  routing. Preserve current behavior in v1.x for compatibility.
- Dependency invalidation and supersession commands.
- CLI human review (`hardstop review list|show|approve|reject`), once the
  candidate table exists and there is real review traffic to measure.
