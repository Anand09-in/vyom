interface Props {
  source: string;
}

const SOURCE_STYLES: Record<string, { label: string; className: string }> = {
  bse: {
    label: "BSE",
    className: "bg-blue-50 text-blue-700 border-blue-200",
  },
  sebi: {
    label: "SEBI",
    className: "bg-purple-50 text-purple-700 border-purple-200",
  },
  rbi: {
    label: "RBI",
    className: "bg-green-50 text-green-700 border-green-200",
  },
  live: {
    label: "LIVE",
    className: "bg-amber-50 text-amber-700 border-amber-200",
  },
};

export function SourceBadge({ source }: Props) {
  const style = SOURCE_STYLES[source.toLowerCase()] ?? {
    label: source.toUpperCase(),
    className: "bg-gray-50 text-gray-700 border-gray-200",
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style.className}`}
    >
      {style.label}
    </span>
  );
}