export type UserResponse = {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  is_verified: boolean;
  is_admin: boolean;
};

export type AdminOverview = {
  total_users: number;
  active_users: number;
  total_conversations: number;
  total_runs: number;
  successful_runs: number;
  degraded_runs: number;
  failed_runs: number;
  requests_today: number;
  average_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  tool_usage: Record<string, number>;
};

export type AdminUser = UserResponse & {
  is_active: boolean;
  created_at: string;
  conversation_count: number;
  run_count: number;
};

export type AdminUserPage = {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
};

export type AdminAgentRun = {
  id: string;
  conversation_id: string;
  user_email: string;
  user_display_name: string | null;
  intent: string | null;
  retrieval_mode: string | null;
  status: "running" | "success" | "degraded" | "failed";
  latency_ms: number | null;
  retry_count: number;
  tools_used: string[] | null;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
};

export type AdminAgentRunPage = {
  items: AdminAgentRun[];
  total: number;
  limit: number;
  offset: number;
};

export type AuthResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: UserResponse;
};

export type ConversationResponse = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  is_archived: boolean;
};

export type CitationResponse = {
  citation_id: string;
  evidence_id: string | null;
  task_id: string | null;
  title: string;
  url: string | null;
  source_type: string;
  tool: string | null;
  provider: string | null;
  metadata: Record<string, unknown>;
};

export type MessageResponse = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sequence_no: number;
  intent: string | null;
  citations: CitationResponse[] | null;
  warnings: string[] | null;
  created_at: string;
};

export type AgentRunResponse = {
  id: string;
  status: "running" | "success" | "degraded" | "failed";
  intent: string | null;
  retrieval_mode: string | null;
  latency_ms: number | null;
  retry_count: number;
  tools_used: string[] | null;
  created_at: string;
  completed_at: string | null;
};

export type ChatResponse = {
  conversation_id: string;
  user_message: MessageResponse;
  assistant_message: MessageResponse;
  agent_run: AgentRunResponse;
};

export type AgentProgressStage = "planning" | "retrieving" | "validating" | "reasoning" | "generating";

export type StreamEvent =
  | { event: "connected"; data: { conversation_id: string } }
  | { event: "stage"; data: { stage: AgentProgressStage; message?: string } }
  | { event: "tool"; data: { tool: string; task_id: string; status: string } }
  | { event: "completed"; data: ChatResponse }
  | { event: "error"; data: { code: string; message: string } };
