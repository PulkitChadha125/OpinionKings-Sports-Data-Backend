from fastapi import HTTPException, Request, WebSocket

from app.providers.base import MissingCredentials, ProviderError
from app.state import AppState


def get_ctx(request: Request) -> AppState:
    return request.app.state.ctx


def get_ws_ctx(websocket: WebSocket) -> AppState:
    return websocket.app.state.ctx


def provider_http_error(exc: ProviderError) -> HTTPException:
    if isinstance(exc, MissingCredentials):
        return HTTPException(503, detail=exc.message)
    return HTTPException(502, detail={"provider": exc.provider, "status": exc.status,
                                      "message": exc.message, "url": exc.url})
