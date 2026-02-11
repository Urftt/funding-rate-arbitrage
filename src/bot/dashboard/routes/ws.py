"""WebSocket hub for real-time HTML fragment broadcast to dashboard clients."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)

router = APIRouter()


class DashboardHub:
    """Manages WebSocket connections and broadcasts HTML fragments to all clients."""

    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept a WebSocket connection and add it to the active connections list."""
        await ws.accept()
        self.connections.append(ws)
        log.info("dashboard_ws_connected", total=len(self.connections))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection from the active connections list."""
        if ws in self.connections:
            self.connections.remove(ws)
        log.info("dashboard_ws_disconnected", total=len(self.connections))

    async def broadcast(self, html: str) -> None:
        """Send an HTML fragment to all connected clients, removing broken connections."""
        for ws in self.connections.copy():
            try:
                await ws.send_text(html)
            except Exception:
                self.connections.remove(ws)
                log.warning("dashboard_ws_broadcast_error", remaining=len(self.connections))


hub = DashboardHub()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates."""
    ws_hub: DashboardHub = websocket.app.state.hub
    await ws_hub.connect(websocket)
    try:
        while True:
            # Consume messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)
