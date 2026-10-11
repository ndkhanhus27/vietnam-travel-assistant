import { describe, expect, it } from "vitest";
import { loadLanguage } from "./LocaleProvider";

describe("language persistence", () => {
  it("loads English and defaults safely to Vietnamese", () => {
    expect(loadLanguage({ getItem: () => "en" })).toBe("en");
    expect(loadLanguage({ getItem: () => "vi" })).toBe("vi");
    expect(loadLanguage({ getItem: () => "unknown" })).toBe("vi");
  });
});
