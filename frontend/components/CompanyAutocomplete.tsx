"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Company } from "@/types";

interface Props {
  companies: Company[];
  value: string;
  onChange: (v: string) => void;
}

const MAX_SUGGESTIONS = 8;

export function CompanyAutocomplete({ companies, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const matches = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return [];
    return companies
      .filter((c) => c.name.toLowerCase().includes(q))
      .slice(0, MAX_SUGGESTIONS);
  }, [companies, value]);

  // Close on outside click — the dropdown otherwise stays open until the
  // user picks something or clears the field.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const select = (name: string) => {
    onChange(name);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % matches.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + matches.length) % matches.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      select(matches[highlight].name);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <input
        type="text"
        placeholder="Company"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setHighlight(0);
          setOpen(true);
        }}
        onFocus={() => value.trim() && setOpen(true)}
        onKeyDown={onKeyDown}
        role="combobox"
        aria-expanded={open && matches.length > 0}
        aria-autocomplete="list"
        autoComplete="off"
        className="w-32 px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-100 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-400 dark:placeholder:text-gray-500"
        maxLength={30}
      />

      {open && matches.length > 0 && (
        <ul className="absolute bottom-full mb-1 left-0 w-56 max-h-56 overflow-y-auto bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg py-1 z-10">
          {matches.map((c, i) => (
            <li key={c.bse_code ?? c.name}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()} // keep focus, avoid blur-before-click
                onClick={() => select(c.name)}
                className={`w-full text-left px-3 py-1.5 text-sm truncate transition-colors ${
                  i === highlight
                    ? "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300"
                    : "text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700"
                }`}
              >
                {c.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
