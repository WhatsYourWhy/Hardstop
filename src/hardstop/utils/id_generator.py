import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional, Union


@dataclass
class _IdDeterminismState:
    now: datetime
    seed: str
    counter: int = 0


_ID_STATE: Optional[_IdDeterminismState] = None


def _current_now() -> datetime:
    if _ID_STATE is not None:
        return _ID_STATE.now
    return datetime.now(timezone.utc)


def _next_suffix(length: int = 8) -> str:
    if _ID_STATE is not None:
        _ID_STATE.counter += 1
        payload = f"{_ID_STATE.seed}:{_ID_STATE.counter}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return digest[:length]
    return uuid.uuid4().hex[:length]


def new_event_id() -> str:
    now = _current_now()
    return f"EVT-{now.strftime('%Y%m%d')}-{_next_suffix()}"


def new_alert_id() -> str:
    now = _current_now()
    return f"ALERT-{now.strftime('%Y%m%d')}-{_next_suffix()}"


@contextmanager
def deterministic_id_context(
    *,
    now: datetime,
    seed: Union[int, str],
) -> Iterator[None]:
    """
    Provide a deterministic context for ID generation (event/alert).

    Args:
        now: datetime to freeze for ID prefixes (must be timezone-aware or UTC).
        seed: Seed value for deterministic UUID suffix generation.
    """
    global _ID_STATE

    normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    normalized_now = normalized_now.astimezone(timezone.utc)

    seed_str = str(seed)
    previous_state = _ID_STATE
    _ID_STATE = _IdDeterminismState(now=normalized_now, seed=seed_str)
    try:
        yield
    finally:
        _ID_STATE = previous_state


__all__ = ["new_event_id", "new_alert_id", "deterministic_id_context"]

