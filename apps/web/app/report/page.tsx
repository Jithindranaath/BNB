import Link from "next/link";
import { api, round } from "@/lib/api";
import { EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

type Output = {
  receipt_id: string;
  url: string;
  delta: number;
  favorable: boolean;
  created_at: string;
  anchored: boolean;
};

type Task = {
  agent_id: string;
  name: string;
  category: string | null;
  baseline: string | null;
  metric: string;
  unit: string;
  higher_is_better: boolean;
  kind: "BACKTEST" | "LIVE";
  replay_method: string | null;
  n: number;
  evaluation_window_days: number | null;
  receipts_span_days: number;
  distinct_snapshots: number;
  time: {
    agent_median_seconds: number | null;
    agent_p90_seconds: number | null;
    baseline_median_seconds: number | null;
    baseline_is_human: boolean;
    speedup_x: number | null;
  };
  cost: {
    on_chain: boolean;
    agent_gas_bnb: number;
    protocol_fees_usd: number;
    agent_fee_usd: number;
    note: string | null;
  };
  output_quality: {
    avg_delta: number;
    median_delta: number;
    best_delta: number;
    worst_delta: number;
    wins: number;
    losses: number;
    win_rate: number | null;
    verdict: string;
  };
  outputs: Output[];
};

type Planned = {
  agent_id: string;
  task: string;
  baseline: string;
  headline_metric: string;
  status: string;
  reason: string | null;
};

type Report = {
  tasks: Task[];
  planned: Planned[];
  methodology: string;
  meets_min_3_bothways: boolean;
  has_trading_or_security: boolean;
  backtested_tasks: string[];
  caveats: string[];
  generated_at: string;
};

export default async function ReportPage() {
  const rep = (await api.report()) as Report | null;

  if (!rep) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Agent Advantage Report</h1>
        <div className="mt-4">
          <EmptyState>Orchestrator unreachable ({api.base}).</EmptyState>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Agent Advantage Report</h1>
        <a
          href={api.reportPdfUrl}
          className="rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-50"
          target="_blank"
          rel="noreferrer"
        >
          Download PDF
        </a>
      </div>
      <p className="mt-1 text-xs text-neutral-400">
        Generated live from the receipts table · {new Date(rep.generated_at).toLocaleString()}
      </p>

      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <Badge ok={rep.meets_min_3_bothways}>≥3 both-ways tasks</Badge>
        <Badge ok={rep.has_trading_or_security}>≥1 trading/security</Badge>
      </div>

      {rep.caveats.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-amber-700">
          {rep.caveats.map((c) => (
            <li key={c}>! {c}</li>
          ))}
        </ul>
      )}

      {rep.tasks.length === 0 ? (
        <div className="mt-4">
          <EmptyState>No both-ways receipts yet.</EmptyState>
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          {rep.tasks.map((t) => (
            <TaskCard key={t.agent_id} t={t} />
          ))}
        </div>
      )}

      <h2 className="mt-8 text-sm font-medium uppercase tracking-wide text-neutral-500">
        Planned tasks — spec §10
      </h2>
      <div className="mt-2 space-y-2">
        {rep.planned.map((p) => (
          <div key={p.agent_id} className="rounded-lg border border-neutral-200 p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{p.agent_id}</span>
              <span
                className={
                  p.status === "has receipts"
                    ? "text-xs text-emerald-600"
                    : "text-xs text-neutral-400"
                }
              >
                {p.status}
              </span>
            </div>
            <p className="text-xs text-neutral-500">{p.task}</p>
            <p className="text-xs text-neutral-400">
              baseline {p.baseline} · {p.headline_metric}
            </p>
            {p.reason && <p className="mt-1 text-xs text-amber-700">{p.reason}</p>}
          </div>
        ))}
      </div>

      <p className="mt-6 max-w-2xl text-xs text-neutral-500">{rep.methodology}</p>
    </div>
  );
}

function TaskCard({ t }: { t: Task }) {
  const q = t.output_quality;
  const arrow = t.higher_is_better ? "↑" : "↓";
  return (
    <div className="rounded-xl border border-neutral-200 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">{t.name}</h3>
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] ${
            t.kind === "BACKTEST"
              ? "bg-amber-50 text-amber-700"
              : "bg-emerald-50 text-emerald-700"
          }`}
        >
          {t.kind}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-neutral-400">
        {t.category} · baseline {t.baseline} · metric {t.metric} ({t.unit}) {arrow}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
        <Field label="n">{t.n} runs · {t.distinct_snapshots} snapshots</Field>
        <Field label="evaluation window">
          {t.evaluation_window_days == null ? "—" : `${round(t.evaluation_window_days)}d`}
        </Field>
        <Field label="time (agent / baseline)">
          {fmtSec(t.time.agent_median_seconds)} / {fmtSec(t.time.baseline_median_seconds)}
          {t.time.baseline_is_human ? " (human)" : ""}
          {t.time.speedup_x ? ` · ${t.time.speedup_x}×` : ""}
        </Field>
        <Field label="cost">
          {t.cost.note
            ? "simulated · $0"
            : `${t.cost.agent_gas_bnb} BNB gas · $${t.cost.protocol_fees_usd} fees`}
        </Field>
        <Field label="avg Δ">
          {q.avg_delta >= 0 ? "+" : ""}
          {round(q.avg_delta)} {t.unit}
        </Field>
        <Field label="best / worst Δ">
          {round(q.best_delta)} / {round(q.worst_delta)}
        </Field>
        <Field label="win rate">
          {q.win_rate == null ? "—" : `${Math.round(q.win_rate * 100)}%`} ({q.wins}W/{q.losses}L)
        </Field>
        <Field label="verdict">{q.verdict}</Field>
      </dl>

      {t.replay_method && (
        <p className="mt-3 border-l-2 border-amber-200 pl-2 text-xs text-neutral-500">
          <span className="font-medium text-amber-700">BACKTEST replay:</span> {t.replay_method}
        </p>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-neutral-500">
          {t.outputs.length} receipt{t.outputs.length === 1 ? "" : "s"} attached
        </summary>
        <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
          {t.outputs.map((o) => (
            <li key={o.receipt_id}>
              <Link href={o.url} className="text-neutral-500 hover:text-neutral-900">
                {o.favorable ? "+" : "−"} {o.receipt_id.slice(0, 8)} · Δ {round(o.delta)} ·{" "}
                {new Date(o.created_at).toLocaleDateString()}
                {o.anchored ? " · anchored" : ""}
              </Link>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-neutral-400">{label}</dt>
      <dd className="mt-0.5 font-medium text-neutral-800">{children}</dd>
    </div>
  );
}

function fmtSec(s: number | null): string {
  return s == null ? "—" : `${s}s`;
}

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`rounded px-2 py-0.5 ${
        ok ? "bg-emerald-50 text-emerald-700" : "bg-neutral-100 text-neutral-400"
      }`}
    >
      {ok ? "✓" : "○"} {children}
    </span>
  );
}
