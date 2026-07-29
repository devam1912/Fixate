"""Telemetry and Event Logger Package."""

from fixate.telemetry.logger import TelemetryLogger, AgentTelemetryEvent

TelemetryTracker = TelemetryLogger
TelemetryEvent = AgentTelemetryEvent

__all__ = ["TelemetryLogger", "TelemetryTracker", "AgentTelemetryEvent", "TelemetryEvent"]
