import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MessageResponse } from "../api/types";
import {
  consumePendingConversationNavigation,
  createOptimisticMessageId,
  MessageView,
} from "./TravelChatPage";
import { MarkdownLite } from "../components/MarkdownLite";

const message: MessageResponse = {
  id: "assistant-1",
  role: "assistant",
  content: "## Travel answer",
  sequence_no: 2,
  intent: null,
  citations: [
    { citation_id: "1", evidence_id: "e1", task_id: null, title: "Official source", url: "https://example.com", source_type: "web", tool: null, provider: null, metadata: {} },
    { citation_id: "2", evidence_id: null, task_id: "weather-1", title: "Weather result", url: null, source_type: "tool", tool: "weather", provider: null, metadata: {} },
  ],
  warnings: null,
  created_at: "2026-09-30T00:00:00Z",
};

describe("MessageView", () => {
  it("renders linked and non-linked citations without fabricating URLs", () => {
    const html = renderToStaticMarkup(<MessageView message={message} degraded={false} />);
    expect(html).toContain('href="https://example.com"');
    expect(html).toContain("Weather result");
    expect((html.match(/href=/g) || [])).toHaveLength(1);
  });

  it("keeps degraded answers usable and adds a warning", () => {
    const html = renderToStaticMarkup(<MessageView message={message} degraded />);
    expect(html).toContain("Travel answer");
    expect(html).toContain("Một số thông tin chưa thể được kiểm chứng đầy đủ.");
  });
});

describe("MarkdownLite", () => {
  it("renders headings, links, images and code without injecting HTML", () => {
    const markdown = "## Huế\n[Xem nguồn](https://example.com/source)\n![Đại Nội](https://example.com/hue.jpg)\n`inline`\n```js\nalert('safe text')\n```";
    const html = renderToStaticMarkup(<MarkdownLite content={markdown} />);

    expect(html).toContain("<h2>Huế</h2>");
    expect(html).toContain('href="https://example.com/source"');
    expect(html).toContain('src="https://example.com/hue.jpg"');
    expect(html).toContain("<code>inline</code>");
    expect(html).toContain('class="language-js"');
  });

  it("blocks unsafe link and image protocols", () => {
    const html = renderToStaticMarkup(<MarkdownLite content="[bad](javascript:alert(1))\n![bad](data:text/html,bad)" />);

    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("data:text");
    expect(html).not.toContain("href=");
    expect(html).not.toContain("src=");
  });
});

describe("createOptimisticMessageId", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("works when randomUUID is unavailable on an insecure HTTP origin", () => {
    vi.stubGlobal("crypto", {});

    expect(createOptimisticMessageId()).toMatch(/^optimistic-\d+-[a-z0-9]+$/);
  });
});

describe("consumePendingConversationNavigation", () => {
  it("preserves messages once when the first send navigates to its new conversation", () => {
    const pending = { current: "conversation-1" };

    expect(consumePendingConversationNavigation(pending, "conversation-1")).toBe(true);
    expect(pending.current).toBeNull();
    expect(consumePendingConversationNavigation(pending, "conversation-1")).toBe(false);
  });
});
