from sqlalchemy import (
    Column,
    Float,
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


class Event(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    source_type = Column(String, nullable=False)
    source_name = Column(String)
    title = Column(String)
    raw_text = Column(Text)
    event_type = Column(String)
    severity_guess = Column(Integer)
    city = Column(String)
    state = Column(String)
    country = Column(String)


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True)
    summary = Column(Text, nullable=False)
    risk_type = Column(String, nullable=False)
    priority = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    root_event_id = Column(String, nullable=False)
    reasoning = Column(Text)
    recommended_actions = Column(Text)


def create_all(engine_url: str) -> None:
    engine = create_engine(engine_url)
    Base.metadata.create_all(engine)

