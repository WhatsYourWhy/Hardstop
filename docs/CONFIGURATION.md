# Configuration Reference

## Source Configuration (`config/sources.yaml`)

Define external sources with metadata. Defaults are layered:

- `defaults`: HTTP/client behavior (timeout, max items, user agent).
- `tier_defaults`: trust-aware tuning for each tier (global, regional, local) that sets `trust_tier`, `classification_floor`, and `weighting_bias`.
- Per-source overrides: anything specified on the source wins over tier defaults.

### Source fields

- **id**: Unique source identifier
- **type**: Source adapter type (`rss`, `nws_alerts`)
- **tier**: `global`, `regional`, or `local`
- **url**: Source endpoint URL
- **enabled**: Whether source is active
- **trust_tier**: Reliability tier (1-3, default 2)
  - Tier 3: High trust (official sources) — +1 impact score
  - Tier 2: Medium trust (default) — no modifier
  - Tier 1: Low trust — -1 impact score
- **classification_floor**: Minimum alert classification (0-2, default 0). Quality validation may reduce classification below this floor to prevent false positives (Policy B).
- **weighting_bias**: Impact score adjustment (-2 to +2, default 0)
- **suppress**: Per-source suppression rules

### Example

```yaml
tier_defaults:
  global:
    trust_tier: 3
    classification_floor: 0
    weighting_bias: 0
  regional:
    trust_tier: 2
  local:
    trust_tier: 1
    weighting_bias: -1

tiers:
  global:
    - id: nws_active_us
      type: nws_alerts
      enabled: true
      tier: global
      url: "https://api.weather.gov/alerts/active"
      trust_tier: 3
```

## Suppression Configuration (`config/suppression.yaml`)

Define global suppression rules to filter noise:

- **enabled**: Master switch for suppression
- **rules**: List of suppression rules
  - **id**: Unique rule identifier
  - **kind**: Match type (`keyword`, `regex`, `exact`)
  - **field**: Field to match (`title`, `summary`, `raw_text`, `url`, `event_type`, `source_id`, `tier`, `any`)
  - **pattern**: Pattern to match
  - **case_sensitive**: Whether matching is case-sensitive
  - **note**: Human-readable note
  - **reason_code**: Short code for reporting

### Example

```yaml
enabled: true
rules:
  - id: global_test_alerts
    kind: keyword
    field: any
    pattern: "test alert"
    case_sensitive: false
    note: "Common noise across multiple feeds"
```

## Alert Quality Configuration (`hardstop.config.yaml`)

Controls how network linking confidence affects alert classification.

- **min_confidence_class_1**: Minimum facility confidence for "Relevant" alerts (default 0.60)
- **min_confidence_class_2**: Minimum facility confidence for "Impactful" alerts (default 0.70)
- **min_confidence_ambiguous**: Minimum confidence for ambiguous facility matches (default 0.50)
- **allow_quality_override_floor**: Whether quality validation can override source policy minimum (default true, Policy B)

### Example

```yaml
alert_quality:
  min_confidence_class_1: 0.60
  min_confidence_class_2: 0.70
  min_confidence_ambiguous: 0.50
  allow_quality_override_floor: true
```

### How quality validation works

- Events with low facility confidence (< 0.60) are capped at classification 0
- Ambiguous facility matches are capped at classification 1, requiring 2+ compensating factors
- Classification 2 requires both high confidence (>= 0.70) and 2+ high-impact factors
- Quality validation metadata is exposed in `alert.evidence.diagnostics.quality_validation`

## CSV Data Format

See [CSV_CONTRACT.md](CSV_CONTRACT.md) for the network data format (facilities, lanes, shipments).
