"use client";
import { ConversationSummary } from "@/types";

interface Props {
  conversations: ConversationSummary[];
  activeSessionId: string;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
}

export function Sidebar({ conversations, activeSessionId, onSelect, onNew, onDelete }: Props) {
  return (
    <aside className="w-64 shrink-0 h-screen bg-gray-50 border-r border-gray-100 flex flex-col">
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-blue-50 hover:text-blue-700 hover:border-blue-200 transition-colors"
        >
          <span className="text-base leading-none">+</span>
          New conversation
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-4 text-xs text-gray-400 text-center">
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
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-600 hover:bg-gray-100"
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
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 w-6 h-6 flex items-center justify-center rounded-md text-gray-300 opacity-0 group-hover:opacity-100 hover:bg-red-50 hover:text-red-500 transition-all"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>
    </aside>
  );
}
