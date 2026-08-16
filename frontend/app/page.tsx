"use client";
import { useEffect, useRef } from "react";
import { useChat } from "@/hooks/useChat";
import { MessageBubble } from "@/components/MessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { Sidebar } from "@/components/Sidebar";

export default function Home() {
  const {
    messages,
    loading,
    company,
    setCompany,
    send,
    conversations,
    activeSessionId,
    switchConversation,
    startNewConversation,
    deleteConversation,
  } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar
        conversations={conversations}
        activeSessionId={activeSessionId}
        onSelect={switchConversation}
        onNew={startNewConversation}
        onDelete={deleteConversation}
      />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <span className="text-white text-sm font-bold">V</span>
            </div>
            <div>
              <span className="font-semibold text-gray-900">Vyom</span>
              <span className="text-xs text-gray-400 ml-2">
                Indian fintech intelligence
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-400">
              BSE · SEBI · RBI
            </span>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-gray-400 hover:text-blue-600 transition-colors"
            >
              API docs
            </a>
          </div>
        </header>

        {/* Messages */}
        <main className="flex-1 overflow-y-auto px-4 py-6">
          <div className="max-w-3xl mx-auto">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center gap-4">
                <div className="w-16 h-16 bg-blue-50 rounded-2xl flex items-center justify-center">
                  <span className="text-3xl">📊</span>
                </div>
                <div>
                  <h1 className="text-xl font-semibold text-gray-900 mb-1">
                    Ask about Indian markets
                  </h1>
                  <p className="text-sm text-gray-500 max-w-md">
                    Every answer is grounded in real BSE filings, SEBI
                    regulatory circulars, and RBI macro data — with citations
                    back to the source.
                  </p>
                </div>
                <div className="grid grid-cols-3 gap-3 mt-2 text-xs text-gray-500">
                  <div className="bg-blue-50 text-blue-700 px-3 py-2 rounded-lg border border-blue-100">
                    BSE / NSE filings
                  </div>
                  <div className="bg-purple-50 text-purple-700 px-3 py-2 rounded-lg border border-purple-100">
                    SEBI circulars
                  </div>
                  <div className="bg-green-50 text-green-700 px-3 py-2 rounded-lg border border-green-100">
                    RBI macro data
                  </div>
                </div>
              </div>
            ) : (
              messages.map((m) => <MessageBubble key={m.id} message={m} />)
            )}
            <div ref={bottomRef} />
          </div>
        </main>

        {/* Input */}
        <ChatInput
          onSend={send}
          loading={loading}
          company={company}
          onCompanyChange={setCompany}
        />
      </div>
    </div>
  );
}
