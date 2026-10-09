import { describe, expect, it } from "vitest";
import { isGoogleSignInOriginSupported } from "./GoogleSignIn";

describe("Google Sign-In origin policy", () => {
  it("allows HTTPS and local development origins", () => {
    expect(isGoogleSignInOriginSupported("https:", "travel.example.com")).toBe(true);
    expect(isGoogleSignInOriginSupported("http:", "localhost")).toBe(true);
    expect(isGoogleSignInOriginSupported("http:", "127.0.0.1")).toBe(true);
  });

  it("rejects an HTTP public IP origin", () => {
    expect(isGoogleSignInOriginSupported("http:", "203.0.113.10")).toBe(false);
  });
});
