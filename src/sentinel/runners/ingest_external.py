"""Runner for ingesting external raw items into events and alerts."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from sentinel.alerts.alert_builder import build_basic_alert
from sentinel.config.loader import (
    get_all_sources,
    get_source_with_defaults,
    get_suppression_rules_for_source,
    load_sources_config,
    load_suppression_config,
)
from sentinel.database.event_repo import save_event
from sentinel.database.raw_item_repo import (
    get_raw_items_for_ingest,
    mark_raw_item_status,
    mark_raw_item_suppressed,
)
from sentinel.parsing.network_linker import link_event_to_network
from sentinel.parsing.normalizer import normalize_external_event
from sentinel.suppression.engine import evaluate_suppression
from sentinel.suppression.models import SuppressionRule
from sentinel.utils.logging import get_logger

logger = get_logger(__name__)


def main(
    session: Session,
    limit: Optional[int] = None,
    min_tier: Optional[str] = None,
    source_id: Optional[str] = None,
    since_hours: Optional[int] = None,
    no_suppress: bool = False,
    explain_suppress: bool = False,
) -> Dict[str, int]:
    """
    Main ingestion runner for external raw items.
    
    Processes raw_items with NEW status:
    1. Normalizes to events
    2. Evaluates suppression rules (v0.8)
    3. If suppressed: marks as suppressed and skips alert creation
    4. If not suppressed: persists events, links to network, builds alerts
    5. Updates raw_item status
    
    Args:
        session: SQLAlchemy session
        limit: Maximum number of raw items to process
        min_tier: Minimum tier (global > regional > local)
        source_id: Filter by specific source ID
        since_hours: Only process items fetched within this many hours
        no_suppress: If True, bypass suppression entirely (v0.8)
        explain_suppress: If True, log suppression decisions (v0.8)
        
    Returns:
        Dict with counts: {"processed": N, "events": M, "alerts": K, "errors": E, "suppressed": S}
    """
    # Load sources config for metadata
    sources_config = load_sources_config()
    all_sources = {s["id"]: s for s in get_all_sources(sources_config)}
    
    # Load suppression config (v0.8)
    global_rules: List[SuppressionRule] = []
    if not no_suppress:
        try:
            suppression_config = load_suppression_config()
            if suppression_config.get("enabled", True):
                # Convert dict rules to SuppressionRule models
                for rule_dict in suppression_config.get("rules", []):
                    try:
                        global_rules.append(SuppressionRule(**rule_dict))
                    except Exception as e:
                        logger.warning(f"Invalid suppression rule: {rule_dict.get('id', 'unknown')} - {e}")
        except FileNotFoundError:
            logger.debug("Suppression config not found, skipping suppression")
        except Exception as e:
            logger.warning(f"Error loading suppression config: {e}")
    
    # Get raw items for ingestion
    raw_items = get_raw_items_for_ingest(
        session=session,
        limit=limit,
        min_tier=min_tier,
        source_id=source_id,
        since_hours=since_hours,
    )
    
    logger.info(f"Processing {len(raw_items)} raw items for ingestion")
    
    stats = {
        "processed": 0,
        "events": 0,
        "alerts": 0,
        "errors": 0,
        "suppressed": 0,  # v0.8: suppressed count
    }
    
    for raw_item in raw_items:
        try:
            # Parse raw payload
            payload = json.loads(raw_item.raw_payload_json)
            
            # Build candidate dict
            candidate = {
                "canonical_id": raw_item.canonical_id,
                "title": raw_item.title,
                "url": raw_item.url,
                "published_at_utc": raw_item.published_at_utc,
                "payload": payload,
            }
            
            # Get source config for metadata (with v0.7 defaults applied)
            source_config_raw = all_sources.get(raw_item.source_id, {})
            source_config = get_source_with_defaults(source_config_raw) if source_config_raw else {}
            
            # Normalize to event (injects tier/trust_tier/classification_floor/weighting_bias)
            event = normalize_external_event(
                raw_item_candidate=candidate,
                source_id=raw_item.source_id,
                tier=raw_item.tier,
                raw_id=raw_item.raw_id,
                source_config=source_config,
            )
            
            # Evaluate suppression (v0.8)
            suppressed = False
            if not no_suppress:
                # Get source-specific suppression rules
                source_rules: List[SuppressionRule] = []
                source_suppress_rules = get_suppression_rules_for_source(source_config)
                for rule_dict in source_suppress_rules:
                    try:
                        source_rules.append(SuppressionRule(**rule_dict))
                    except Exception as e:
                        logger.warning(f"Invalid source suppression rule for {raw_item.source_id}: {e}")
                
                # Evaluate suppression
                suppression_result = evaluate_suppression(
                    source_id=raw_item.source_id,
                    tier=raw_item.tier,
                    item=event,
                    global_rules=global_rules,
                    source_rules=source_rules,
                )
                
                if suppression_result.is_suppressed:
                    suppressed = True
                    suppressed_at_utc = datetime.now(timezone.utc).isoformat()
                    
                    # Mark raw item as suppressed
                    mark_raw_item_suppressed(
                        session,
                        raw_item.raw_id,
                        suppression_result.primary_rule_id or "unknown",
                        suppression_result.matched_rule_ids,
                        suppressed_at_utc,
                        "INGEST_EXTERNAL",
                    )
                    
                    # Save event with suppression metadata (but don't create alert)
                    save_event(
                        session,
                        event,
                        suppression_primary_rule_id=suppression_result.primary_rule_id,
                        suppression_rule_ids=suppression_result.matched_rule_ids,
                        suppressed_at_utc=suppressed_at_utc,
                    )
                    session.commit()
                    
                    stats["suppressed"] += 1
                    stats["events"] += 1  # Event is still created for audit
                    
                    if explain_suppress:
                        logger.info(
                            f"Suppressed raw_item {raw_item.raw_id} (rule: {suppression_result.primary_rule_id}, "
                            f"matched: {suppression_result.matched_rule_ids})"
                        )
                    
                    stats["processed"] += 1
                    continue  # Skip alert creation
            
            # Not suppressed - proceed with normal flow
            # Persist event
            save_event(session, event)
            session.commit()
            stats["events"] += 1
            logger.debug(f"Created event {event['event_id']} from raw_item {raw_item.raw_id}")
            
            # Link to network
            event = link_event_to_network(event, session=session)
            
            # Build alert (handles correlation internally)
            alert = build_basic_alert(event, session=session)
            stats["alerts"] += 1
            logger.debug(f"Created/updated alert {alert.alert_id} for event {event['event_id']}")
            
            # Mark raw item as normalized
            mark_raw_item_status(session, raw_item.raw_id, "NORMALIZED")
            session.commit()
            
            stats["processed"] += 1
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process raw_item {raw_item.raw_id}: {error_msg}", exc_info=True)
            try:
                session.rollback()  # Rollback failed transaction
                mark_raw_item_status(session, raw_item.raw_id, "FAILED", error=error_msg)
                session.commit()
            except Exception as rollback_error:
                logger.error(f"Failed to rollback and mark status: {rollback_error}")
                session.rollback()
            stats["errors"] += 1
    
    logger.info(
        f"Ingestion complete: {stats['processed']} processed, "
        f"{stats['events']} events, {stats['alerts']} alerts, "
        f"{stats['suppressed']} suppressed, {stats['errors']} errors"
    )
    
    return stats

