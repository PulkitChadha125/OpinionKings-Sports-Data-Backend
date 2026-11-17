"""Pure state-machine rules for a fixture's market lifecycle.

SCHEDULED -> (24h before start) -> ACTIVE | PENDING_MAPPING -> LIVE -> FINISHED
side paths: CANCELLED, POSTPONED (start moved far out), back to SCHEDULED on reschedule.
"""

from datetime import datetime, timedelta

from app.models import Lifecycle
from app.providers.oddspapi import (STATUS_CANCELLED, STATUS_FINISHED, STATUS_LIVE,
                                    STATUS_PREGAME, STATUS_REMOVED)

RESCHEDULE_TOLERANCE = timedelta(minutes=5)
POSTPONE_THRESHOLD = timedelta(hours=12)

PRE_MATCH = {Lifecycle.SCHEDULED, Lifecycle.PENDING_MAPPING, Lifecycle.ACTIVE, Lifecycle.POSTPONED}


def vendor_transition(current: Lifecycle, vendor_status: int | None, old_start: datetime | None,
                      new_start: datetime, now: datetime, window: timedelta) -> tuple[Lifecycle, str] | None:
    """Transition driven by a vendor fixture update. Returns (new_state, reason) or None."""
    if vendor_status in (STATUS_CANCELLED, STATUS_REMOVED):
        if current != Lifecycle.CANCELLED:
            return Lifecycle.CANCELLED, f"vendor status {vendor_status} (cancelled/removed)"
        return None
    if vendor_status == STATUS_FINISHED:
        return (Lifecycle.FINISHED, "vendor reports finished") if current != Lifecycle.FINISHED else None
    if vendor_status == STATUS_LIVE:
        return (Lifecycle.LIVE, "match started") if current != Lifecycle.LIVE else None

    if vendor_status not in (STATUS_PREGAME, None):
        return None

    if current == Lifecycle.CANCELLED:
        return Lifecycle.SCHEDULED, "reinstated by vendor"

    if current in PRE_MATCH and old_start is not None:
        delta = new_start - old_start
        if abs(delta) > RESCHEDULE_TOLERANCE:
            outside_window = new_start > now + window
            if delta > POSTPONE_THRESHOLD and outside_window:
                return Lifecycle.POSTPONED, f"postponed by {delta}"
            if outside_window and current in (Lifecycle.ACTIVE, Lifecycle.PENDING_MAPPING):
                return Lifecycle.SCHEDULED, f"rescheduled by {delta}; outside activation window"
            if current == Lifecycle.POSTPONED and not outside_window:
                return Lifecycle.SCHEDULED, f"rescheduled by {delta}; back in window"
    return None


def activation_transition(current: Lifecycle, start: datetime, now: datetime, window: timedelta,
                          has_markets: bool) -> tuple[Lifecycle, str] | None:
    """Transition driven by the activation job."""
    if current not in (Lifecycle.SCHEDULED, Lifecycle.POSTPONED, Lifecycle.PENDING_MAPPING):
        return None
    if not (now <= start <= now + window):
        return None
    if has_markets:
        return Lifecycle.ACTIVE, "inside activation window with exchange markets"
    if current != Lifecycle.PENDING_MAPPING:
        return Lifecycle.PENDING_MAPPING, "inside activation window, no exchange markets mapped yet"
    return None
