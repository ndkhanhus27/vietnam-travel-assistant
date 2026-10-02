import { describe, expect, it } from "vitest";
import { reconcileCompletedMessages } from "./chatState";
import type { ChatResponse, MessageResponse } from "./types";

const base = { intent: null, citations: null, warnings: null, created_at: "2026-09-30T00:00:00Z" };
const optimistic: MessageResponse = { ...base, id: "optimistic", role: "user", content: "Plan Hue", sequence_no: Number.MAX_SAFE_INTEGER };
const result: ChatResponse = {
  conversation_id: "c1",
  user_message: { ...base, id: "user-1", role: "user", content: "Plan Hue", sequence_no: 1 },
  assistant_message: { ...base, id: "assistant-1", role: "assistant", content: "Answer", sequence_no: 2 },
  agent_run: { id: "run-1", status: "degraded", intent: null, retrieval_mode: null, latency_ms: 10, retry_count: 0, tools_used: null, created_at: base.created_at, completed_at: base.created_at },
};

describe("reconcileCompletedMessages", () => {
  it("replaces the optimistic turn with persisted messages without duplicates", () => {
    const messages = reconcileCompletedMessages([optimistic], optimistic.id, result);
    expect(messages.map((message) => message.id)).toEqual(["user-1", "assistant-1"]);
    expect(messages.filter((message) => message.role === "user")).toHaveLength(1);
  });
});
