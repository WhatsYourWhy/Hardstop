from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_CONFIG_PATH = Path("sentinel.config.yaml")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_SUPPRESSION_PATH = Path("config/suppression.yaml")


def load_config(path: Path | None = None) -> Dict[str, Any]:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources_config(path: Path | None = None) -> Dict[str, Any]:
    """
    Load sources configuration from YAML file.
    
    Args:
        path: Optional path to sources.yaml file. Defaults to config/sources.yaml
        
    Returns:
        Dictionary with sources configuration
        
    Raises:
        FileNotFoundError: If sources config file doesn't exist
    """
    cfg_path = path or DEFAULT_SOURCES_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Sources config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Validate structure
    if not isinstance(config, dict):
        raise ValueError("Sources config must be a dictionary")
    if "version" not in config:
        raise ValueError("Sources config must have 'version' field")
    if "tiers" not in config:
        raise ValueError("Sources config must have 'tiers' field")
    
    # Validate tiers structure
    tiers = config.get("tiers", {})
    for tier_name in ["global", "regional", "local"]:
        if tier_name not in tiers:
            continue  # Optional tier
        if not isinstance(tiers[tier_name], list):
            raise ValueError(f"Tier '{tier_name}' must be a list")
        for source in tiers[tier_name]:
            if not isinstance(source, dict):
                raise ValueError(f"Source in tier '{tier_name}' must be a dictionary")
            required_fields = ["id", "type", "tier", "url"]
            for field in required_fields:
                if field not in source:
                    raise ValueError(f"Source in tier '{tier_name}' missing required field: {field}")
    
    return config


def get_all_sources(config: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Get all sources from config, flattened into a single list.
    
    Args:
        config: Optional sources config dict. If None, loads from default path.
        
    Returns:
        List of source dictionaries
    """
    if config is None:
        config = load_sources_config()
    
    sources = []
    tiers = config.get("tiers", {})
    for tier_name in ["global", "regional", "local"]:
        tier_sources = tiers.get(tier_name, [])
        for source in tier_sources:
            # Ensure tier field is set
            source["tier"] = tier_name
            sources.append(source)
    
    return sources


def get_sources_by_tier(tier: str, config: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """
    Get sources for a specific tier.
    
    Args:
        tier: Tier name (global, regional, local)
        config: Optional sources config dict. If None, loads from default path.
        
    Returns:
        List of source dictionaries for the tier
    """
    if config is None:
        config = load_sources_config()
    
    return config.get("tiers", {}).get(tier, [])


def get_source_with_defaults(source: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get source config with v0.7 trust weighting defaults applied.
    
    Defaults:
    - trust_tier: 2 (if absent)
    - classification_floor: 0 (if absent)
    - weighting_bias: 0 (if absent)
    
    Args:
        source: Source dictionary from config
        
    Returns:
        Source dictionary with defaults applied
    """
    result = source.copy()
    
    # Apply defaults for v0.7 fields
    if "trust_tier" not in result:
        result["trust_tier"] = 2
    if "classification_floor" not in result:
        result["classification_floor"] = 0
    if "weighting_bias" not in result:
        result["weighting_bias"] = 0
    
    return result


def load_suppression_config(path: Path | None = None) -> Dict[str, Any]:
    """
    Load suppression configuration from YAML file.
    
    Args:
        path: Optional path to suppression.yaml file. Defaults to config/suppression.yaml
        
    Returns:
        Dictionary with suppression configuration
        
    Raises:
        FileNotFoundError: If suppression config file doesn't exist
        ValueError: If config structure is invalid
    """
    cfg_path = path or DEFAULT_SUPPRESSION_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Suppression config file not found: {cfg_path}")
    
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Validate structure
    if not isinstance(config, dict):
        raise ValueError("Suppression config must be a dictionary")
    if "version" not in config:
        raise ValueError("Suppression config must have 'version' field")
    
    # enabled defaults to True if not present
    if "enabled" not in config:
        config["enabled"] = True
    
    # rules defaults to empty list if not present
    if "rules" not in config:
        config["rules"] = []
    elif not isinstance(config["rules"], list):
        raise ValueError("Suppression config 'rules' must be a list")
    
    return config


def get_suppression_rules_for_source(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract suppression rules from a source config.
    
    Args:
        source: Source dictionary from config
        
    Returns:
        List of suppression rule dictionaries (empty list if none)
    """
    return source.get("suppress", [])

