"""End-to-end: mocked OddsPapi -> sync -> activation -> REST API."""

import json
import time
from datetime import datetime, timedelta, timezone

import httpx

BASE = "https://v5.oddspapi.io/en"


def _fixture(fid: str, hours_from_now: float, status: int = 0) -> dict:
    start = int((datetime.now(timezone.utc) + timedelta(hours=hours_from_now)).timestamp())
    return {"fixtureId": fid, "statusId": status, "sportId": 10, "sportName": "Soccer", "tournamentId": 17,
            "tournamentName": "Premier League", "startTime": start,
            "participant1Name": "Arsenal", "participant2Name": "Chelsea"}


def test_sync_and_activate(respx_mock, app_client):
    respx_mock.get(f"{BASE}/fixtures").mock(return_value=httpx.Response(200, json=[
        _fixture("idSOON", 5), _fixture("idLATER", 48), _fixture("idNOMKT", 6)]))

    def odds(request):
        fid = request.url.params["fixtureId"]
        if fid == "idSOON":
            return httpx.Response(200, json={"odds": {"kalshi": {"o1": {}, "o2": {}}, "polymarket": {"o3": {}}},
                                             "bookmakers": {}})
        return httpx.Response(200, json={"odds": {}, "bookmakers": {}})

    respx_mock.get(f"{BASE}/fixtures/odds").mock(side_effect=odds)
    respx_mock.get(f"{BASE}/fixtures/mapping").mock(return_value=httpx.Response(
        200, json=[{"fixtureId": "idSOON", "bookmakerFixtureId": "KXEPL-ARSCHE"}]))

    r = app_client.post("/admin/sync-fixtures")
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 3

    r = app_client.post("/admin/activate-markets")
    assert r.json()["activated"] == 1 and r.json()["pending_mapping"] == 1

    fixtures = {f["oddspapi_id"]: f for f in app_client.get("/fixtures").json()}
    assert fixtures["idSOON"]["lifecycle"] == "ACTIVE"
    assert {m["exchange"] for m in fixtures["idSOON"]["markets"]} == {"kalshi", "polymarket"}
    assert fixtures["idSOON"]["markets"][0]["exchange_fixture_id"] == "KXEPL-ARSCHE"
    assert fixtures["idNOMKT"]["lifecycle"] == "PENDING_MAPPING"
    assert fixtures["idLATER"]["lifecycle"] == "SCHEDULED"

    # vendor cancels the match -> CANCELLED with an audit event
    respx_mock.get(f"{BASE}/fixtures").mock(return_value=httpx.Response(200, json=[_fixture("idSOON", 5, status=3)]))
    app_client.post("/admin/sync-fixtures")
    detail = app_client.get("/fixtures/idSOON").json()
    assert detail["lifecycle"] == "CANCELLED"
    assert [e["to_state"] for e in detail["events"]] == ["ACTIVE", "CANCELLED"]


def test_vendor_error_is_reported(respx_mock, app_client):
    respx_mock.get(f"{BASE}/sports").mock(return_value=httpx.Response(401, json={"code": "invalid_api_key"}))
    r = app_client.get("/vendors/oddspapi/sports")
    assert r.status_code == 502
    assert r.json()["detail"]["status"] == 401


def test_health_and_live_ws(app_client):
    h = app_client.get("/health").json()
    assert h["providers"]["oddspapi"]["configured"] is True

    hub = app_client.app.state.ctx.hub
    with app_client.websocket_connect("/ws/live?fixture_id=idX") as ws:
        for _ in range(50):
            if hub.subscriber_count:
                break
            time.sleep(0.02)
        hub.publish("fixture:idX", {"type": "scores", "fixtureId": "idX", "payload": {"home": 1}})
        msg = ws.receive_json()
        assert msg["type"] == "scores" and msg["payload"] == {"home": 1}


def test_exchange_endpoints(respx_mock, app_client):
    route = respx_mock.get(f"{BASE}/fixtures").mock(return_value=httpx.Response(200, json=[_fixture("idK", 5)]))
    r = app_client.get("/exchanges/kalshi/fixtures?sport_id=10&status=upcoming")
    assert r.status_code == 200 and r.json()[0]["oddspapi_id"] == "idK"
    params = route.calls.last.request.url.params
    assert params["bookmakers"] == "kalshi" and params["statusId"] == "0"

    respx_mock.get(f"{BASE}/fixtures/mapping").mock(return_value=httpx.Response(200, json=[{"fixtureId": "idK"}]))
    r = app_client.get("/exchanges/polymarket.us/mapping?fixture_ids=idK")
    assert r.status_code == 200
    assert app_client.get("/exchanges/notanexchange/fixtures").status_code == 422

    spec = app_client.get("/openapi.json").json()
    assert "/exchanges/{exchange}/fixtures/{fixture_id}/odds" in spec["paths"]
