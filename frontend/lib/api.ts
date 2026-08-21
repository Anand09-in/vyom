import { Company, ConversationSummary, HistoryTurn } from "@/types";
import { getIdToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SESSION_KEY = "vyom_session_id";

/** crypto.randomUUID() only exists in a secure context (HTTPS, or literally
 * `localhost`) — it's undefined when the app is served over plain HTTP from
 * a real host/IP, which throws and breaks the whole page. These ids are
 * just opaque client-side identifiers (message/session ids), never used for
 * anything security-sensitive, so a Math.random()-based fallback is fine. */
export function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Every Vyom endpoint except /health requires a Cognito ID token — see
 * api/auth.py. Returns {} (no header) if there's no signed-in session,
 * which the backend will correctly reject with 401 rather than crash on. */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Reads the persisted session id, or mints and persists a new one.
 * localStorage (not sessionStorage) so conversation memory survives a
 * browser refresh, not just the current tab's lifetime. */
export function getOrCreateSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = newId();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

/** Sets the active session id explicitly — used when switching to or
 * starting a conversation, as opposed to getOrCreateSessionId's lazy
 * read-or-mint behavior. */
export function setActiveSessionId(id: string): void {
  localStorage.setItem(SESSION_KEY, id);
}

export async function queryStream(
  query: string,
  company: string | null,
  sessionId: string,
  onRoute: (sources: string[], rationale: string) => void,
  onToken: (token: string) => void,
  onDone: (data: {
    citations: object[];
    sources_used: string[];
    latency_ms: number;
    session_id: string;
  }) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ query, company: company || null, session_id: sessionId }),
  });

  if (!res.ok) throw new Error(`API error ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
        continue;
      }
      if (!line.startsWith("data:")) continue;

      const raw = line.slice(5).trim();
      if (!raw) continue;

      if (currentEvent === "route") {
        const parsed = JSON.parse(raw);
        onRoute(parsed.sources ?? [], parsed.rationale);
      } else if (currentEvent === "done") {
        const parsed = JSON.parse(raw);
        if (parsed.session_id) setActiveSessionId(parsed.session_id);
        onDone(parsed);
      } else if (currentEvent === "token") {
        onToken(JSON.parse(raw));
      }
    }
  }
}

export async function fetchHistory(sessionId: string): Promise<HistoryTurn[]> {
  const res = await fetch(`${API_BASE}/query/history/${sessionId}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.turns ?? [];
}

export async function deleteHistory(sessionId: string): Promise<void> {
  await fetch(`${API_BASE}/query/history/${sessionId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
}

export async function fetchCompanies(): Promise<Company[]> {
  const res = await fetch(`${API_BASE}/query/companies`, {
    headers: await authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.companies ?? [];
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/query/conversations`, {
    headers: await authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.conversations ?? [];
}

export async function submitFeedback(
  query_log_id: number,
  rating: 1 | -1,
  comment?: string
): Promise<void> {
  await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ query_log_id, rating, comment }),
  });
}