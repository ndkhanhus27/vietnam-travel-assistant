import { describe, expect, it } from "vitest";
import { loadLanguage } from "./LocaleProvider";

describe("language persistence", () => {
  it("uses Vietnamese even when English was previously saved", () => {
    expect(loadLanguage({ getItem: () => "en" })).toBe("vi");
    expect(loadLanguage({ getItem: () => "vi" })).toBe("vi");
    expect(loadLanguage({ getItem: () => "unknown" })).toBe("vi");
  });
});
