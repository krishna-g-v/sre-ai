export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
  display_name: string;
  is_superuser: boolean;
  group_ids: string[];
}

export interface ChatSession {
  id: string;
  title: string;
  status: "general" | "pinned";
  pinned_document_id: string | null;
  pinned_document_title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  message_category: "general" | "document_topic" | "live_ops" | null;
  created_at: string;
}

export interface SendMessageResponse {
  session: ChatSession;
  message: ChatMessage;
  retrieved_titles: string[];
  drifted: boolean;
}

export interface DocumentOut {
  id: string;
  title: string;
  source_filename: string;
  owner_scope: "group" | "personal";
  group_ids: string[];
  content_type: "pdf" | "docx" | "md" | "txt";
  status: "processing" | "ready" | "failed";
  tags: string[];
  chunk_strategy: "whole_document" | "best_effort";
  best_effort_target_size: string | null;
  converted_to_markdown: boolean;
}

export type AgentCategory = "Grafana" | "Synthetics" | "Prometheus" | "Kubernetes" | "CloudWatch" | "Custom";
export type SeverityLevel = "Critical" | "Warning" | "Info";
export type NoiseVerdict = "Real Incident" | "Filtered Noise" | "Investigating";

export interface Agent {
  id: string;
  name: string;
  description: string;
  owner: string;
  category: AgentCategory;
  enabled: boolean;
  trigger_type: string;
  webhook_path: string;
  triage_prompt: string;
  severity_rule: string;
  auto_remediation_enabled: boolean;
  group_ids: string[];
  last_run_at: string | null;
  total_triaged: number;
  real_issues_detected: number;
  noise_filtered_count: number;
  created_at: string;
}

export interface CanaryStep {
  name: string;
  durationMs: number;
  status: "success" | "failed" | "skipped";
  errorDetails?: string;
}

export interface TriageReport {
  summary: string;
  is_real_issue: boolean;
  noise_reason: string;
  impact_level: SeverityLevel;
  root_cause_hypothesis: string;
  step_by_step_remediation: string[];
  runbook_url?: string;
  recommended_action: string;
  estimated_resolution_minutes: number;
}

export interface Alert {
  id: string;
  agent_id: string | null;
  agent_name: string;
  source: AgentCategory;
  title: string;
  occurred_at: string;
  status: "Firing" | "Resolved" | "Triaged";
  severity: SeverityLevel;
  verdict: NoiseVerdict;
  raw_payload: Record<string, unknown>;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  canary_name: string | null;
  canary_start_url: string | null;
  canary_end_url: string | null;
  canary_error_step: string | null;
  canary_error_msg: string | null;
  canary_steps: CanaryStep[] | null;
  runbook_link: string | null;
  triage_report: TriageReport | null;
  group_ids: string[];
  created_at: string;
}

export interface DashboardStats {
  total_alerts_ingested: number;
  real_incidents_count: number;
  filtered_noise_count: number;
  active_agents_count: number;
  auto_triaged_percentage: number;
  noise_reduction_rate: number;
}

export interface GroupOut {
  id: string;
  name: string;
  description: string;
}

export interface UserOut {
  id: string;
  username: string;
  display_name: string;
  is_superuser: boolean;
  group_ids: string[];
}

export interface UserAwsAccount {
  id: string;
  label: string;
  account_id: string;
  role_arn: string;
  external_id: string;
  region: string;
  has_own_credentials: boolean;
}
