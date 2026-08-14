const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function queryStream(
  query: string,
  company: string | null,
  onRoute: (sources: string[], rationale: string) => void,
  onToken: (token: string) => void,
  onDone: (data: {
    citations: object[];
    sources_used: string[];
    latency_ms: number;
  }) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, company: company || null }),
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
        onDone(JSON.parse(raw));
      } else if (currentEvent === "token") {
        onToken(JSON.parse(raw));
      }
    }
  }
}

export async function submitFeedback(
  query_log_id: number,
  rating: 1 | -1,
  comment?: string
): Promise<void> {
  await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query_log_id, rating, comment }),
  });
}