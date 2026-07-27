"""Evaluation metrics calculation model."""

from typing import List, Dict
from pydantic import BaseModel, Field


class CaseMetricResult(BaseModel):
    case_id: str
    bug_category: str
    localization_correct: bool
    first_attempt_passed: bool
    final_verified_passed: bool
    attempts_used: int
    execution_time_seconds: float
    estimated_token_cost: float


class EvalScorecard(BaseModel):
    """Aggregate benchmark metrics scorecard."""
    total_cases: int
    successful_fixes: int
    localization_accuracy_pct: float
    first_attempt_success_pct: float
    overall_fix_rate_pct: float
    average_attempts_per_case: float
    average_execution_time_seconds: float
    total_token_cost_usd: float
    case_results: List[CaseMetricResult] = Field(default_factory=list)
