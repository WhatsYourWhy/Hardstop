from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_CONFIG_PATH = Path("sentinel.config.yaml")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")


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

