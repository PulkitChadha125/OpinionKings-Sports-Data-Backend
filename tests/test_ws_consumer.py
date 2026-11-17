import asyncio
import json

from app.services.latency import LatencyTracker
from app.services.live_hub import LiveHub
from app.services.oddspapi_ws import OddsPapiStream


def _stream(updates=None, snapshots=None):
    async def on_update(p):
        updates.append(p)

    async def on_snapshot(ch):
        snapshots.append(ch)

    return OddsPapiStream("wss://x", "k", ["fixtures", "scores"], LatencyTracker(), LiveHub(),
                          on_fixture_update=on_update if updates is not None else None,
                          on_snapshot_required=on_snapshot if snapshots is not None else None)


def test_login_message_includes_resume_cursor():
    s = _stream()
    assert s.login_message() == {"type": "login", "apiKey": "k", "channels": ["fixtures", "scores"],
                                 "receiveType": "json"}
    s.server_epoch, s.cursors = "ep1", {"scores": "1-1"}
    assert s.login_message()["lastSeenId"] == {"scores": "1-1"}


def test_data_message_updates_cursor_hub_and_handler():
    updates, snaps = [], []
    s = _stream(updates, snaps)
    q = s.hub.subscribe("fixture:id1")
    msg = {"channel": "scores", "type": "UPDATE", "ts": 1765497902846, "entryId": "1765497902846-3221",
           "payload": {"fixtureId": "id1", "scores": {"result": {"participant1Score": 1}}}}
    asyncio.run(s.handle_raw(json.dumps(msg)))
    assert s.cursors["scores"] == "1765497902846-3221"
    assert s.message_counts == {"scores": 1}
    assert q.get_nowait()["fixtureId"] == "id1"
    assert updates[0]["channel"] == "scores"


def test_control_messages():
    snaps = []
    s = _stream(snapshots=snaps)
    asyncio.run(s.handle_raw(json.dumps({"type": "login_ok", "resume": {"serverEpoch": "e1"}})))
    assert s.server_epoch == "e1"
    s.cursors = {"scores": "x", "fixtures": "y"}
    asyncio.run(s.handle_raw(json.dumps({"type": "snapshot_required", "channels": ["scores"]})))
    assert "scores" not in s.cursors and snaps == [["scores"]]
    assert asyncio.run(s.handle_raw(json.dumps({"type": "reconnect", "reason": "server_upgrade"}))) == "reconnect"
