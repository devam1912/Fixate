"""Event dispatcher and subscriber queue for WebSockets / SSE streaming."""

import asyncio
import queue
import logging
from typing import Dict, List
from fixate.telemetry.logger import AgentTelemetryEvent

logger = logging.getLogger(__name__)


class EventStreamDispatcher:
    """Manages real-time event queues for active dashboard WebSocket / SSE connections."""

    def __init__(self):
        self._incident_queues: Dict[str, List[queue.Queue]] = {}

    def subscribe_incident(self, incident_id: str) -> queue.Queue:
        """Create and register a new event subscription queue for an incident session."""
        if incident_id not in self._incident_queues:
            self._incident_queues[incident_id] = []

        event_queue = queue.Queue()
        self._incident_queues[incident_id].append(event_queue)
        logger.info(f"Registered live stream subscriber for incident {incident_id}")
        return event_queue

    def unsubscribe_incident(self, incident_id: str, event_queue: queue.Queue):
        """Remove a subscriber queue when client disconnects."""
        if incident_id in self._incident_queues and event_queue in self._incident_queues[incident_id]:
            self._incident_queues[incident_id].remove(event_queue)
            logger.info(f"Unsubscribed live stream subscriber for incident {incident_id}")

    def broadcast_event(self, event: AgentTelemetryEvent):
        """Broadcast a telemetry event to all active subscriber queues matching the incident ID."""
        incident_id = event.incident_id
        if incident_id in self._incident_queues:
            for q in list(self._incident_queues[incident_id]):
                try:
                    q.put_nowait(event)
                except Exception as err:
                    logger.error(f"Error dispatching event to queue: {err}")
