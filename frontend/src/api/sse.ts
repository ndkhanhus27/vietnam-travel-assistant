import type { StreamEvent } from "./types";

export class SseParser {
  private buffer = "";

  feed(chunk: string): StreamEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const frames = this.buffer.split("\n\n");
    this.buffer = frames.pop() ?? "";
    return frames.flatMap((frame) => this.parseFrame(frame));
  }

  finish(): StreamEvent[] {
    const frame = this.buffer.trim();
    this.buffer = "";
    return frame ? this.parseFrame(frame) : [];
  }

  private parseFrame(frame: string): StreamEvent[] {
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const separator = line.indexOf(":");
      const field = separator < 0 ? line : line.slice(0, separator);
      let value = separator < 0 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") eventName = value;
      if (field === "data") dataLines.push(value);
    }
    if (!dataLines.length || !["connected", "stage", "tool", "completed", "error"].includes(eventName)) return [];
    return [{ event: eventName, data: JSON.parse(dataLines.join("\n")) } as StreamEvent];
  }
}
