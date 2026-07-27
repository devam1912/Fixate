"""Server-Sent Events (SSE) and WebSocket routers for live telemetry event streaming."""

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from fixate.telemetry.events import EventStreamDispatcher
from fixate.telemetry.logger import AgentTelemetryEvent

router = APIRouter(prefix="/api/stream")
dispatcher = EventStreamDispatcher()


@router.get("/sse/{incident_id}")
async def sse_live_stream(incident_id: str):
    """Server-Sent Events endpoint streaming live agent telemetry updates to dashboard."""
    event_queue = dispatcher.subscribe_incident(incident_id)

    async def event_generator():
        try:
            while True:
                if not event_queue.empty():
                    evt: AgentTelemetryEvent = event_queue.get_nowait()
                    data = evt.model_dump_json()
                    yield f"event: agent_event\ndata: {data}\n\n"
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            dispatcher.unsubscribe_incident(incident_id, event_queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/ws/{incident_id}")
async def websocket_live_stream(websocket: WebSocket, incident_id: str):
    """WebSocket endpoint for real-time bidirectional telemetry streaming."""
    await websocket.accept()
    event_queue = dispatcher.subscribe_incident(incident_id)

    try:
        while True:
            if not event_queue.empty():
                evt: AgentTelemetryEvent = event_queue.get_nowait()
                await websocket.send_text(evt.model_dump_json())
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        dispatcher.unsubscribe_incident(incident_id, event_queue)
    except Exception:
        dispatcher.unsubscribe_incident(incident_id, event_queue)
