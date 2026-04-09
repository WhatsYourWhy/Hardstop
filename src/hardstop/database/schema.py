from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Facility(Base):
    __tablename__ = "facilities"

    facility_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    lat = Column(Float)
    lon = Column(Float)
    criticality_score = Column(Integer)


class Lane(Base):
    __tablename__ = "lanes"

    lane_id = Column(String, primary_key=True)
    origin_facility_id = Column(String, nullable=False)
    dest_facility_id = Column(String, nullable=False)
    mode = Column(String)
    carrier_name = Column(String)
    avg_transit_days = Column(Float)
    volume_score = Column(Integer)


class Shipment(Base):
    __tablename__ = "shipments"

    shipment_id = Column(String, primary_key=True)
    order_id = Column(String)
    lane_id = Column(String, nullable=False)
    sku_id = Column(String)
    qty = Column(Float)
    status = Column(String)
    ship_date = Column(String)
    eta_date = Column(String)
    customer_name = Column(String)
    priority_flag = Column(Integer)


class RawItem(Base):
    __tablename__ = "raw_items"

    raw_id = Column(String, primary_key=True)
    source_id = Column(String, nullable=False, index=True)
    tier = Column(String, nullable=False)
    fetched_at_utc = Column(String, nullable=False)
    published_at_utc = Column(String, nullable=True)
    canonical_id = Column(String, nullable=True, index=True)
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    raw_payload_json = Column(Text, nullable=False)
    content_hash = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="NEW")
    error = Column(Text, nullable=True)
    trust_tier = Column(Integer, nullable=True)
    suppression_status = Column(String, nullable=True)
    suppression_primary_rule_id = Column(String, nullable=True)
    suppression_rule_ids_json = Column(Text, nullable=True)
    suppressed_at_utc = Column(String, nullable=True)
    suppression_stage = Column(String, nullable=True)
    suppression_reason_code = Column(String, nullable=True)


class Event(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)
    source_name = Column(String)
    source_id = Column(String, nullable=True, index=True)
    raw_id = Column(String, nullable=True, index=True)
    title = Column(String)
    raw_text = Column(Text)
    event_type = Column(String)
    event_time_utc = Column(String, nullable=True)
    severity_guess = Column(Integer)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    location_hint = Column(Text, nullable=True)
    entities_json = Column(Text, nullable=True)
    event_payload_json = Column(Text, nullable=True)
    trust_tier = Column(Integer, nullable=True)
    suppression_primary_rule_id = Column(String, nullable=True)
    suppression_rule_ids_json = Column(Text, nullable=True)
    suppressed_at_utc = Column(String, nullable=True)
    suppression_reason_code = Column(String, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True)
    summary = Column(Text, nullable=False)
    risk_type = Column(String, nullable=False)
    classification = Column(Integer, nullable=False)
    priority = Column(Integer, nullable=True)  # Deprecated: use classification
    status = Column(String, nullable=False)
    root_event_id = Column(String, nullable=False)
    reasoning = Column(Text)
    recommended_actions = Column(Text)
    
    correlation_key = Column(String, nullable=True, index=True)
    correlation_action = Column(String, nullable=True)
    first_seen_utc = Column(String, nullable=True)
    last_seen_utc = Column(String, nullable=True)
    update_count = Column(Integer, nullable=True)
    root_event_ids_json = Column(Text, nullable=True)
    impact_score = Column(Integer, nullable=True)
    scope_json = Column(Text, nullable=True)
    tier = Column(String, nullable=True)
    source_id = Column(String, nullable=True, index=True)
    trust_tier = Column(Integer, nullable=True)
    diagnostics_json = Column(Text, nullable=True)


class SourceRun(Base):
    __tablename__ = "source_runs"

    run_id = Column(String, primary_key=True)
    run_group_id = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False, index=True)
    phase = Column(String, nullable=False, index=True)
    run_at_utc = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)
    status_code = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    items_fetched = Column(Integer, nullable=False, default=0)
    items_new = Column(Integer, nullable=False, default=0)
    items_processed = Column(Integer, nullable=False, default=0)
    items_suppressed = Column(Integer, nullable=False, default=0)
    items_events_created = Column(Integer, nullable=False, default=0)
    items_alerts_touched = Column(Integer, nullable=False, default=0)
    diagnostics_json = Column(Text, nullable=True)
    
    __table_args__ = (
        Index('idx_source_runs_source_run_at', 'source_id', 'run_at_utc'),
    )


def create_all(engine_url: str) -> None:
    engine = create_engine(engine_url)
    Base.metadata.create_all(engine)
