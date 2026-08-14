"use client";
import { useState, KeyboardEvent } from "react";

interface Props {
  onSend: (query: string) => void;
  loading: boolean;
  company: string;
  onCompanyChange: (v: string) => void;
}

const EXAMPLES = [
  "What is HDFC Bank's NPA risk in unsecured lending?",
  "Latest SEBI BRSR disclosure requirements for listed companies",
  "What is RBI repo rate trend and its impact on bank margins?",
  "Given Reliance capex plans, what does RBI credit growth say?",
];

export function ChatInput({ onSend, loading, company, onCompanyChange }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    const q = value.trim();
    if (!q || loading) return;
    onSend(q);
    setValue("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-gray-100 bg-white px-4 pt-3 pb-4">
      {/* Example queries */}
      <div className="flex gap-2 mb-2 flex-wrap">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => onSend(ex)}
            disabled={loading}
            className="text-xs px-3 py-1 rounded-full bg-gray-50 text-gray-500 hover:bg-blue-50 hover:text-blue-700 transition-colors border border-gray-200 disabled:opacity-40"
          >
            {ex.length > 48 ? ex.slice(0, 48) + "…" : ex}
          </button>
        ))}
      </div>

      {/* Input row */}
      <div className="flex gap-2 items-end">
        {/* Company filter */}
        <input
          type="text"
          placeholder="Company"
          value={company}
          onChange={(e) => onCompanyChange(e.target.value)}
          className="w-28 px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400"
          maxLength={30}
        />

        {/* Query textarea */}
        <textarea
          rows={2}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask about BSE filings, SEBI circulars, or RBI macro data…"
          disabled={loading}
          className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50"
        />

        {/* Send button */}
        <button
          onClick={submit}
          disabled={loading || !value.trim()}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors self-end"
        >
          {loading ? "…" : "Ask"}
        </button>
      </div>

      <p className="text-xs text-gray-300 mt-2 text-center">
        Vyom searches BSE filings · SEBI circulars · RBI macro data
      </p>
    </div>
  );
}