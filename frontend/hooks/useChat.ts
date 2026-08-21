"use client";
import { useState, useCallback, useEffect } from "react";
import { Message, Citation, Company, ConversationSummary } from "@/types";
import {
  queryStream,
  submitFeedback,
  getOrCreateSessionId,
  setActiveSessionId,
  fetchHistory,
  deleteHistory,
  fetchConversations,
  fetchCompanies,
  newId,
} from "@/lib/api";

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [company, setCompany] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);

  const refreshConversations = useCallback(() => {
    fetchConversations().then(setConversations);
  }, []);

  // Restore the visible thread from Redis on mount — conversation memory
  // survives a refresh, not just the current tab's lifetime. Runs only in
  // the browser (localStorage isn't available during SSR).
  useEffect(() => {
    const id = getOrCreateSessionId();
    // sessionId is inherently client-only (reads localStorage, unavailable
    // during SSR) — it can't be computed via a useState lazy initializer
    // without risking a server/client hydration mismatch, so a synchronous
    // setState here is the correct pattern, not an anti-pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSessionId(id);
    fetchHistory(id).then((turns) => {
      if (turns.length === 0) return;
      const restored: Message[] = turns.flatMap((t) => [
        { id: newId(), role: "user" as const, content: t.question },
        { id: newId(), role: "assistant" as const, content: t.answer },
      ]);
      setMessages(restored);
    });
    refreshConversations();
    // Fetched once — 97 short strings, no reason to refetch per keystroke
    // or on every render. Reflects what's actually ingested (repo.py's
    // list_companies()), not a hardcoded frontend copy that could drift.
    fetchCompanies().then(setCompanies);
  }, [refreshConversations]);

  const send = useCallback(
    async (query: string) => {
      const userMsg: Message = {
        id: newId(),
        role: "user",
        content: query,
      };
      const assistantId = newId();
      const assistantMsg: Message = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setLoading(true);

      let accumulated = "";

      try {
        await queryStream(
          query,
          company || null,
          sessionId,
          (sources: string[], rationale: string) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, sources_used: sources, route_rationale: rationale }
                  : m
              )
            );
          },
          (token) => {
            accumulated += token;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: accumulated } : m
              )
            );
          },
          ({ citations, sources_used, latency_ms }) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      streaming: false,
                      citations: citations as Citation[],
                      sources_used,
                      latency_ms,
                    }
                  : m
              )
            );
          }
        );
        // A brand-new conversation needs to appear in the sidebar, and an
        // existing one's recency should bump to the top.
        refreshConversations();
      } catch {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: "Something went wrong. Is the API running?",
                  streaming: false,
                  error: true,
                }
              : m
          )
        );
      } finally {
        setLoading(false);
      }
    },
    [company, sessionId, refreshConversations]
  );

  const feedback = useCallback(
    async (query_log_id: number, rating: 1 | -1) => {
      await submitFeedback(query_log_id, rating);
    },
    []
  );

  const switchConversation = useCallback(async (id: string) => {
    setActiveSessionId(id);
    setSessionId(id);
    const turns = await fetchHistory(id);
    const restored: Message[] = turns.flatMap((t) => [
      { id: newId(), role: "user" as const, content: t.question },
      { id: newId(), role: "assistant" as const, content: t.answer },
    ]);
    setMessages(restored);
  }, []);

  const startNewConversation = useCallback(() => {
    const id = newId();
    setActiveSessionId(id);
    setSessionId(id);
    setMessages([]);
  }, []);

  const deleteConversation = useCallback(
    (id: string) => {
      // Update the sidebar instantly — don't wait on the network round trip
      // before removing it from view. The DELETE call still fires and
      // completes in the background.
      setConversations((prev) => prev.filter((c) => c.session_id !== id));
      if (id === sessionId) startNewConversation();
      deleteHistory(id);
    },
    [sessionId, startNewConversation]
  );

  return {
    messages,
    loading,
    company,
    setCompany,
    companies,
    send,
    feedback,
    conversations,
    activeSessionId: sessionId,
    switchConversation,
    startNewConversation,
    deleteConversation,
  };
}
