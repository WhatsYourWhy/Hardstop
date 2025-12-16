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
    tier = Column(String, nullable=False)  # global, regional, local
    fetched_at_utc = Column(String, nullable=False)  # ISO 8601 string
    published_at_utc = Column(String, nullable=True)  # ISO 8601 string
    canonical_id = Column(String, nullable=True, index=True)
    url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    raw_payload_json = Column(Text, nullable=False)  # Full original item as JSON
    content_hash = Column(String, nullable=True, index=True)  # SHA256 hash
    status = Column(String, nullable=False, default="NEW")  # NEW, NORMALIZED, FAILED
    error = Column(Text, nullable=True)


class Event(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)
    source_name = Column(String)
    source_id = Column(String, nullable=True, index=True)  # v0.6: external source ID
    raw_id = Column(String, nullable=True, index=True)  # v0.6: link to raw_items
    title = Column(String)
    raw_text = Column(Text)
    event_type = Column(String)
    event_time_utc = Column(String, nullable=True)  # v0.6: ISO 8601 string
    severity_guess = Column(Integer)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    location_hint = Column(Text, nullable=True)  # v0.6: best-effort location text
    entities_json = Column(Text, nullable=True)  # v0.6: extracted entities as JSON
    event_payload_json = Column(Text, nullable=True)  # v0.6: normalized event as JSON


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True)
    summary = Column(Text, nullable=False)
    risk_type = Column(String, nullable=False)
    classification = Column(Integer, nullable=False)  # Canonical field (0=Interesting, 1=Relevant, 2=Impactful)
    priority = Column(Integer, nullable=True)  # DEPRECATED: Use classification. Will be removed in v0.4.
    status = Column(String, nullable=False)
    root_event_id = Column(String, nullable=False)
    reasoning = Column(Text)
    recommended_actions = Column(Text)
    
    # Correlation fields (v0.4)
    correlation_key = Column(String, nullable=True, index=True)
    correlation_action = Column(String, nullable=True)  # "CREATED" or "UPDATED" - fact about ingest time
    first_seen_utc = Column(DateTime, nullable=True)
    last_seen_utc = Column(DateTime, nullable=True)
    update_count = Column(Integer, nullable=True)
    root_event_ids_json = Column(Text, nullable=True)  # Store list as JSON string
    
    # Brief fields (v0.5)
    impact_score = Column(Integer, nullable=True)  # Network impact score (0-10)
    scope_json = Column(Text, nullable=True)  # Scope as JSON: {"facilities": [...], "lanes": [...], "shipments": [...]}


def create_all(engine_url: str) -> None:
    engine = create_engine(engine_url)
    Base.metadata.create_all(engine)

