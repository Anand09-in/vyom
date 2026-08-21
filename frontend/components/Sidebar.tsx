"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConversationSummary } from "@/types";

interface Props {
  conversations: ConversationSummary[];
  activeSessionId: string;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
}

const WIDTH_KEY = "vyom_sidebar_width";
const MIN_WIDTH = 200;
const MAX_WIDTH = 480;
const DEFAULT_WIDTH = 256; // matches the old fixed w-64

export function Sidebar({ conversations, activeSessionId, onSelect, onNew, onDelete }: Props) {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [resizing, setResizing] = useState(false);
  const asideRef = useRef<HTMLElement>(null);

  // Width is inherently client-only (localStorage) — same reasoning as
  // useChat's session id: a lazy useState initializer would risk a
  // server/client hydration mismatch, so read it in an effect instead.
  useEffect(() => {
    const stored = Number(localStorage.getItem(WIDTH_KEY));
    if (stored >= MIN_WIDTH && stored <= MAX_WIDTH) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setWidth(stored);
    }
  }, []);

  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    setResizing(true);
  }, []);

  useEffect(() => {
    if (!resizing) return;

    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (e: PointerEvent) => {
      const left = asideRef.current?.getBoundingClientRect().left ?? 0;
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX - left));
      setWidth(next);
    };
    const onUp = () => {
      setResizing(false);
      setWidth((w) => {
        localStorage.setItem(WIDTH_KEY, String(w));
        return w;
      });
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [resizing]);

  return (
    <aside
      ref={asideRef}
      style={{ width }}
      className="relative shrink-0 h-screen bg-gray-50 dark:bg-gray-900 border-r border-gray-100 dark:border-gray-800 flex flex-col"
    >
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-blue-50 dark:hover:bg-blue-950 hover:text-blue-700 dark:hover:text-blue-300 hover:border-blue-200 dark:hover:border-blue-800 transition-colors"
        >
          <span className="text-base leading-none">+</span>
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-gray-400 dark:text-gray-500 text-center">
            No conversations yet
          </p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.session_id} className="group relative">
                <button
                  onClick={() => onSelect(c.session_id)}
                  title={c.title}
                  className={`w-full text-left px-3 py-2 pr-8 rounded-lg text-sm truncate transition-colors ${
                    c.session_id === activeSessionId
                      ? "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                      : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                  }`}
                >
                  {c.title || "Untitled conversation"}
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.session_id);
                  }}
                  aria-label="Delete conversation"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-md text-gray-300 dark:text-gray-600 opacity-0 group-hover:opacity-100 hover:bg-red-50 dark:hover:bg-red-950 hover:text-red-500 dark:hover:text-red-400 transition-all"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>

      {/* Drag handle — resizes the sidebar, width persists across reloads */}
      <div
        onPointerDown={startResize}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        className={`absolute top-0 right-0 h-full w-1.5 -mr-0.5 cursor-col-resize group ${
          resizing ? "select-none" : ""
        }`}
      >
        <div
          className={`h-full w-px mx-auto transition-colors ${
            resizing ? "bg-blue-400 w-0.5" : "bg-transparent group-hover:bg-blue-300"
          }`}
        />
      </div>
    </aside>
  );
}
