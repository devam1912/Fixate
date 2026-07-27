"""Structured event logger for agent telemetry and live stream replay."""

import os
import json
import datetime
import logging
from typing import Dict, List, Optional, Callable
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentTelemetryEvent(BaseModel):
    """Structured telemetry event recording agent actions, inputs, outputs, and results."""
    event_id: str = Field(..., description="Unique event ID")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    incident_id: str = Field(..., description="Incident session ID")
    agent: str = Field(..., description="Agent identifier: Localization, RAG, PatchGen, Verification, Orchestrator")
    action: str = Field(..., description="Action executed by agent")
    input_summary: str = Field(..., description="Concise summary of input data passed to agent")
    output_summary: str = Field(..., description="Concise summary of output produced by agent")
    result: str = Field(..., description="Execution outcome: SUCCESS, FAILURE, IN_PROGRESS, REQUIRES_APPROVAL")
    details: Dict = Field(default_factory=dict, description="Arbitrary event payload details")


class TelemetryLogger:
    """Central telemetry logger persisting incident event streams for replay and dashboard visualization."""

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = log_dir or os.path.join(os.getcwd(), "telemetry_logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self._subscribers: List[Callable[[AgentTelemetryEvent], None]] = []

    def subscribe(self, callback: Callable[[AgentTelemetryEvent], None]):
        """Subscribe a listener callback (e.g. WebSocket / SSE broadcaster) to live telemetry events."""
        self._subscribers.append(callback)

    def log_event(
        self,
        incident_id: str,
        agent: str,
        action: str,
        input_summary: str,
        output_summary: str,
        result: str,
        details: Optional[Dict] = None,
    ) -> AgentTelemetryEvent:
        """Create, record, and dispatch a structured telemetry event."""
        import uuid

        event_id = f"evt_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        event = AgentTelemetryEvent(
            event_id=event_id,
            timestamp=timestamp,
            incident_id=incident_id,
            agent=agent,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            result=result,
            details=details or {},
        )

        # 1. Persist event to JSON Lines file for replay
        log_file = os.path.join(self.log_dir, f"incident_{incident_id}.jsonl")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        except Exception as exc:
            logger.error(f"Error persisting telemetry event to {log_file}: {exc}")

        # 2. Notify subscribers (live WebSocket / SSE streaming)
        for sub in self._subscribers:
            try:
                sub(event)
            except Exception as sub_err:
                logger.error(f"Error notifying telemetry subscriber: {sub_err}")

        logger.info(f"[{agent}] {action}: {result} ({input_summary[:40]} -> {output_summary[:40]})")
        return event

    def get_incident_events(self, incident_id: str) -> List[AgentTelemetryEvent]:
        """Load and return all recorded events for a given incident ID."""
        log_file = os.path.join(self.log_dir, f"incident_{incident_id}.jsonl")
        if not os.path.exists(log_file):
            return []

        events: List[AgentTelemetryEvent] = []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(AgentTelemetryEvent.model_validate_json(line))
        except Exception as exc:
            logger.error(f"Error reading incident log {log_file}: {exc}")

        return events
