/**
 * Typed client for the orchestrator (spec.md §8).
 * Base URL from NEXT_PUBLIC_ORCHESTRATOR_URL; all reads are no-store.
 * Every getter degrades to a safe empty value if the API is unreachable, so a
 * page renders an explicit empty state instead of crashing (rule R2).
 */

export const ORCHESTRATOR_URL =
  process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://localhost:8088";

export type Pricing = { model: "perf_fee" | "flat" | "free" | "tbd"; bps?: number | null };
export type AdvantageMetric = { name: string; unit: string; higher_is_better: boolean };

export type AgentStats = {
  n_runs: number;
  window_days: number | null;
  median_wall_seconds: number | null;
  win_rate: number | null;
  median_delta: number | null;
  worst_delta: number | null;
  max_drawdown_pct: number | null;
  updated_at: string | null;
};

export type AgentCard = {
  id: string;
  name: string;
  category: string;
  one_liner: string;
  tiers: number[];
  pricing: Pricing;
  advantage_metric: AdvantageMetric;
  sentry_gate: boolean;
  available: boolean;
  unavailable_reason: string | null;
  stats: AgentStats;
  has_runs: boolean;
};

export type Receipt = {
  id: string;
  agent_id: string;
  agent_run_id: string;
  baseline_run_id: string;
  metric: string;
  unit: string;
  agent_value: number;
  baseline_value: number;
  delta: number;
  favorable: boolean;
  merkle_leaf: string;
  batch_id: string | null;
  anchored_tx: string | null;
  created_at: string;
};

export type InputSpec = {
  type: "address" | "number" | "enum" | "string" | "bool";
  required: boolean;
  default: unknown;
  min?: number | null;
  max?: number | null;
  values?: unknown[] | null;
};

export type Curve = {
  metric: string;
  unit: string;
  window_days: number | null;
  points: { created_at: string; agent_value: number; baseline_value: number; delta: number }[];
};

export type AgentDetail = AgentCard & {
  inputs: Record<string, InputSpec>;
  data_deps: string[];
  baseline: string;
  kill_switch: { max_loss_pct: number } | null;
  recent_receipts: Receipt[];
  curve: Curve;
};

export type Category = { category: string; agent_count: number; live_runs: number };

export type ReceiptDetail = Receipt & {
  merkle_proof: string[] | null;
  anchor_root: string | null;
  verified_hint: string;
};

export type HireStatus = {
  hire_id: string;
  agent_id: string;
  tier: number;
  status: string;
  phase: string | null;
  error: string | null;
  result: { metric: string; unit: string; value: number; baseline_value: number; outputs: Record<string, unknown> } | null;
  receipt: Receipt | null;
  delta: number | null;
  favorable: boolean | null;
};

async function get<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${ORCHESTRATOR_URL}${path}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export const api = {
  base: ORCHESTRATOR_URL,
  agents: () => get<AgentCard[]>("/agents", []),
  agent: (id: string) => get<AgentDetail | null>(`/agents/${id}`, null),
  agentReceipts: (id: string, limit = 25) =>
    get<Receipt[]>(`/agents/${id}/receipts?limit=${limit}`, []),
  categories: () => get<Category[]>("/categories", []),
  activity: (limit = 20) => get<Receipt[]>(`/activity?limit=${limit}`, []),
  receipt: (id: string) => get<ReceiptDetail | null>(`/receipts/${id}`, null),
  report: () => get<Record<string, unknown> | null>("/report/advantage", null),
  reportPdfUrl: `${ORCHESTRATOR_URL}/report/advantage.pdf`,
  hire: (id: string) => get<HireStatus | null>(`/hires/${id}`, null),
  async createHire(body: { agent_id: string; tier: number; inputs: Record<string, unknown> }) {
    const res = await fetch(`${ORCHESTRATOR_URL}/hires`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const json = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, json } as {
      ok: boolean;
      status: number;
      json: { hire_id?: string; detail?: { errors?: Record<string, string> } };
    };
  },
  streamUrl: (hireId: string) => `${ORCHESTRATOR_URL}/hires/${hireId}/stream`,
};

// --- formatting helpers used across cards ---

export function fmtAdvantage(c: AgentCard): string {
  if (!c.has_runs) return "No runs yet";
  const s = c.stats;
  const dir = c.advantage_metric.higher_is_better ? "" : " (lower is better)";
  const delta =
    s.median_delta == null
      ? "—"
      : `${s.median_delta >= 0 ? "+" : ""}${round(s.median_delta)} ${c.advantage_metric.unit}`;
  const win = s.win_rate == null ? "" : ` · ${Math.round(s.win_rate * 100)}% win`;
  const wall = s.median_wall_seconds == null ? "" : ` · median ${round(s.median_wall_seconds)}s`;
  const dd =
    s.max_drawdown_pct == null ? "" : ` · max drawdown ${round(s.max_drawdown_pct)}%`;
  return `median ${delta} vs ${"baseline"}${dir} · n=${s.n_runs} · ${round(
    s.window_days ?? 0,
  )}d${win}${wall}${dd}`;
}

export function round(n: number, d = 2): number {
  const p = 10 ** d;
  return Math.round(n * p) / p;
}
