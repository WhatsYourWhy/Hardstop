from typing import Dict


def attach_dummy_entities(event: Dict) -> Dict:
    """
    For the demo, pretend we matched the event to one facility and some shipments.

    In a real system, this would use NLP + DB context.
    """
    if not event.get("facilities"):
        event["facilities"] = ["PLANT-01"]
    if not event.get("shipments"):
        event["shipments"] = ["SHP-1001", "SHP-1002"]
    return event

