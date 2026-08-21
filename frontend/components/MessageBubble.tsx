"use client";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Message } from "@/types";
import { SourceBadge } from "./SourceBadge";
import { submitFeedback } from "@/lib/api";

interface Props {
  message: Message;
}

const MARKDOWN_COMPONENTS = {
  p: (props: React.ComponentProps<"p">) => (
    <p className="mb-2 last:mb-0" {...props} />
  ),
  ol: (props: React.ComponentProps<"ol">) => (
    <ol className="list-decimal list-outside pl-5 mb-2 space-y-2" {...props} />
  ),
  ul: (props: React.ComponentProps<"ul">) => (
    <ul className="list-disc list-outside pl-5 mb-2 space-y-1" {...props} />
  ),
  li: (props: React.ComponentProps<"li">) => <li className="pl-1" {...props} />,
  strong: (props: React.ComponentProps<"strong">) => (
    <strong className="font-semibold text-gray-900 dark:text-gray-100" {...props} />
  ),
  a: (props: React.ComponentProps<"a">) => (
    <a
      {...props}
      target="_blank"
      rel="noreferrer"
      className="text-blue-600 dark:text-blue-400 underline underline-offset-2 hover:text-blue-700 dark:hover:text-blue-300"
    />
  ),
  // GFM tables — needs remarkGfm below, plain markdown doesn't parse `| a | b |`
  // as a table at all, it'd otherwise render as unstyled pipe-delimited text.
  table: (props: React.ComponentProps<"table">) => (
    <div className="overflow-x-auto mb-2 rounded-lg border border-gray-200 dark:border-gray-700">
      <table className="w-full text-xs" {...props} />
    </div>
  ),
  thead: (props: React.ComponentProps<"thead">) => (
    <thead className="bg-gray-50 dark:bg-gray-800" {...props} />
  ),
  th: (props: React.ComponentProps<"th">) => (
    <th className="text-left font-semibold text-gray-700 dark:text-gray-200 px-3 py-1.5 border-b border-gray-200 dark:border-gray-700" {...props} />
  ),
  td: (props: React.ComponentProps<"td">) => (
    <td className="px-3 py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-0" {...props} />
  ),
  code: ({ className, ...props }: React.ComponentProps<"code">) => {
    // react-markdown gives block code a `language-xxx` className (from the
    // ```lang fence) and inline code no className at all — that's the only
    // reliable way to tell them apart here.
    const isBlock = Boolean(className);
    return isBlock ? (
      <code className={`${className ?? ""} block`} {...props} />
    ) : (
      <code
        className="px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 text-[0.85em] font-mono"
        {...props}
      />
    );
  },
  pre: (props: React.ComponentProps<"pre">) => (
    <pre
      className="mb-2 p-3 rounded-lg bg-gray-900 dark:bg-black text-gray-100 text-xs overflow-x-auto"
      {...props}
    />
  ),
};

/** Renders the model's markdown (headings, numbered/bulleted lists, bold,
 * tables, code, links) as real HTML structure instead of preserving raw
 * whitespace — the model's output isn't reliably indented/spaced enough
 * for a plain-text + whitespace-pre-wrap approach to look right. */
function FormattedAnswer({ text }: { text: string }) {
  return (
    <div className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function MessageBubble({ message }: Props) {
  const [feedback, setFeedback] = useState<1 | -1 | null>(null);

  const handleFeedback = async (rating: 1 | -1) => {
    if (!message.query_log_id || feedback !== null) return;
    setFeedback(rating);
    await submitFeedback(message.query_log_id, rating);
  };

  if (message.role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 max-w-lg text-sm leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-2xl w-full">
        {/* Route rationale pill */}
        {message.route_rationale && (
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-gray-400 dark:text-gray-500">{message.route_rationale}</span>
            <div className="flex gap-1">
              {(message.sources_used ?? []).map((s) => (
                <SourceBadge key={s} source={s} />
              ))}
            </div>
          </div>
        )}

        {/* Answer bubble */}
        <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm dark:shadow-none">
          {/* Streaming indicator */}
          {message.streaming && !message.content && (
            <div className="flex gap-1 py-2">
              <span className="w-2 h-2 bg-gray-300 dark:bg-gray-600 rounded-full animate-bounce [animation-delay:0ms]" />
              <span className="w-2 h-2 bg-gray-300 dark:bg-gray-600 rounded-full animate-bounce [animation-delay:150ms]" />
              <span className="w-2 h-2 bg-gray-300 dark:bg-gray-600 rounded-full animate-bounce [animation-delay:300ms]" />
            </div>
          )}

          {/* Answer text */}
          {message.content && <FormattedAnswer text={message.content} />}

          {/* Error state */}
          {message.error && (
            <p className="text-sm text-red-500 dark:text-red-400">{message.content}</p>
          )}

          {/* Citations */}
          {(message.citations ?? []).length > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
              <p className="text-xs font-medium text-gray-400 dark:text-gray-500 mb-1.5">Sources</p>
              <div className="flex flex-wrap gap-1.5">
                {message.citations!.map((c, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-700"
                  >
                    <SourceBadge source={c.type} />
                    <span className="ml-1">
                      {c.type === "bse" && c.company && `${c.company}${c.section ? ` · ${c.section}` : ""}`}
                      {c.type === "sebi" && c.circular_number && c.circular_number.slice(0, 30)}
                      {c.type === "rbi" && c.series_id && `${c.series_id} · ${c.period ?? ""}`}
                      {c.type === "live" && c.title && c.url && (
                        <a
                          href={c.url}
                          target="_blank"
                          rel="noreferrer"
                          className="hover:underline hover:text-blue-600 dark:hover:text-blue-400"
                        >
                          {c.title.slice(0, 40)}
                          {c.published_at ? ` · ${c.published_at}` : ""}
                        </a>
                      )}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Footer: latency + feedback */}
          {!message.streaming && (
            <div className="flex items-center gap-3 mt-3 pt-2 border-t border-gray-50 dark:border-gray-800">
              {message.latency_ms !== undefined && message.latency_ms !== null && (
                <span className="text-xs text-gray-300 dark:text-gray-600">
                  {(message.latency_ms / 1000).toFixed(1)}s
                </span>
              )}
              {message.query_log_id && (
                <div className="ml-auto flex gap-1">
                  <button
                    onClick={() => handleFeedback(1)}
                    className={`text-xs px-2 py-0.5 rounded transition-colors ${
                      feedback === 1
                        ? "bg-green-100 dark:bg-green-950 text-green-700 dark:text-green-400"
                        : "text-gray-400 dark:text-gray-500 hover:text-green-600 dark:hover:text-green-400"
                    }`}
                  >
                    Helpful
                  </button>
                  <button
                    onClick={() => handleFeedback(-1)}
                    className={`text-xs px-2 py-0.5 rounded transition-colors ${
                      feedback === -1
                        ? "bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400"
                        : "text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400"
                    }`}
                  >
                    Not helpful
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
