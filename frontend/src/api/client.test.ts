import { beforeEach, describe, expect, it, vi } from "vitest";

class MemoryStorage {
  private values = new Map<string, string>();
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
  clear() { this.values.clear(); }
}

const eventTarget = new EventTarget();
Object.defineProperty(globalThis, "localStorage", { value: new MemoryStorage(), configurable: true });
Object.defineProperty(globalThis, "window", { value: eventTarget, configurable: true });

const user = { id: "u1", email: "user@example.com", display_name: "User", avatar_url: null, is_verified: false };
const auth = { access_token: "access-new", refresh_token: "refresh-new", token_type: "bearer" as const, expires_in: 900, user };

describe("API client", () => {
  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("stores both application tokens and user after login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(auth), { status: 200, headers: { "Content-Type": "application/json" } })));
    const { api, sessionStore } = await import("./client");
    const result = await api.login({ email: "user@example.com", password: "password" });
    expect(result.user).toEqual(user);
    expect(sessionStore.get()).toMatchObject({ access_token: "access-new", refresh_token: "refresh-new", user });
  });

  it("exchanges a Google credential through the backend auth endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(auth), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api, sessionStore } = await import("./client");

    await api.googleLogin("mock-google-credential");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/google",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ credential: "mock-google-credential" }),
      }),
    );
    expect(sessionStore.get()).toMatchObject({
      access_token: "access-new",
      refresh_token: "refresh-new",
      user,
    });
  });

  it("uses one rotating refresh for concurrent 401 responses and retries once", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      const authorization = new Headers(init?.headers).get("Authorization");
      if (url.endsWith("/auth/refresh")) return new Response(JSON.stringify(auth), { status: 200 });
      if (url.endsWith("/users/me") && authorization === "Bearer access-old") return new Response(JSON.stringify({ detail: "expired" }), { status: 401 });
      return new Response(JSON.stringify(user), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { api, sessionStore } = await import("./client");
    sessionStore.set({ ...auth, access_token: "access-old", refresh_token: "refresh-old" });
    const [first, second] = await Promise.all([api.me(), api.me()]);
    expect(first).toEqual(user);
    expect(second).toEqual(user);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/users/me"))).toHaveLength(4);
  });

  it("clears the session when refresh fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const status = String(input).endsWith("/auth/refresh") ? 401 : 401;
      return new Response(JSON.stringify({ detail: "Invalid refresh token" }), { status });
    }));
    const { api, sessionStore } = await import("./client");
    sessionStore.set({ ...auth, access_token: "expired", refresh_token: "invalid" });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(sessionStore.get()).toBeNull();
  });

  it("rejects stream 429 before parsing a response body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Too many requests" }), { status: 429, headers: { "Retry-After": "17" } })));
    const { api, sessionStore } = await import("./client");
    sessionStore.set(auth);
    const callback = vi.fn();
    await expect(api.streamMessage("c1", "hello", callback)).rejects.toMatchObject({ status: 429, retryAfter: 17 });
    expect(callback).not.toHaveBeenCalled();
  });
});
