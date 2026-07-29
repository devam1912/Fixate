"""Human Approval Gate and Safety Package."""

from fixate.safety.approval import HumanApprovalChecker, RiskAssessment

SafetyChecker = HumanApprovalChecker

__all__ = ["HumanApprovalChecker", "SafetyChecker", "RiskAssessment"]
