import { describe, expect, it } from "vitest";
import { loadAppearance, loadThemeMode, saveAppearance } from "./AppearanceProvider";

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

  it("loads light, dark, and system display modes safely", () => {
    expect(loadThemeMode({ getItem: () => "dark" })).toBe("dark");
    expect(loadThemeMode({ getItem: () => "system" })).toBe("system");
    expect(loadThemeMode({ getItem: () => "unknown" })).toBe("light");
  });
});
