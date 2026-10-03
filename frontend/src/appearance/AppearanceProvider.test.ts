import { describe, expect, it } from "vitest";
import { loadAppearance, saveAppearance } from "./AppearanceProvider";

describe("appearance persistence", () => {
  it("loads each supported appearance and falls back safely", () => {
    expect(loadAppearance({ getItem: () => "yellow" })).toBe("yellow");
    expect(loadAppearance({ getItem: () => "green" })).toBe("green");
    expect(loadAppearance({ getItem: () => "unknown" })).toBe("pink");
  });

  it("persists the selected appearance", () => {
    const values = new Map<string, string>();
    saveAppearance("green", {
      setItem: (key, value) => values.set(key, value),
    });
    expect(values.get("vta_appearance")).toBe("green");
  });
});
