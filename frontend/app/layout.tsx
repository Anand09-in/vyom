import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Vyom — Indian fintech intelligence",
  description:
    "Multi-source agentic RAG over BSE filings, SEBI circulars, and RBI macro data",
};

// Sets the .dark class before hydration so there's no flash of the wrong
// theme on load. Explicit localStorage choice (ThemeToggle.tsx) wins;
// system preference is the fallback for a first-ever visit — see
// globals.css's @custom-variant dark for how Tailwind picks this up.
const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem('vyom_theme');var d=s?s==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;if(d)document.documentElement.classList.add('dark');}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className={inter.className}>{children}</body>
    </html>
  );
}