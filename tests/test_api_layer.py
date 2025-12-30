"""Tests for API layer guardrails and contracts."""

import ast
import importlib.util
from pathlib import Path


def test_api_layer_has_no_sqlalchemy_imports():
    """Test that API layer files don't import SQLAlchemy directly.
    
    Note: TYPE_CHECKING imports are allowed (e.g., `if TYPE_CHECKING: from ..database.schema import Alert`).
    These are only used for type hints and don't cause runtime SQLAlchemy imports.
    """
    api_dir = Path("src/hardstop/api")
    
    # Files to check (exclude __init__.py and README.md)
    api_files = [
        api_dir / "brief_api.py",
        api_dir / "alerts_api.py",
        api_dir / "sources_api.py",
        api_dir / "export.py",
        api_dir / "models.py",
    ]
    
    # Forbidden imports (except Session which is allowed for type hints)
    forbidden_modules = [
        "sqlalchemy",
        "sessionmaker",
        "declarative_base",
    ]
    forbidden_names = [
        "Column",
        "Integer",
        "String",
        "Base",
    ]
    # Session is allowed ONLY for type hints - we'll check usage separately
    
    violations = []
    for api_file in api_files:
        if not api_file.exists():
            continue
        
        # Parse the file
        source = api_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(api_file))
        
        # Track Session imports to verify they're only used in type hints
        session_imports = []
        
        # Check all imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(forbidden in alias.name for forbidden in forbidden_modules + forbidden_names):
                        violations.append(f"{api_file}: direct import '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module and any(forbidden in node.module for forbidden in forbidden_modules):
                    # Check if it's importing Session (allowed for type hints)
                    if node.module == "sqlalchemy.orm" and node.names:
                        all_session = all(alias.name == "Session" for alias in node.names)
                        if all_session:
                            # Only Session imported - allowed for type hints
                            session_imports.append((api_file, node.lineno))
                            continue
                    # Otherwise, it's a violation
                    violations.append(f"{api_file}: direct import from '{node.module}'")
                
                # Check for backdoor: from hardstop.database.schema (should only be in TYPE_CHECKING)
                if node.module == "hardstop.database.schema":
                    # Check if this import is inside a TYPE_CHECKING block by examining source context
                    lines = source.split("\n")
                    line_num = node.lineno - 1  # Convert to 0-based index
                    # Look backwards for TYPE_CHECKING block
                    in_type_checking = False
                    for i in range(max(0, line_num - 10), line_num + 1):
                        if "TYPE_CHECKING" in lines[i] and ("if TYPE_CHECKING:" in lines[i] or "if TYPE_CHECKING" in lines[i]):
                            # Check if this import is indented under the TYPE_CHECKING block
                            import_indent = len(lines[line_num]) - len(lines[line_num].lstrip())
                            type_checking_indent = len(lines[i]) - len(lines[i].lstrip())
                            if import_indent > type_checking_indent:
                                in_type_checking = True
                                break
                    
                    if not in_type_checking:
                        violations.append(f"{api_file}:{node.lineno} imports from hardstop.database.schema outside TYPE_CHECKING block")
                # Check imported names
                if node.names:
                    for alias in node.names:
                        if alias.name in forbidden_names:
                            violations.append(f"{api_file}: direct import '{alias.name}' from '{node.module}'")
    
    # Verify Session is only used in type hints (function parameters with type annotations)
    for api_file, lineno in session_imports:
        source = api_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(api_file))
        
        # Find all uses of Session
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Session":
                # Check if it's in a type annotation (function parameter or return type)
                parent = node
                is_type_hint = False
                for _ in range(5):  # Check up to 5 levels up
                    if parent is None:
                        break
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Check if it's in annotations
                        if node in ast.walk(parent.args) or (isinstance(parent.returns, ast.Name) and parent.returns.id == "Session"):
                            is_type_hint = True
                            break
                    parent = getattr(parent, "parent", None)
                
                if not is_type_hint:
                    violations.append(f"{api_file}: Session used outside type hints (line {node.lineno})")
    
    if violations:
        assert False, f"API layer has SQLAlchemy violations:\n" + "\n".join(violations)
    
        # Also check for direct session.query() calls (even if Session is imported for type hints)
        for api_file in api_files:
            if not api_file.exists():
                continue
        
            source = api_file.read_text(encoding="utf-8")
            # Check for session.query( pattern (direct DB access)
            # But allow if it's in a comment or docstring
            lines = source.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip comments and docstrings
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                # Check for direct DB access patterns
                if "session.query(" in stripped or "session.add(" in stripped or "session.commit(" in stripped:
                    # Check if it's in a string literal
                    if '"' in stripped or "'" in stripped:
                        # Might be in a string - check context
                        if stripped.count('"') >= 2 or stripped.count("'") >= 2:
                            continue
                    assert False, f"{api_file}:{i} has direct session.query/add/commit call (violates rule: API should only call repo functions)"
                
                # Check for .execute( pattern (another direct DB access pattern)
                if ".execute(" in stripped:
                    # Check if it's in a comment or string
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    if '"' in stripped or "'" in stripped:
                        if stripped.count('"') >= 2 or stripped.count("'") >= 2:
                            continue
                    assert False, f"{api_file}:{i} has direct .execute( call (violates rule: API should only call repo functions)"
                
                # Check for runtime sqlalchemy imports (not in TYPE_CHECKING)
                if "from sqlalchemy" in stripped or "import sqlalchemy" in stripped:
                    # Check if it's in a TYPE_CHECKING block
                    if "TYPE_CHECKING" not in source[max(0, i-5):i+1]:  # Check context around this line
                        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                            continue
                        assert False, f"{api_file}:{i} has runtime sqlalchemy import (violates rule: use TYPE_CHECKING for type hints only)"

