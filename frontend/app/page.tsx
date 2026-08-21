"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useChat } from "@/hooks/useChat";
import { MessageBubble } from "@/components/MessageBubble";
import { ChatInput } from "@/components/ChatInput";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle } from "@/components/ThemeToggle";
import { DoodleBackground } from "@/components/DoodleBackground";
import { VyomLogo } from "@/components/VyomLogo";
import { isSignedIn, signOut } from "@/lib/auth";

export default function Home() {
  const router = useRouter();
  const [authChecked, setAuthChecked] = useState(false);
  const {
    messages,
    loading,
    company,
    setCompany,
    companies,
    send,
    conversations,
    activeSessionId,
    switchConversation,
    startNewConversation,
    deleteConversation,
  } = useChat();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    isSignedIn().then((ok) => {
      if (!ok) router.push("/login");
      else setAuthChecked(true);
    });
  }, [router]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSignOut = async () => {
    await signOut();
    router.push("/login");
  };

  if (!authChecked) return null;

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      <Sidebar
        conversations={conversations}
        activeSessionId={activeSessionId}
        onSelect={switchConversation}
        onNew={startNewConversation}
        onDelete={deleteConversation}
      />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-6 py-3 bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-3">
            <VyomLogo className="w-8 h-8" />
            <div>
              <span className="font-bold text-gray-900 dark:text-gray-100 tracking-wide">VYOM</span>
              <span className="text-xs text-gray-400 dark:text-gray-500 ml-2 tracking-wide">
                Indian fintech intelligence
              </span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-400 dark:text-gray-500">
              BSE · SEBI · RBI
            </span>
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              API docs
            </a>
            <button
              onClick={handleSignOut}
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              Sign out
            </button>
            <ThemeToggle />
          </div>
        </header>

        {/* Messages */}
        <main className="relative flex-1 overflow-y-auto px-4 py-6">
          <DoodleBackground />
          <div className="relative z-10 max-w-3xl mx-auto">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center gap-4">
                <VyomLogo className="w-16 h-16" />
                <span className="sr-only">Vyom</span>
                <div>
                  <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100 mb-1">
                    One question. Four sources. Every claim cited.
                  </h1>
                  <p className="text-sm text-gray-500 dark:text-gray-400 max-w-md">
                    Vyom fuses real BSE filings, SEBI circulars, RBI macro
                    data, and live web search into a single grounded
                    answer — with a citation for every fact.
                  </p>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-2 text-xs text-gray-500">
                  <div className="bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 px-3 py-2 rounded-lg border border-blue-100 dark:border-blue-900">
                    BSE / NSE filings
                  </div>
                  <div className="bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 px-3 py-2 rounded-lg border border-purple-100 dark:border-purple-900">
                    SEBI circulars
                  </div>
                  <div className="bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300 px-3 py-2 rounded-lg border border-green-100 dark:border-green-900">
                    RBI macro data
                  </div>
                  <div className="bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 px-3 py-2 rounded-lg border border-amber-100 dark:border-amber-900">
                    Live web search
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
          companies={companies}
        />
      </div>
    </div>
  );
}
