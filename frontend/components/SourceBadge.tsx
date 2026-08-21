interface Props {
  source: string;
}

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  bse: {
    label: "BSE",
    className: "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-900",
  },
  sebi: {
    label: "SEBI",
    className: "bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-900",
  },
  rbi: {
    label: "RBI",
    className: "bg-green-50 dark:bg-green-950 text-green-700 dark:text-green-300 border-green-200 dark:border-green-900",
  },
  live: {
    label: "LIVE",
    className: "bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900",
  },
};

export function SourceBadge({ source }: Props) {
  const style = SOURCE_STYLES[source.toLowerCase()] ?? {
    label: source.toUpperCase(),
    className: "bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700",
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style.className}`}
    >
      {style.label}
    </span>
  );
}