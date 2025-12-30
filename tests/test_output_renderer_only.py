"""Tests to enforce output/daily_brief.py is renderer-only."""

import ast
from pathlib import Path


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

