"""Tests to enforce output/daily_brief.py is renderer-only."""

import ast
from pathlib import Path

from hardstop.output.daily_brief import render_markdown


def test_daily_brief_is_renderer_only():
    """Test that output/daily_brief.py does not import repos or SQLAlchemy schema.
    
    This enforces the "renderer-only" rule: output/daily_brief.py should only:
    - Call api.brief_api.get_brief()
    - Render the result (markdown/JSON)
    - Use Session type hints (for compatibility wrapper)
    """
    daily_brief_file = Path("src/hardstop/output/daily_brief.py")
    
    if not daily_brief_file.exists():
        return  # Skip if file doesn't exist
    
    source = daily_brief_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(daily_brief_file))
    
    violations = []
    
    # Check all imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Check for repo imports
                if "database" in alias.name and ("repo" in alias.name or "schema" in alias.name):
                    violations.append(f"Direct import of '{alias.name}' (should use api layer)")
        
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # Check for repo imports
                if node.module and "database" in node.module:
                    if "_repo" in node.module or node.module.endswith(".schema"):
                        violations.append(f"Import from '{node.module}' (should use api layer)")
                
                # Check for SQLAlchemy schema imports
                if node.module == "hardstop.database.schema":
                    violations.append(f"Import from hardstop.database.schema (should use api layer)")
    
    # Check for direct DB access patterns in source
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and docstrings
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        
        # Check for session.query(, session.add(, session.commit(
        if "session.query(" in stripped or "session.add(" in stripped or "session.commit(" in stripped:
            # Check if it's in a string literal
            if '"' in stripped or "'" in stripped:
                if stripped.count('"') >= 2 or stripped.count("'") >= 2:
                    continue
            violations.append(f"Line {i}: Direct DB access pattern (should use api layer)")
        
        # Check for .execute( pattern
        if ".execute(" in stripped:
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if '"' in stripped or "'" in stripped:
                if stripped.count('"') >= 2 or stripped.count("'") >= 2:
                    continue
            violations.append(f"Line {i}: Direct DB execute pattern (should use api layer)")
    
    # Allow: api.brief_api.get_brief() calls
    # Allow: Session type hints (for generate_brief compatibility wrapper)
    # Allow: Standard library imports
    
    if violations:
        assert False, (
            f"output/daily_brief.py violates renderer-only rule:\n" +
            "\n".join(f"  - {v}" for v in violations) +
            "\n\nRenderer should only call api.brief_api.get_brief() and render the result."
        )


def test_render_markdown_surfaces_evidence_summary():
    """Ensure renderer surfaces incident evidence summaries without DB access."""
    alert = {
        "alert_id": "ALERT-1",
        "classification": 2,
        "impact_score": 9,
        "summary": "Spill affecting primary lane",
        "correlation": {"key": "SPILL|FAC-1|LANE-1", "action": "CREATED", "alert_id": "ALERT-1"},
        "scope": {"facilities": ["FAC-1"], "lanes": ["LANE-1"], "shipments": [], "shipments_total_linked": 0, "shipments_truncated": False},
        "first_seen_utc": "2024-05-01T00:00:00Z",
        "last_seen_utc": "2024-05-01T00:00:00Z",
        "update_count": 0,
        "tier": "global",
        "trust_tier": 2,
        "evidence_summary": {
            "merge_summary": ["Existing alert seen within 168h window", "Shared facilities: FAC-1"],
            "artifact_hash": "abc123",
        },
    }
    brief_data = {
        "read_model_version": "brief.v1",
        "generated_at_utc": "2024-05-02T00:00:00Z",
        "window": {"since": "24h", "since_hours": 24},
        "counts": {"new": 1, "updated": 0, "impactful": 1, "relevant": 0, "interesting": 0},
        "tier_counts": {"global": 1, "regional": 0, "local": 0, "unknown": 0},
        "top": [alert],
        "updated": [],
        "created": [alert],
        "suppressed": {"count": 0, "by_rule": [], "by_source": []},
        "suppressed_legacy": {"total_queried": 1, "limit_applied": 20},
    }

    markdown = render_markdown(brief_data)
    assert "Evidence: Existing alert seen within 168h window; Shared facilities: FAC-1" in markdown


def test_render_markdown_with_missing_unknown_tier_count():
    """Ensure renderer handles tier_counts without an unknown entry."""
    brief_data = {
        "read_model_version": "brief.v1",
        "generated_at_utc": "2024-05-02T00:00:00Z",
        "window": {"since": "24h", "since_hours": 24},
        "counts": {"new": 1, "updated": 0, "impactful": 0, "relevant": 1, "interesting": 0},
        "tier_counts": {"global": 2, "regional": 1, "local": 0},  # missing unknown key
        "top": [],
        "updated": [],
        "created": [],
        "suppressed": {"count": 0, "by_rule": [], "by_source": []},
        "suppressed_legacy": {"total_queried": 1, "limit_applied": 20},
    }

    markdown = render_markdown(brief_data)

    assert "- **Tier:** Global 2 | Regional 1" in markdown
