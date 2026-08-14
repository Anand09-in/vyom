export interface Citation {
  type: "bse" | "sebi" | "rbi";
  id?: number;
  company?: string;
  section?: string;
  circular_number?: string;
  title?: string;
  series_id?: string;
  period?: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  sources_used?: string[];
  route_rationale?: string;
  latency_ms?: number;
  query_log_id?: number;
  streaming?: boolean;
  error?: boolean;
}

export interface QueryResponse {
  answer: string;
  citations: Citation[];
  sources_used: string[];
  route_rationale: string;
  latency_ms: number;
  query_log_id: number;
}