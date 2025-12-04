import uuid
from datetime import datetime


def new_event_id() -> str:
    return f"EVT-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def new_alert_id() -> str:
    return f"ALERT-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

