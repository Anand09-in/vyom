"use client";
import { useState, useCallback } from "react";
import { Message, Citation } from "@/types";
import { queryStream, submitFeedback } from "@/lib/api";

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [company, setCompany] = useState("");

  const send = useCallback(
    async (query: string) => {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content: query,
      };
      const assistantId = crypto.randomUUID();
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
          (sources, rationale) => {
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
    [company]
  );

  const feedback = useCallback(
    async (query_log_id: number, rating: 1 | -1) => {
      await submitFeedback(query_log_id, rating);
    },
    []
  );

  return { messages, loading, company, setCompany, send, feedback };
}