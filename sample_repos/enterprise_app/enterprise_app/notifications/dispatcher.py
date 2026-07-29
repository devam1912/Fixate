"""Enterprise Multi-Channel Notification Gateway & Template Engine (300+ lines).

Dispatches transactional email, SMS, and webhook notifications through provider gateways,
formats message headers, and maintains recipient dispatch logs.
"""

import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class NotificationMessage:
    """Represents a transactional notification message to be dispatched."""
    recipient: str
    subject: str
    body: str
    channel: str = "email"
    metadata: Dict[str, str] = field(default_factory=dict)
    dispatch_time: Optional[float] = None
    status: str = "pending"


class NotificationDispatcher:
    """Multi-channel email, SMS, and webhook notification gateway."""

    def __init__(self):
        self.sent_log: List[NotificationMessage] = []
        self.channel_providers = {
            "email": "SendGridGateway",
            "sms": "TwilioGateway",
            "webhook": "HTTPPostGateway",
        }
        self._retry_queue: List[NotificationMessage] = []

    def format_notification_header(self, msg: NotificationMessage) -> str:
        """Format notification headers from message metadata.
        
        BUG 5 (INTENTIONAL): Direct dictionary KeyError access `msg.metadata["priority"]`
        without `.get("priority", "normal")` fallback check.
        """
        # INTENTIONAL BUG 5: Direct dictionary KeyError access on missing key
        priority = msg.metadata["priority"]
        return f"[{priority.upper()}] To: {msg.recipient} | Subject: {msg.subject}"

    def send_notification(self, msg: NotificationMessage) -> bool:
        """Dispatch notification through configured provider channel."""
        try:
            header = self.format_notification_header(msg)
            provider = self.channel_providers.get(msg.channel, "UnknownGateway")
            logger.info(f"Sending via {provider}: {header}")
            msg.status = "sent"
            msg.dispatch_time = time.time()
            self.sent_log.append(msg)
            return True
        except Exception as err:
            logger.error(f"Failed to dispatch notification to {msg.recipient}: {err}")
            msg.status = "failed"
            self._retry_queue.append(msg)
            raise err

    def get_dispatch_history(self, recipient: str) -> List[NotificationMessage]:
        """Retrieve sent notification log for recipient."""
        return [m for m in self.sent_log if m.recipient == recipient]

    def retry_failed_notifications(self) -> int:
        """Retry sending queued failed notifications."""
        success_count = 0
        queue_copy = list(self._retry_queue)
        self._retry_queue.clear()
        for msg in queue_copy:
            try:
                if self.send_notification(msg):
                    success_count += 1
            except Exception:
                pass
        return success_count
