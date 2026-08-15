export interface TelemetryEvent {
  event_id: string;
  timestamp: string;
  incident_id: string;
  agent: string;
  action: string;
  input_summary: string;
  output_summary: string;
  result: 'SUCCESS' | 'FAILURE' | 'IN_PROGRESS' | 'REQUIRES_APPROVAL';
  details?: any;
}

export interface GeneratedPatch {
  target_file: string;
  unified_diff: string;
  explanation: string;
  lines_changed: number;
}

export interface RiskAssessment {
  is_risky: boolean;
  risk_level: 'HIGH' | 'LOW';
  matched_keywords: string[];
  reason: string;
}

export interface IncidentSummary {
  incident_id: string;
  state: 'IDLE' | 'LOCALIZING' | 'RETRIEVING' | 'PATCHING' | 'VERIFYING' | 'CHECKING_SAFETY' | 'COMPLETED' | 'FAILED' | 'PENDING_APPROVAL';
  language?: string;
  verified_by?: string;
  failing_test: string;
  exception_type: string;
  target_file?: string;
  suspect_function?: string;
  verified_patch?: GeneratedPatch;
  risk_assessment?: RiskAssessment;
  total_attempts: number;
  failure_report?: string;
  telemetry_events: TelemetryEvent[];
  pull_request?: PullRequestResult;
}

export interface PullRequestResult {
  url: string;
  branch: string;
  base: string;
}

export interface RepositoryFailure {
  failure_id: string;
  language: string;
  test_name: string;
  exception_type: string;
  exception_message: string;
  failing_file: string;
  failing_line: number;
  raw_log: string;
}

export interface RepositoryLanguageReport {
  language: string;
  status: 'failed' | 'passed' | 'no_tests' | 'no_output' | 'unparsed_failure' | 'not_run';
  install_detail: string;
  failure_count: number;
  log_excerpt: string;
}

export interface RepositoryScan {
  scan_id: string;
  repo_path: string;
  repo_url?: string;
  languages: RepositoryLanguageReport[];
  failures: RepositoryFailure[];
  total_failures: number;
}

export interface CodeGraphNode {
  id: string;
  label: string;
  symbol_type: string;
  file_path: string;
  is_test: boolean;
}

export interface CodeGraphEdge {
  source: string;
  target: string;
  relation: string;
}

export interface CodeGraphData {
  nodes: CodeGraphNode[];
  edges: CodeGraphEdge[];
}

export interface EvalCaseResult {
  case_id: string;
  bug_category: string;
  localization_correct: boolean;
  first_attempt_passed: boolean;
  final_verified_passed: boolean;
  attempts_used: number;
  execution_time_seconds: number;
  estimated_token_cost: number;
}

export interface EvalScorecard {
  total_cases: number;
  successful_fixes: number;
  localization_accuracy_pct: number;
  first_attempt_success_pct: number;
  overall_fix_rate_pct: number;
  average_attempts_per_case: number;
  average_execution_time_seconds: number;
  total_token_cost_usd: number;
  case_results: EvalCaseResult[];
}
