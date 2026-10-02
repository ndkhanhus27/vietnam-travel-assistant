import { describe, expect, it } from "vitest";
import { SseParser } from "./sse";

describe("SseParser", () => {
  it("buffers partial frames and preserves Vietnamese UTF-8", () => {
    const parser = new SseParser();
    expect(parser.feed('event: stage\ndata: {"stage":"planning","message":"Dang phan')).toEqual([]);
    const events = parser.feed(' tich yeu cau"}\n\n');
    expect(events).toEqual([{
      event: "stage",
      data: { stage: "planning", message: "Dang phan tich yeu cau" },
    }]);
  });

  it("parses multiple event types and ignores comments", () => {
    const parser = new SseParser();
    const events = parser.feed([
      ": ping",
      "event: connected",
      'data: {"conversation_id":"c1"}',
      "",
      "event: tool",
      'data: {"tool":"weather","task_id":"t1","status":"started"}',
      "",
      "event: error",
      'data: {"code":"FAILED","message":"Khong the hoan tat"}',
      "",
      "",
    ].join("\n"));
    expect(events.map((event) => event.event)).toEqual(["connected", "tool", "error"]);
  });
});
