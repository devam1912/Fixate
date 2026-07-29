"""Fan-out of telemetry events to live dashboard subscribers.

The pipeline runs on a worker thread while SSE and WebSocket handlers run on the
event loop, so events cross a thread boundary. Delivery therefore goes through
``loop.call_soon_threadsafe`` onto an ``asyncio.Queue``: handlers can then await
events instead of polling, and no queue operation happens on the wrong thread.

The previous implementation exposed ``broadcast_event`` but nothing ever called
it, and no handler ever subscribed to the telemetry logger -- the streaming
endpoints accepted connections and emitted nothing.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from fixate.telemetry.logger import AgentTelemetryEvent

logger = logging.getLogger(__name__)

# Bounds a subscriber that stops reading, so a stalled browser tab cannot grow
# the queue without limit.
MAX_QUEUED_EVENTS = 1000


class EventStreamDispatcher:
    """Routes telemetry events to the live subscribers of each incident."""

    def __init__(self) -> None:
        self._incident_queues: Dict[str, List[asyncio.Queue]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Record the event loop that deliveries must be scheduled onto."""
        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def subscribe_incident(self, incident_id: str) -> asyncio.Queue:
        """Register a subscriber queue for an incident."""
        self.bind_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
        self._incident_queues.setdefault(incident_id, []).append(queue)
        logger.info("Registered live stream subscriber for incident %s", incident_id)
        return queue

    def unsubscribe_incident(self, incident_id: str, queue: asyncio.Queue) -> None:
        """Drop a subscriber when its client disconnects."""
        queues = self._incident_queues.get(incident_id)
        if not queues:
            return
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._incident_queues.pop(incident_id, None)
        logger.info("Unsubscribed live stream subscriber for incident %s", incident_id)

    def broadcast_event(self, event: AgentTelemetryEvent) -> None:
        """Deliver an event to every subscriber of its incident.

        Called from the pipeline's worker thread via the telemetry logger's
        subscription hook, so the actual put is marshalled onto the loop.
        """
        queues = self._incident_queues.get(event.incident_id)
        if not queues:
            return

        for queue in list(queues):
            self._put(queue, event)

    def _put(self, queue: asyncio.Queue, event: AgentTelemetryEvent) -> None:
        def deliver() -> None:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping telemetry event; subscriber queue is full.")

        loop = self._loop
        if loop is None or not loop.is_running():
            # No loop yet (e.g. a synchronous test run): deliver inline so events
            # are not silently lost.
            deliver()
            return

        try:
            loop.call_soon_threadsafe(deliver)
        except RuntimeError as exc:
            logger.warning("Could not schedule telemetry delivery: %s", exc)


#: Process-wide dispatcher. The API subscribes it to the shared telemetry logger so
#: every pipeline event reaches connected dashboards.
DISPATCHER = EventStreamDispatcher()
