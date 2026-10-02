export type UserResponse = {
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  is_verified: boolean;
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
