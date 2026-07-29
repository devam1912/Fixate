"""Live telemetry streaming over SSE and WebSocket.

Both endpoints await events pushed by the dispatcher rather than polling a queue on
a timer, so the dashboard advances as each stage completes instead of redrawing
once the whole run has finished.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from fixate.telemetry.events import DISPATCHER
from fixate.telemetry.logger import AgentTelemetryEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream")

# Emitted periodically so proxies do not close an idle connection, and so a client
# can tell "still working" apart from "stream died".
HEARTBEAT_SECONDS = 15.0


@router.get("/sse/{incident_id}")
async def sse_live_stream(incident_id: str):
    """Server-Sent Events stream of an incident's telemetry."""
    queue = DISPATCHER.subscribe_incident(incident_id)

    async def event_generator():
        try:
            while True:
                try:
                    event: AgentTelemetryEvent = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue

                yield f"event: agent_event\ndata: {event.model_dump_json()}\n\n"

                # A terminal transition ends the stream so the client is not left
                # holding an open connection after the incident finishes.
                if event.action in ("PIPELINE_HALTED", "PIPELINE_CRASHED") or (
                    event.action == "STATE_TRANSITION"
                    and event.output_summary in ("COMPLETED", "FAILED", "PENDING_APPROVAL")
                ):
                    yield "event: done\ndata: {}\n\n"
                    return
        except asyncio.CancelledError:
            raise
        finally:
            DISPATCHER.unsubscribe_incident(incident_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/{incident_id}")
async def websocket_live_stream(websocket: WebSocket, incident_id: str):
    """WebSocket stream of an incident's telemetry."""
    await websocket.accept()
    queue = DISPATCHER.subscribe_incident(incident_id)

    try:
        while True:
            try:
                event: AgentTelemetryEvent = await asyncio.wait_for(
                    queue.get(), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"keepalive"}')
                continue
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket stream for %s ended: %s", incident_id, exc)
    finally:
        DISPATCHER.unsubscribe_incident(incident_id, queue)
