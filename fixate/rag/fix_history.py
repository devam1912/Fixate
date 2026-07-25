"""Fix History Store for recording and retrieving successful error signature -> diff pairs."""

import os
import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FixRecord(BaseModel):
    """Structured record of a verified historical code fix."""
    fix_id: str = Field(..., description="Unique ID for the fix record")
    exception_type: str = Field(..., description="Exception class name")
    exception_message: str = Field(..., description="Error message text")
    failing_symbol: str = Field(..., description="Target symbol ID fixed")
    applied_diff: str = Field(..., description="Unified diff patch that resolved the error")
    timestamp: str = Field(..., description="ISO timestamp when fix was verified")


class FixHistoryStore:
    """Store for indexing past successful bug fixes to provide few-shot fix examples to Patch Generator."""

    def __init__(self, db_file: Optional[str] = None):
        self.db_file = db_file or os.path.join(os.getcwd(), "fix_history.json")
        self.history: List[FixRecord] = []
        self._load()

    def _load(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.history = [FixRecord(**item) for item in data]
                logger.info(f"Loaded {len(self.history)} historical fix records from {self.db_file}")
            except Exception as exc:
                logger.error(f"Error loading fix history file {self.db_file}: {exc}")

    def _save(self):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump([rec.model_dump() for rec in self.history], f, indent=2)
        except Exception as exc:
            logger.error(f"Error saving fix history file {self.db_file}: {exc}")

    def record_fix(
        self,
        exception_type: str,
        exception_message: str,
        failing_symbol: str,
        applied_diff: str,
    ) -> FixRecord:
        """Record a newly verified successful fix into the historical database."""
        import datetime

        fix_id = f"fix_{len(self.history) + 1}_{exception_type}"
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = FixRecord(
            fix_id=fix_id,
            exception_type=exception_type,
            exception_message=exception_message,
            failing_symbol=failing_symbol,
            applied_diff=applied_diff,
            timestamp=timestamp,
        )
        self.history.append(record)
        self._save()
        logger.info(f"Recorded new fix in history: {fix_id} for {exception_type}")
        return record

    def find_similar_fixes(self, exception_type: str, exception_message: str, limit: int = 2) -> List[FixRecord]:
        """Query fix history for past fixes matching or similar to the current failure signature."""
        matched: List[FixRecord] = []

        # 1. Exact exception type match
        for rec in reversed(self.history):
            if rec.exception_type.lower() == exception_type.lower():
                matched.append(rec)
                if len(matched) >= limit:
                    return matched

        # 2. Substring message match fallback
        if not matched:
            err_words = set(exception_message.lower().split())
            for rec in reversed(self.history):
                if any(w in rec.exception_message.lower() for w in err_words if len(w) > 3):
                    matched.append(rec)
                    if len(matched) >= limit:
                        return matched

        return matched
