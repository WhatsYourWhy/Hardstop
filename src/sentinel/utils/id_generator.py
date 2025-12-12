import uuid
from datetime import UTC, datetime


def new_event_id() -> str:
    return f"EVT-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def new_alert_id() -> str:
    return f"ALERT-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

