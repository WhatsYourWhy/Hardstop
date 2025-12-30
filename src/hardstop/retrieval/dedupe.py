"""Deduplication logic for raw items."""

import hashlib
import json
from typing import Dict, Optional


def compute_content_hash(candidate: Dict) -> str:
    """
    Compute SHA256 hash of stable fields for deduplication.
    
    Args:
        candidate: RawItemCandidate dict or similar structure
        
    Returns:
        SHA256 hash as hex string
    """
    # Stable fields for hashing (exclude timestamps that might vary)
    stable_fields = {
        "canonical_id": candidate.get("canonical_id"),
        "title": candidate.get("title"),
        "url": candidate.get("url"),
    }
    
    # Include payload content if available
    payload = candidate.get("payload", {})
    if payload:
        # Extract key content fields
        content_fields = {
            "title": payload.get("title"),
            "summary": payload.get("summary"),
            "description": payload.get("description"),
            "content": payload.get("content"),
        }
        stable_fields["payload_content"] = content_fields
    
    # Sort keys for consistent hashing
    stable_json = json.dumps(stable_fields, sort_keys=True, default=str)
    return hashlib.sha256(stable_json.encode("utf-8")).hexdigest()


def get_dedupe_key(source_id: str, candidate: Dict) -> tuple[Optional[str], Optional[str]]:
    """
    Get deduplication key for a candidate.
    
    Returns:
        Tuple of (canonical_id, content_hash)
        - canonical_id: If available, use this as primary key
        - content_hash: Fallback hash for deduplication
    """
    canonical_id = candidate.get("canonical_id")
    content_hash = compute_content_hash(candidate)
    
    return (canonical_id, content_hash)


def is_duplicate(
    source_id: str,
    candidate: Dict,
    existing_canonical_ids: set[str],
    existing_content_hashes: set[str],
) -> bool:
    """
    Check if a candidate is a duplicate based on existing items.
    
    Args:
        source_id: Source ID
        candidate: RawItemCandidate dict
        existing_canonical_ids: Set of existing canonical IDs for this source
        existing_content_hashes: Set of existing content hashes for this source
        
    Returns:
        True if duplicate, False otherwise
    """
    canonical_id, content_hash = get_dedupe_key(source_id, candidate)
    
    # Primary check: canonical_id
    if canonical_id and canonical_id in existing_canonical_ids:
        return True
    
    # Fallback check: content_hash
    if content_hash in existing_content_hashes:
        return True
    
    return False

