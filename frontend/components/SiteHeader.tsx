import { ReactNode } from "react";
import { VyomLogo } from "./VyomLogo";
import { ThemeToggle } from "./ThemeToggle";

/** Shared nav bar for the landing page and login page — same mark,
 * wordmark, and layout on both so moving from one to the other reads as
 * one continuous site, not two differently-designed pages. Only the
 * right-hand action differs (a "Sign in" CTA vs. nothing), passed in via
 * `rightSlot`. */
export function SiteHeader({ rightSlot }: { rightSlot?: ReactNode }) {
  return (
    <header className="flex items-center justify-between px-6 py-4 max-w-6xl mx-auto">
      <a href="/" className="flex items-center gap-3">
        <VyomLogo className="w-8 h-8" />
        <span className="font-bold text-gray-900 dark:text-gray-100 tracking-wide">VYOM</span>
      </a>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        {rightSlot}
      </div>
    </header>
  );
}
