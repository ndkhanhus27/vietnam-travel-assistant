import { SseParser } from "./sse";
import type {
  AdminAgentRunPage,
  AdminOverview,
  AdminUser,
  AdminUserPage,
  AuthResponse,
  ChatResponse,
  ConversationResponse,
  MessageResponse,
  StreamEvent,
  UserResponse,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");
const SESSION_KEY = "vta_session";
const SESSION_EVENT = "vta:session-change";

export type StoredSession = Pick<AuthResponse, "access_token" | "refresh_token" | "user">;

export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfter?: number) {
    super(message);
  }
}

export const sessionStore = {
  get(): StoredSession | null {
    try {
      const value = localStorage.getItem(SESSION_KEY);
      return value ? JSON.parse(value) as StoredSession : null;
    } catch {
      localStorage.removeItem(SESSION_KEY);
      return null;
    }
  },
  set(result: AuthResponse) {
    const session: StoredSession = {
      access_token: result.access_token,
      refresh_token: result.refresh_token,
      user: result.user,
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    window.dispatchEvent(new Event(SESSION_EVENT));
  },
  updateUser(user: UserResponse) {
    const session = this.get();
    if (!session) return;
    localStorage.setItem(SESSION_KEY, JSON.stringify({ ...session, user }));
    window.dispatchEvent(new Event(SESSION_EVENT));
  },
  clear() {
    localStorage.removeItem(SESSION_KEY);
    window.dispatchEvent(new Event(SESSION_EVENT));
  },
  event: SESSION_EVENT,
};

let refreshPromise: Promise<AuthResponse> | null = null;

function retryAfter(response: Response) {
  const value = Number(response.headers.get("Retry-After"));
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function disableGoogleAutoSelect() {
  window.google?.accounts.id.disableAutoSelect?.();
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail = "Yêu cầu không thành công. Vui lòng thử lại.";
  try {
    const payload = await response.json() as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === "string") detail = payload.detail;
    else if (Array.isArray(payload.detail)) detail = payload.detail.map((item) => item.msg).filter(Boolean).join(" ") || detail;
  } catch {
    // Keep the safe public fallback.
  }
  if (response.status >= 500) detail = response.status === 502 ? "Trợ lý chưa thể hoàn tất câu trả lời." : "Dịch vụ đang tạm thời gián đoạn.";
  if (response.status === 429) detail = "Bạn thao tác quá nhanh. Vui lòng thử lại sau.";
  return new ApiError(response.status, detail, retryAfter(response));
}

async function fetchRequest(path: string, init: RequestInit, token?: string): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng.");
  }
}

async function refreshSession(): Promise<AuthResponse> {
  if (refreshPromise) return refreshPromise;
  const session = sessionStore.get();
  if (!session?.refresh_token) throw new ApiError(401, "Phiên đăng nhập đã hết hạn.");
  refreshPromise = (async () => {
    const response = await fetchRequest("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });
    if (!response.ok) throw await errorFromResponse(response);
    const result = await response.json() as AuthResponse;
    sessionStore.set(result);
    return result;
  })().catch((error) => {
    sessionStore.clear();
    throw error;
  }).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function authorizedResponse(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  let session = sessionStore.get();
  let response = await fetchRequest(path, init, session?.access_token);
  if (response.status === 401 && retry && session?.refresh_token) {
    await refreshSession();
    session = sessionStore.get();
    response = await fetchRequest(path, init, session?.access_token);
  }
  return response;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const response = await authorizedResponse(path, init, retry);
  if (!response.ok) throw await errorFromResponse(response);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function authenticate(path: string, body: object): Promise<AuthResponse> {
  const response = await fetchRequest(path, { method: "POST", body: JSON.stringify(body) });
  if (!response.ok) throw await errorFromResponse(response);
  const result = await response.json() as AuthResponse;
  sessionStore.set(result);
  return result;
}

export async function streamConversation(
  conversationId: string,
  content: string,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const path = `/conversations/${conversationId}/messages/stream`;
  const response = await authorizedResponse(path, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw await errorFromResponse(response);
  if (!response.body) throw new ApiError(0, "Máy chủ không trả về nội dung phản hồi.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  let terminalEventReceived = false;
  const emit = (event: StreamEvent) => {
    if (event.event === "completed" || event.event === "error") {
      terminalEventReceived = true;
    }
    onEvent(event);
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const event of parser.feed(decoder.decode(value, { stream: true }))) emit(event);
  }
  for (const event of parser.feed(decoder.decode())) emit(event);
  for (const event of parser.finish()) emit(event);
  if (!terminalEventReceived) {
    throw new ApiError(0, "Kết nối bị gián đoạn trước khi trợ lý trả về kết quả.");
  }
}

export const api = {
  register: (payload: { display_name?: string | null; email: string; password: string }) => authenticate("/auth/register", payload),
  login: (payload: { email: string; password: string }) => authenticate("/auth/login", payload),
  googleLogin: (credential: string, password?: string) => authenticate("/auth/google", { credential, ...(password === undefined ? {} : { password }) }),
  forgotPassword: async (email: string): Promise<{ message: string }> => {
    const response = await fetchRequest("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
    if (!response.ok) throw await errorFromResponse(response);
    return response.json();
  },
  resetPassword: async (token: string, password: string, confirmPassword: string): Promise<void> => {
    const response = await fetchRequest("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, password, confirm_password: confirmPassword }) });
    if (!response.ok) throw await errorFromResponse(response);
  },
  refresh: refreshSession,
  me: () => request<UserResponse>("/users/me"),
  updateMe: (displayName: string | null) => request<UserResponse>("/users/me", {
    method: "PATCH",
    body: JSON.stringify({ display_name: displayName }),
  }),
  createLocalPassword: (password: string, confirmPassword: string) => request<void>("/auth/local-password", {
    method: "POST",
    body: JSON.stringify({ password, confirm_password: confirmPassword }),
  }),
  listConversations: (includeArchived = false) => request<ConversationResponse[]>(`/conversations?limit=100&offset=0&include_archived=${includeArchived}`),
  getConversation: (id: string) => request<ConversationResponse>(`/conversations/${id}`),
  createConversation: () => request<ConversationResponse>("/conversations", { method: "POST", body: "{}" }),
  updateConversation: (id: string, payload: { title?: string | null; is_archived?: boolean }) => request<ConversationResponse>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  getMessages: (id: string) => request<MessageResponse[]>(`/conversations/${id}/messages`),
  sendMessage: (id: string, content: string) => request<ChatResponse>(`/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  streamMessage: streamConversation,
  logout: async () => {
    const refreshToken = sessionStore.get()?.refresh_token;
    try {
      if (refreshToken) await request<void>("/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) }, false);
    } finally {
      sessionStore.clear();
      disableGoogleAutoSelect();
    }
  },
  logoutAll: async () => {
    try {
      await request<void>("/auth/logout-all", { method: "POST" });
    } finally {
      sessionStore.clear();
      disableGoogleAutoSelect();
    }
  },
  adminOverview: () => request<AdminOverview>("/admin/overview"),
  adminUsers: (limit = 25, offset = 0) => request<AdminUserPage>(`/admin/users?limit=${limit}&offset=${offset}`),
  updateAdminUser: (id: string, isActive: boolean) => request<AdminUser>(`/admin/users/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  }),
  adminAgentRuns: (limit = 25, offset = 0) => request<AdminAgentRunPage>(`/admin/agent-runs?limit=${limit}&offset=${offset}`),
};
