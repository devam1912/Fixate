"""Heuristic risk classification checker enforcing human-in-the-loop approval gates for high-risk patches."""

import re
import logging
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Keywords indicating sensitive security, financial, or database structural code
HIGH_RISK_KEYWORDS = {
    # Authentication & Security
    "auth", "login", "password", "token", "jwt", "session", "credential", "secret", "rbac", "permission",
    # Financial & Payments
    "payment", "billing", "stripe", "checkout", "charge", "refund", "card", "crypto", "currency",
    # Database Migrations & Schemas
    "migration", "schema", "drop_table", "alter_table", "delete_all", "truncate",
}


class RiskAssessment(BaseModel):
    """Structured assessment result produced by HumanApprovalChecker."""
    is_risky: bool = Field(..., description="True if patch touches sensitive high-risk areas requiring human approval")
    risk_level: str = Field(..., description="HIGH or LOW")
    matched_keywords: List[str] = Field(default_factory=list, description="List of sensitive risk keywords detected")
    reason: str = Field(..., description="Human-readable explanation of risk level assessment")


class HumanApprovalChecker:
    """Evaluates patch risk based on file paths, function names, and diff contents."""

    def __init__(self, high_risk_keywords: set = None):
        self.keywords = high_risk_keywords or HIGH_RISK_KEYWORDS

    def evaluate_patch_risk(self, target_file: str, function_name: str, unified_diff: str) -> RiskAssessment:
        """Evaluate whether a proposed patch poses high operational/security risk requiring human sign-off."""
        matched: List[str] = []

        combined_text = f"{target_file} {function_name} {unified_diff}".lower()
        tokens = set(re.findall(r'[a-z_]+', combined_text))

        for kw in self.keywords:
            if kw in tokens or any(kw in token for token in tokens if len(token) > 3 and kw in token):
                matched.append(kw)

        if matched:
            reason = (
                f"Patch modifies sensitive code area matching high-risk keywords: {', '.join(matched)}. "
                f"Requires human sign-off before auto-applying."
            )
            logger.warning(f"HIGH RISK PATCH DETECTED: {reason}")
            return RiskAssessment(
                is_risky=True,
                risk_level="HIGH",
                matched_keywords=matched,
                reason=reason,
            )

        return RiskAssessment(
            is_risky=False,
            risk_level="LOW",
            matched_keywords=[],
            reason="Patch modifies standard application logic with low operational risk.",
        )
