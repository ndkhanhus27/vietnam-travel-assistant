import { describe, expect, it } from "vitest";
import { isGmailAddress } from "./emailPolicy";

describe("Gmail account policy", () => {
  it("allows case-insensitive Gmail addresses and plus aliases", () => {
    expect(isGmailAddress(" User+travel@GMAIL.COM ")).toBe(true);
  });
  it("rejects other domains and suffix lookalikes", () => {
    for (const value of ["user@outlook.com", "user@hotmail.com", "user@gmail.com.attacker.com", "user@company.com", "@gmail.com", "user@@gmail.com"])
      expect(isGmailAddress(value)).toBe(false);
  });
});
