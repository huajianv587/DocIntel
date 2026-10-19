export type User = { id: string; email: string; role: "agent" | "admin"; is_active: boolean };
export type Citation = { chunk_id: string; source_id: string; source_type: string; title: string; page?: number | null; section: string; url: string; score: number; snippet: string };
export type ToolEvent = { name: string; status: string; latency_ms: number; output_summary: string };
export type Result = { trace_id: string; route: string; answer: string; abstained: boolean; confidence: number; citations: Citation[]; tool_events: ToolEvent[]; model?: string | null; token_usage: Record<string, number>; cost_usd: number; latency_ms: number; escalation?: Record<string, unknown> | null };
export type Conversation = { id: string; title: string; status: string; domain: string; created_at: string; updated_at: string };
export type Message = { id: string; role: string; content: string; trace_id?: string | null; citations: Citation[]; tool_events: ToolEvent[]; model?: string | null; token_usage: Record<string, unknown>; latency_ms?: number | null; created_at: string };
export type ConversationDetail = Conversation & { messages: Message[] };
export type Ticket = { id: string; conversation_id?: string | null; created_by?: string; assignee_id?: string | null; status: "draft" | "queued" | "in_progress" | "resolved" | "closed"; title: string; summary: string; attempted_steps: string[]; citations: Citation[]; recommendation: string; metadata?: Record<string, unknown>; created_at: string; updated_at: string };
export type TicketCreate = { conversation_id?: string | null; title: string; summary: string; attempted_steps?: string[]; citations?: Partial<Citation>[]; recommendation?: string; metadata?: Record<string, unknown> };

const tokenKey = "docintel.access_token";
export const token = () => localStorage.getItem(tokenKey);
export const saveToken = (value: string) => localStorage.setItem(tokenKey, value);
export const clearToken = () => localStorage.removeItem(tokenKey);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json");
  const access = token();
  if (access) headers.set("authorization", `Bearer ${access}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) => request<{ access_token: string; user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request<User>("/auth/me"),
  conversations: () => request<Conversation[]>("/api/conversations"),
  createConversation: (title = "New support conversation") => request<Conversation>("/api/conversations", { method: "POST", body: JSON.stringify({ title, domain: "tech_support" }) }),
  conversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  conversationTraces: (id: string) => request<Array<Record<string, unknown>>>(`/api/conversations/${id}/trace`),
  send: (id: string, query: string, code?: string) => request<Result>(`/api/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ query, code }) }),
  sendStream: async (id: string, query: string, code: string | undefined, onToken: (text: string) => void) => {
    const headers = new Headers({ "content-type": "application/json" });
    const access = token();
    if (access) headers.set("authorization", `Bearer ${access}`);
    const response = await fetch(`/api/conversations/${id}/messages/stream`, { method: "POST", headers, body: JSON.stringify({ query, code }) });
    if (!response.ok || !response.body) throw new Error(await response.text());
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let result: Result | null = null;
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      for (const frame of frames) {
        const event = frame.match(/^event: (.+)$/m)?.[1];
        const data = frame.match(/^data: (.+)$/m)?.[1];
        if (!event || !data) continue;
        if (event === "token") onToken(String(JSON.parse(data).text || ""));
        if (event === "result") result = JSON.parse(data) as Result;
      }
      if (chunk.done) break;
    }
    if (!result) throw new Error("Stream ended without a result");
    return result;
  },
  tickets: () => request<Ticket[]>("/api/tickets"),
  createTicket: (payload: TicketCreate) => request<Ticket>("/api/tickets", { method: "POST", body: JSON.stringify(payload) }),
  updateTicket: (id: string, status: Ticket["status"]) => request<Ticket>(`/api/tickets/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  adminMetrics: () => request<Record<string, unknown>>("/api/admin/metrics"),
  traces: () => request<Array<Record<string, unknown>>>("/api/admin/traces"),
  sources: () => request<Array<Record<string, unknown>>>("/api/admin/sources"),
  evaluations: () => request<Array<Record<string, unknown>>>("/api/admin/evaluations"),
  runEvaluation: (payload: { domain?: string; version_label?: string; gold_path?: string }) => request<Record<string, unknown>>("/api/admin/evaluations/run", { method: "POST", body: JSON.stringify(payload) }),
  syncSource: (id: string) => request<Record<string, unknown>>(`/api/admin/sources/${id}/sync`, { method: "POST" }),
  pauseSource: (id: string) => request<Record<string, unknown>>(`/api/admin/sources/${id}/pause`, { method: "POST" }),
  resumeSource: (id: string) => request<Record<string, unknown>>(`/api/admin/sources/${id}/resume`, { method: "POST" }),
  users: () => request<User[]>("/api/admin/users"),
  updateUser: (id: string, payload: { role?: User["role"]; is_active?: boolean }) => request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
};
