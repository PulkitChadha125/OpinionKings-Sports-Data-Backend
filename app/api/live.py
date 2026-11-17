import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_ws_ctx
from app.state import AppState
from app.api import tags

router = APIRouter(tags=[tags.BACKEND_LIVE])


@router.websocket("/ws/live")
async def live(websocket: WebSocket, fixture_id: str | None = None, ctx: AppState = Depends(get_ws_ctx)):
    """Frontend stream. `?fixture_id=<oddspapi id>` for one match, omit for everything.

    Messages: {"type": "scores"|"fixtures"|"odds"|"lifecycle", "fixtureId", "payload", ...}
    """
    await websocket.accept()
    topic = f"fixture:{fixture_id}" if fixture_id else "all"
    queue = ctx.hub.subscribe(topic)
    try:
        if fixture_id and topic in ctx.hub.latest:
            await websocket.send_json({"snapshot": True, **ctx.hub.latest[topic]})
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        ctx.hub.unsubscribe(topic, queue)
