"use client";
import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { signIn, signUp, confirmSignUp } from "@/lib/auth";
import { DoodleBackground } from "@/components/DoodleBackground";
import { SiteHeader } from "@/components/SiteHeader";

type Mode = "signin" | "signup" | "confirm";

const STATS = [
  { value: "4", label: "sources fused" },
  { value: "97", label: "Nifty 100 companies" },
  { value: "0.84", label: "RAGAS faithfulness" },
  { value: "100%", label: "Terraform" },
];

const FEATURES = [
  {
    dot: "bg-blue-500",
    title: "BSE / NSE filings",
    body: "Corporate announcements and disclosures, ingested and chunked for retrieval — not just headline search.",
  },
  {
    dot: "bg-purple-500",
    title: "SEBI circulars",
    body: "Regulatory circulars and disclosure requirements, cited with the exact source, every time.",
  },
  {
    dot: "bg-green-500",
    title: "RBI macro data",
    body: "Repo rate, credit growth, and macro series, connecting a company fact to the economy around it.",
  },
  {
    dot: "bg-amber-500",
    title: "Live web search",
    body: "Routed in only when a question is time-sensitive — \"right now,\" \"today,\" \"trading at.\"",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSignIn = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await signIn({ username: email, password });
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await signUp({ username: email, password, options: { userAttributes: { email } } });
      setMode("confirm");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign up failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await confirmSignUp({ username: email, confirmationCode: code });
      setMode("signin");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Confirmation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen bg-gray-50 dark:bg-gray-950">
      <DoodleBackground />
      <div className="relative z-10">
        <SiteHeader />

        <div className="max-w-5xl mx-auto px-6 pb-16 pt-4 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-12 items-center">
          {/* Product pitch */}
          <div className="max-w-xl">
            <h1 className="text-2xl sm:text-3xl font-semibold text-gray-900 dark:text-gray-100 text-balance mb-3">
              One question. Four sources. Every claim cited.
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
              Vyom is an agentic RAG system over Indian fintech data — it
              fuses real BSE filings, SEBI circulars, RBI macro data, and
              live web search into a single grounded answer, with a citation
              traceable back to its source for every fact.
            </p>

            <div className="grid grid-cols-4 gap-3 mb-8">
              {STATS.map((s) => (
                <div key={s.label}>
                  <div className="text-lg font-bold text-gray-900 dark:text-gray-100">
                    {s.value}
                  </div>
                  <div className="text-[11px] text-gray-400 dark:text-gray-500 leading-tight">
                    {s.label}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-4 mb-6">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex items-start gap-3">
                  <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${f.dot}`} />
                  <div>
                    <div className="text-sm font-medium text-gray-800 dark:text-gray-200">
                      {f.title}
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                      {f.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <a
              href="https://github.com/Anand09-in/vyom"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
            >
              github.com/Anand09-in/vyom
            </a>
          </div>

          {/* Auth card */}
          <div className="w-full max-w-sm mx-auto lg:mx-0">
            <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl shadow-sm dark:shadow-none p-6">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
                {mode === "confirm"
                  ? "Verify your email"
                  : mode === "signin"
                    ? "Sign in to Vyom"
                    : "Create your account"}
              </h2>

              {mode === "confirm" ? (
                <form onSubmit={handleConfirm} className="flex flex-col gap-4">
                  <p className="text-xs text-gray-500 dark:text-gray-400 -mt-2">
                    Enter the code sent to{" "}
                    <span className="text-gray-700 dark:text-gray-300">{email}</span>.
                  </p>
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="Verification code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                    className="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                  {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
                  <button
                    type="submit"
                    disabled={loading}
                    className="px-4 py-2 bg-blue-600 text-white text-sm rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    {loading ? "Verifying…" : "Verify"}
                  </button>
                </form>
              ) : (
                <form
                  onSubmit={mode === "signin" ? handleSignIn : handleSignUp}
                  className="flex flex-col gap-4"
                >
                  <input
                    type="email"
                    placeholder="Email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                  <input
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={10}
                    className="px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                  {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
                  <button
                    type="submit"
                    disabled={loading}
                    className="px-4 py-2 bg-blue-600 text-white text-sm rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    {loading ? "…" : mode === "signin" ? "Sign in" : "Create account"}
                  </button>
                </form>
              )}

              {mode !== "confirm" && (
                <button
                  onClick={() => {
                    setMode(mode === "signin" ? "signup" : "signin");
                    setError("");
                  }}
                  className="w-full text-center text-xs text-gray-400 dark:text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors mt-4"
                >
                  {mode === "signin" ? "Need an account? Sign up" : "Already have an account? Sign in"}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
