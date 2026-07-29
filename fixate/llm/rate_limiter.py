"""Thread-safe rate limiter for Gemini LLM generation and embedding requests.

The enforced ceilings are defined once, at the bottom of this module, and are
environment-overridable. They are deliberately *not* restated here: the previous
version of this docstring advertised a 90k embedding TPM against a real allowance
of 30k, and the numbers that matter drifted out of sync with the prose describing
them. Read ``LLM_RATE_LIMITER`` and ``EMBEDDING_RATE_LIMITER`` instead.
"""

import os
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

                # Check TPM limit.
                #
                # A request larger than the entire per-minute budget can never be
                # admitted by waiting, so it must not be treated as "throttle and
                # retry": with an empty window there is no timestamp to compute a
                # wait from (an IndexError), and with a non-empty one the loop
                # simply spins until the window drains and then raises anyway.
                # Callers are expected to size their batches; this clamps rather
                # than crashes, and says so loudly.
                charge = estimated_tokens
                if charge > self.max_tpm:
                    logger.warning(
                        "[%s] A single request estimated at %d tokens exceeds the whole "
                        "TPM budget of %d. Admitting it against a full budget -- the "
                        "provider may still refuse it. Reduce the batch size.",
                        self.name,
                        charge,
                        self.max_tpm,
                    )
                    charge = self.max_tpm

                current_tpm = sum(tok for _, tok in self._token_timestamps)
                if self._token_timestamps and current_tpm + charge > self.max_tpm:
                    wait_time = 60.0 - (now - self._token_timestamps[0][0]) + 0.1
                    logger.info(
                        f"[{self.name}] TPM limit ({current_tpm}/{self.max_tpm}). "
                        f"Throttling for {wait_time:.2f}s"
                    )
                    time.sleep(max(wait_time, 0.1))
                    continue

                estimated_tokens = charge

                # Record request
                self._request_timestamps.append(now)
                self._daily_timestamps.append(now)
                self._token_timestamps.append((now, estimated_tokens))

                used = len(self._daily_timestamps)
                if used == int(self.max_rpd * 0.8):
                    logger.warning(
                        "[%s] 80%% of the daily request budget used (%d/%d).",
                        self.name,
                        used,
                        self.max_rpd,
                    )
                break


def estimate_tokens(text: str) -> int:
    """Approximate a token count for rate-limit accounting.

    Roughly four characters per token, then a deliberate over-estimate. Counting
    whitespace-separated words instead understates code badly -- punctuation,
    operators, and identifiers all tokenize far more finely than prose -- which
    lets the TPM guard pass requests the provider then refuses.

    The 1.15 factor exists because this approximation is only ever checked against
    the provider's real tokenizer *after* a request has been sent. Under-counting
    silently overshoots the quota; over-counting only costs a little throughput.
    """
    return max(1, int(len(text or "") / 4 * 1.15))


def _limit(name: str, default: int) -> int:
    """Read a limit from the environment, falling back to the documented default."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r; using %d.", name, raw, default)
        return default


# Provider limits, with headroom below the published ceilings.
#
# These must track the provider's real quotas. The embedding TPM ceiling was
# previously set to 90,000 against an actual allowance of 30,000, so the limiter
# could never throttle before the API refused -- the local guard was measuring
# against a limit that did not exist. Daily counters live in-process and reset when
# the container restarts while the provider's do not, hence the margin.
LLM_RATE_LIMITER = RateLimiter(
    max_rpm=_limit("FIXATE_LLM_MAX_RPM", 12),      # provider: 15
    max_tpm=_limit("FIXATE_LLM_MAX_TPM", 240000),  # provider: 250,000
    max_rpd=_limit("FIXATE_LLM_MAX_RPD", 480),     # provider: 500
    name="LLM-Flash-Lite",
)

# Embedding TPM is the binding constraint in practice -- a repository-sized index
# is thousands of chunks of code, while requests and daily counts stay far below
# their ceilings. 28,000 against a real 30,000 left ~7% of headroom to absorb the
# gap between the local estimate and Google's tokenizer, and observed usage duly
# peaked at 28.3K. 24,000 is 80% of the real ceiling, which is the margin the
# estimate actually needs.
EMBEDDING_RATE_LIMITER = RateLimiter(
    max_rpm=_limit("FIXATE_EMBED_MAX_RPM", 80),     # provider: 100
    max_tpm=_limit("FIXATE_EMBED_MAX_TPM", 24000),  # provider: 30,000
    max_rpd=_limit("FIXATE_EMBED_MAX_RPD", 900),    # provider: 1,000
    name="Gemini-Embedding",
)
