"""Risk classification gating automatic application of a verified patch.

A patch reaching this stage has already passed its tests, so this gate is not
asking "is it correct?" but "is this code where a passing test is sufficient
evidence?". For authentication, payments, and schema migrations it is not: those
failures are silent, expensive, and often invisible to the suite that just went
green.

Matching is token-based. The previous implementation tested raw substrings, which
made every identifier containing "card" (discard, cardinality, wildcard) look like
a payment change. False positives are not harmless here -- a gate that fires on
routine patches trains operators to approve without reading, which costs exactly
the scrutiny the gate exists to buy.
"""

import logging
import re
from typing import Iterable, List, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Identifier tokens that place a change in a sensitive domain.
HIGH_RISK_KEYWORDS: Set[str] = {
    # Authentication, authorization, and secrets
    "auth", "authenticate", "authorization", "login", "logout", "password", "passwd",
    "token", "jwt", "oauth", "session", "credential", "credentials", "secret",
    "apikey", "rbac", "permission", "permissions", "privilege", "signature", "hmac",
    # Money movement
    "payment", "payments", "billing", "invoice", "stripe", "paypal", "checkout",
    "charge", "refund", "payout", "transfer", "withdraw", "balance", "ledger",
    "currency", "price", "pricing", "subscription",
    # Destructive or structural data operations
    "migration", "migrations", "schema", "drop", "truncate", "alter", "delete",
    "purge", "destroy",
}

# Patterns matched against added lines only. These describe an *action* the patch
# introduces, which a keyword in a filename cannot capture.
HIGH_RISK_PATTERNS = [
    (re.compile(r"\bDROP\s+(TABLE|DATABASE|COLUMN)\b", re.IGNORECASE), "SQL DROP statement"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "SQL TRUNCATE statement"),
    (re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE), "SQL DELETE statement"),
    (re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE), "SQL ALTER statement"),
    (re.compile(r"\bshutil\.rmtree\b"), "recursive filesystem deletion"),
    (re.compile(r"\bos\.(remove|unlink|rmdir)\b"), "filesystem deletion"),
    (re.compile(r"\bsubprocess\.|\bos\.system\b"), "subprocess execution"),
    (re.compile(r"\beval\s*\(|\bexec\s*\("), "dynamic code execution"),
    (re.compile(r"\bverify\s*=\s*False\b"), "disabled TLS verification"),
    (re.compile(r"#\s*nosec|#\s*type:\s*ignore"), "suppressed security or type check"),
]

_TOKEN = re.compile(r"[A-Za-z]+")


class RiskAssessment(BaseModel):
    """Structured risk verdict for a verified patch."""

    is_risky: bool = Field(..., description="True if the patch needs human sign-off")
    risk_level: str = Field(..., description="HIGH or LOW")
    matched_keywords: List[str] = Field(default_factory=list, description="Signals that fired")
    reason: str = Field(..., description="Human-readable explanation of the verdict")


class HumanApprovalChecker:
    """Classifies whether a patch may be applied without human review."""

    def __init__(self, high_risk_keywords: Iterable[str] = None):
        self.keywords = set(high_risk_keywords) if high_risk_keywords else set(HIGH_RISK_KEYWORDS)

    def evaluate_patch_risk(
        self, target_file: str, function_name: str, unified_diff: str
    ) -> RiskAssessment:
        """Decide whether this patch requires sign-off before being applied."""
        matched: List[str] = []

        # Identifier tokens from the path and symbol name: where the change lands.
        for token in self._tokens(f"{target_file} {function_name}"):
            if token in self.keywords and token not in matched:
                matched.append(token)

        # Tokens from added lines only. Removed lines describe code on its way out,
        # and judging a patch by what it deletes inverts the signal.
        added_lines = [
            line[1:] for line in (unified_diff or "").splitlines() if line.startswith("+")
        ]
        added_text = "\n".join(added_lines)
        for token in self._tokens(added_text):
            if token in self.keywords and token not in matched:
                matched.append(token)

        for pattern, label in HIGH_RISK_PATTERNS:
            if pattern.search(added_text) and label not in matched:
                matched.append(label)

        if matched:
            reason = (
                f"This patch touches a sensitive area ({', '.join(sorted(matched))}). "
                "Passing tests are not sufficient evidence of safety here, because failures "
                "in this domain are typically silent. Human sign-off is required before "
                "the change is applied."
            )
            logger.warning("HIGH risk patch for %s: %s", target_file, ", ".join(sorted(matched)))
            return RiskAssessment(
                is_risky=True, risk_level="HIGH", matched_keywords=matched, reason=reason
            )

        return RiskAssessment(
            is_risky=False,
            risk_level="LOW",
            matched_keywords=[],
            reason=(
                "This patch modifies ordinary application logic with no authentication, "
                "payment, or destructive data operations detected. Its passing tests are "
                "adequate evidence for automatic application."
            ),
        )

    @staticmethod
    def _tokens(text: str) -> Set[str]:
        """Split text into lowercase alphabetic identifier tokens.

        Splitting on non-alpha boundaries means ``login_user`` yields {login, user}
        while ``discard`` stays whole and never matches ``card``.
        """
        return {match.group(0).lower() for match in _TOKEN.finditer(text or "")}
