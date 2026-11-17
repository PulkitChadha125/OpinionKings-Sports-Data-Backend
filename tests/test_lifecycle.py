from datetime import datetime, timedelta, timezone

from app.models import Lifecycle as L
from app.services.lifecycle import activation_transition, vendor_transition

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
W = timedelta(hours=24)


def test_activates_within_window_when_markets_exist():
    assert activation_transition(L.SCHEDULED, NOW + timedelta(hours=10), NOW, W, True)[0] == L.ACTIVE


def test_pending_mapping_when_no_markets():
    assert activation_transition(L.SCHEDULED, NOW + timedelta(hours=10), NOW, W, False)[0] == L.PENDING_MAPPING
    assert activation_transition(L.PENDING_MAPPING, NOW + timedelta(hours=10), NOW, W, False) is None


def test_not_activated_outside_window():
    assert activation_transition(L.SCHEDULED, NOW + timedelta(hours=30), NOW, W, True) is None


def test_vendor_live_finished_cancelled():
    start = NOW
    assert vendor_transition(L.ACTIVE, 1, start, start, NOW, W)[0] == L.LIVE
    assert vendor_transition(L.LIVE, 2, start, start, NOW, W)[0] == L.FINISHED
    assert vendor_transition(L.ACTIVE, 3, start, start, NOW, W)[0] == L.CANCELLED
    assert vendor_transition(L.ACTIVE, 4, start, start, NOW, W)[0] == L.CANCELLED
    assert vendor_transition(L.LIVE, 1, start, start, NOW, W) is None


def test_postponed_when_moved_far_out():
    old = NOW + timedelta(hours=5)
    new = NOW + timedelta(days=3)
    assert vendor_transition(L.ACTIVE, 0, old, new, NOW, W)[0] == L.POSTPONED


def test_rescheduled_slightly_outside_window_deactivates():
    old = NOW + timedelta(hours=20)
    new = NOW + timedelta(hours=26)  # moved 6h, now outside the 24h window
    assert vendor_transition(L.ACTIVE, 0, old, new, NOW, W)[0] == L.SCHEDULED


def test_small_time_change_ignored():
    old = NOW + timedelta(hours=5)
    assert vendor_transition(L.ACTIVE, 0, old, old + timedelta(minutes=3), NOW, W) is None


def test_cancelled_then_reinstated():
    assert vendor_transition(L.CANCELLED, 0, NOW, NOW, NOW, W)[0] == L.SCHEDULED
