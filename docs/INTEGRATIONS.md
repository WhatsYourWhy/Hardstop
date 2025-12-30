# Connect your tools

Hardstop is intentionally local-first, but it plays well with the rest of your product stack. Use this guide to connect Hardstop runs to collaboration, code, and automation tools so alerts stay in sync with how your team works.

## Source health outputs for integrations

- The `hardstop sources health` table emits `score`, `health_budget_state` (`HEALTHY`, `WATCH`, `BLOCKED`), and `suppression_pct` columns so schedulers or monitors can react to degraded sources.
- The sources API (`src/hardstop/api/sources_api.py`) returns `health_budget_state` for each source; downstream consumers can mirror the CLI gating logic in dashboards or alerting rules.
- To audit noisy rules, run `hardstop sources health --explain-suppress <source_id>` and capture the reason counts + samples as an attachment in your observability tool.

## Slack

Use Slack to broadcast risk alerts and daily briefs.

- **Recommended flow:**
  1) Create an *Incoming Webhook* in Slack and pick a channel for alerts.
  2) Run `hardstop brief --today --format json > /tmp/brief.json` after each pipeline run.
  3) Post highlights to Slack with a small script:
     - Render a short summary (counts, top impacts) from `/tmp/brief.json`.
     - Send it to the webhook URL as a JSON payload.
  4) Add the script to your scheduler (cron, systemd timer, GitHub Action) so Slack stays current.
- **Threading:** Use the alert `correlation.key` as a thread root to keep updates grouped.
- **Rate limiting:** Batch multiple updates into one post per run to avoid noisy channels.

## GitHub / GitLab

Automate Hardstop alongside your CI so code changes and risk signals stay paired.

- **Run on a schedule:** Trigger `hardstop run --since 24h` in a scheduled workflow to fetch and ingest events.
- **Attach artifacts:** Save `hardstop brief --today --format md` as a build artifact for reviewers.
- **Status visibility:** Fail the job on exit code `2` (broken) and mark it as *warning* for exit code `1` so maintainers see data quality issues.
- **Config versioning:** Keep `config/` under version control and require review for changes to suppression rules or source definitions.

## Agents

If you use AI agents or automation runners, treat Hardstop as the deterministic layer and let the agent handle outreach.

- Use the brief JSON output as the agent's context window and have it decide who to notify.
- Allow agents to call `hardstop sources test <id>` for diagnostics, but gate database writes behind human approval.
- Cache agent prompts with the Hardstop version and config commit so responses are reproducible.

## Integration directory

Hardstop itself avoids SaaS lock-in, so choose the right connector for your stack:

- **Notifications:** Slack, Microsoft Teams, email (SMTP).
- **Work management:** Linear, Jira, Asana — create issues from high-impact alerts.
- **Data sync:** Airflow/Prefect or GitHub Actions to orchestrate `hardstop run` and `hardstop brief` on a schedule.
- **Storage:** Keep SQLite on local disk; mirror to cloud storage only if your policies allow it.

## Linear API (optional)

To mirror high-impact alerts into Linear:

1) Create a Linear API key with access to the target team.
2) Map Hardstop classifications to Linear priority (e.g., class 2 → P1, class 1 → P2).
3) Script a small bridge:
   - Query `hardstop brief --today --format json`.
   - For each `top` alert, upsert a Linear issue keyed by `correlation.key`.
   - Add facilities/lanes/shipments to the issue description for context.
4) Run the bridge after each successful `hardstop run`.

### Set Hardstop as the repo of record

Linear’s GitHub integration and API both accept a repository hint so downstream
automation knows where the issue originated. Make sure Hardstop is the default:

1. **Connect the repo once:** Linear → Settings → Integrations → GitHub →
   select the `hardstop` repository so link-backs resolve automatically.
2. **Pass the repo in your bridge:** When you call the Linear GraphQL API,
   include metadata so future tooling can filter issues:

```
{
  "query": "mutation IssueCreate($input: IssueCreateInput!) { issueCreate(input: $input) { issue { id } } }",
  "variables": {
    "input": {
      "teamId": "<team-id>",
      "title": "[hardstop] {{ alert.title }}",
      "description": "{{ alert.summary }}",
      "metadata": {
        "repo": "hardstop",
        "source": "hardstop-brief"
      }
    }
  }
}
```

If you rely on Linear’s built-in GitHub sync, the metadata step is still useful
because it stays visible even when a human edits the issue later—everything
originating from Hardstop shares the same `repo: hardstop` tag.

## Quick checklist

- [ ] Decide where alerts live (Slack channel, Linear team, GitHub PR comment, etc.).
- [ ] Schedule `hardstop run` + `hardstop brief` at the cadence your team needs.
- [ ] Post summaries, not raw logs — keep channels signal-rich.
- [ ] Track runs with exit codes: `0` healthy, `1` warning, `2` broken.
- [ ] Version-control your configs so integrations stay reproducible.
