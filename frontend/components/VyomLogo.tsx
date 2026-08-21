/** Vyom's app-icon mark: a solid gradient square with an outlined "V".
 * Matches the "full lockup" concept chosen as the product's logo —
 * used as-is at any size (header, login, favicon-scale). */
export function VyomLogo({ className = "w-8 h-8" }: { className?: string }) {
  return (
    <div
      className={`${className} shrink-0 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-800 flex items-center justify-center shadow-sm`}
    >
      <svg viewBox="0 0 32 32" className="w-[58%] h-[58%]" fill="none">
        <path
          d="M7 8 L16 25 L25 8"
          stroke="white"
          strokeWidth="3.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
