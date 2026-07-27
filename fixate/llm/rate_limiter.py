"""Thread-safe rate limiter for Gemini LLM generation and embedding requests.

Rate Limits Enforced:
1. LLM Generation (Gemini Flash Lite / Flash):
   - Max 12 requests per minute (RPM <= 12)
   - Max 250,000 tokens per minute (TPM <= 250k)
   - Max 500 requests per day (RPD <= 500)

2. Embeddings (Gemini Embedding):
   - Max 90 requests per minute (RPM <= 90)
   - Max 90,000 tokens per minute (TPM <= 90k)
   - Max 950 requests per day (RPD <= 950)
"""

import time
import threading
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforces RPM (requests per min), TPM (tokens per min), and RPD (requests per day) limits."""

    def __init__(
        self,
        max_rpm: int,
        max_tpm: int,
        max_rpd: int,
        name: str = "RateLimiter",
    ):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.max_rpd = max_rpd
        self.name = name

        self._lock = threading.Lock()
        self._request_timestamps: List[float] = []
        self._daily_timestamps: List[float] = []
        self._token_timestamps: List[Tuple[float, int]] = []

    def acquire(self, estimated_tokens: int = 500):
        """Block until request can be safely sent within rate limits."""
        with self._lock:
            while True:
                now = time.time()

                # Clean timestamps older than 60s
                self._request_timestamps = [t for t in self._request_timestamps if now - t < 60.0]
                self._token_timestamps = [(t, tok) for t, tok in self._token_timestamps if now - t < 60.0]

                # Clean daily timestamps older than 24 hours (86,400s)
                self._daily_timestamps = [t for t in self._daily_timestamps if now - t < 86400.0]

                # Check RPD limit
                if len(self._daily_timestamps) >= self.max_rpd:
                    wait_time = 86400.0 - (now - self._daily_timestamps[0])
                    logger.warning(
                        f"[{self.name}] RPD limit reached ({len(self._daily_timestamps)}/{self.max_rpd}). "
                        f"Sleeping for {wait_time:.1f}s"
                    )
                    time.sleep(min(wait_time, 5.0))
                    continue

                # Check RPM limit
                if len(self._request_timestamps) >= self.max_rpm:
                    wait_time = 60.0 - (now - self._request_timestamps[0]) + 0.1
                    logger.info(
                        f"[{self.name}] RPM limit ({len(self._request_timestamps)}/{self.max_rpm}). "
                        f"Throttling for {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)
                    continue

                # Check TPM limit
                current_tpm = sum(tok for _, tok in self._token_timestamps)
                if current_tpm + estimated_tokens > self.max_tpm:
                    wait_time = 60.0 - (now - self._token_timestamps[0][0]) + 0.1
                    logger.info(
                        f"[{self.name}] TPM limit ({current_tpm}/{self.max_tpm}). "
                        f"Throttling for {wait_time:.2f}s"
                    )
                    time.sleep(wait_time)
                    continue

                # Record request
                self._request_timestamps.append(now)
                self._daily_timestamps.append(now)
                self._token_timestamps.append((now, estimated_tokens))
                break


# Global rate limiter singletons
LLM_RATE_LIMITER = RateLimiter(
    max_rpm=12,
    max_tpm=250000,
    max_rpd=500,
    name="LLM-Flash-Lite",
)

EMBEDDING_RATE_LIMITER = RateLimiter(
    max_rpm=90,
    max_tpm=90000,
    max_rpd=950,
    name="Gemini-Embedding",
)
