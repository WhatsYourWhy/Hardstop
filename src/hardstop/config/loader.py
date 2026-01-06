from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_CONFIG_PATH = Path("hardstop.config.yaml")
DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_SUPPRESSION_PATH = Path("config/suppression.yaml")
DEFAULT_KEYWORDS_PATH = Path("config/keywords.yaml")

ALLOWED_TIERS = ("global", "regional", "local")

BASE_TIER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "global": {
        "trust_tier": 3,
        "classification_floor": 0,
        "weighting_bias": 0,
    },
    "regional": {
        "trust_tier": 2,
        "classification_floor": 0,
        "weighting_bias": 0,
    },
    "local": {
        "trust_tier": 1,
        "classification_floor": 0,
        "weighting_bias": 0,
    },
}


def _merge_tier_defaults(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Resolve tier defaults with built-in fallbacks."""
    user_defaults = config.get("tier_defaults") or {}
    merged: Dict[str, Dict[str, Any]] = {}
    for tier in ALLOWED_TIERS:
        merged[tier] = {
            **BASE_TIER_DEFAULTS.get(tier, {}),
            **(user_defaults.get(tier) or {}),
        }
    # Provide wildcard defaults for unknown tiers to avoid KeyErrors downstream
    merged["*"] = BASE_TIER_DEFAULTS.get("global", {}).copy()
    return merged


def _normalize_source_entry(
    source: Dict[str, Any],
    tier_name: str,
    tier_defaults: Dict[str, Dict[str, Any]],
    global_defaults: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize a single source entry so every CLI path consumes the same schema.
    """
    normalized = deepcopy(source)
    tier = tier_name or normalized.get("tier") or "global"
    normalized["tier"] = tier
    normalized.setdefault("enabled", global_defaults.get("enabled", True))
    normalized.setdefault("max_items_per_fetch", global_defaults.get("max_items_per_fetch"))
    normalized.setdefault("timeout_seconds", global_defaults.get("timeout_seconds"))
    normalized.setdefault("user_agent", global_defaults.get("user_agent"))

    defaults_for_tier = tier_defaults.get(tier) or tier_defaults.get("*", {})
    normalized.setdefault("trust_tier", defaults_for_tier.get("trust_tier", 2))
    normalized.setdefault("classification_floor", defaults_for_tier.get("classification_floor", 0))
    normalized.setdefault("weighting_bias", defaults_for_tier.get("weighting_bias", 0))

    # Ensure tags/geo/suppress fields always have predictable container types
    normalized["tags"] = list(normalized.get("tags", [])) if normalized.get("tags") else []
    normalized["suppress"] = list(normalized.get("suppress", [])) if normalized.get("suppress") else []
    normalized["geo"] = normalized.get("geo", {}) or {}

    return normalized


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
    
    tier_defaults = config.get("tier_defaults")
    if tier_defaults is not None and not isinstance(tier_defaults, dict):
        raise ValueError("Sources config 'tier_defaults' must be a dictionary if provided")
    
    # Validate tiers structure
    tiers = config.get("tiers", {})
    for tier_name in ALLOWED_TIERS:
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
    
    tier_defaults = _merge_tier_defaults(config)
    defaults = config.get("defaults", {})
    
    sources = []
    tiers = config.get("tiers", {})
    for tier_name in ALLOWED_TIERS:
        tier_sources = tiers.get(tier_name, [])
        for source in tier_sources:
            sources.append(_normalize_source_entry(source, tier_name, tier_defaults, defaults))
    
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
    
    normalized = get_all_sources(config)
    return [source for source in normalized if source.get("tier") == tier]


def get_source_with_defaults(source: Dict[str, Any], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
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
    if config is None:
        config = load_sources_config()
    
    tier_defaults = _merge_tier_defaults(config)
    defaults = config.get("defaults", {})
    tier_name = source.get("tier", "global")
    
    return _normalize_source_entry(source, tier_name, tier_defaults, defaults)


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


def load_keywords_config(path: Path | None = None) -> Dict[str, Any]:
    """
    Load risk keyword configuration from YAML.
    
    Returns:
        Dict containing validated keyword definitions.
    """
    cfg_path = path or DEFAULT_KEYWORDS_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Keywords config file not found: {cfg_path}")
    
    with cfg_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    
    if not isinstance(config, dict):
        raise ValueError("Keywords config must be a dictionary")
    
    keywords = config.get("risk_keywords", [])
    if not isinstance(keywords, list):
        raise ValueError("Keywords config 'risk_keywords' must be a list")
    
    normalized_keywords: List[Dict[str, Any]] = []
    for entry in keywords:
        if isinstance(entry, str):
            term = entry
            weight = 1
        elif isinstance(entry, dict):
            term = entry.get("term")
            weight = entry.get("weight", 1)
        else:
            raise ValueError("Each keyword entry must be a string or dictionary")
        
        if not term or not isinstance(term, str):
            raise ValueError("Keyword entry missing 'term'")
        
        if not isinstance(weight, (int, float)):
            raise ValueError("Keyword 'weight' must be numeric")
        
        weight_value = int(float(weight))
        if weight_value < 0:
            weight_value = 0
        
        normalized_keywords.append(
            {
                "term": term.strip().upper(),
                "weight": weight_value,
            }
        )
    
    config["risk_keywords"] = normalized_keywords
    return config


def load_alert_quality_config(config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Load alert quality thresholds from main config.
    
    Returns alert quality settings with safe defaults. These thresholds control
    how network linking confidence affects alert classification to prevent
    false positives from low-confidence matches.
    
    Args:
        config: Optional main config dict. If None, loads from default path.
    
    Returns:
        Dict with alert quality settings:
        - min_confidence_class_1: Minimum facility confidence for "Relevant" alerts (default 0.60)
        - min_confidence_class_2: Minimum facility confidence for "Impactful" alerts (default 0.70)
        - min_confidence_ambiguous: Minimum confidence for ambiguous matches (default 0.50)
        - allow_quality_override_floor: Whether quality validation can override source policy minimum (default True)
    """
    if config is None:
        try:
            config = load_config()
        except FileNotFoundError:
            config = {}
    
    quality_config = config.get("alert_quality", {})
    
    # Safe defaults (conservative)
    return {
        "min_confidence_class_1": float(quality_config.get("min_confidence_class_1", 0.60)),
        "min_confidence_class_2": float(quality_config.get("min_confidence_class_2", 0.70)),
        "min_confidence_ambiguous": float(quality_config.get("min_confidence_ambiguous", 0.50)),
        "allow_quality_override_floor": bool(quality_config.get("allow_quality_override_floor", True)),
    }
