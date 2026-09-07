import { api, round } from "@/lib/api";
import { EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

type Task = {
  agent_id: string;
  name: string;
  category: string | null;
  baseline: string | null;
  metric: string;
  unit: string;
  lower_is_better: boolean;
  n: number;
  window_days: number | null;
  median_wall_seconds: number | null;
  avg_agent_value: number | null;
  avg_baseline_value: number | null;
  avg_delta: number | null;
  best_delta: number | null;
  worst_delta: number | null;
  advantage: string;
};

export default async function ReportPage() {
  const rep = (await api.report()) as
    | (Record<string, unknown> & { tasks: Task[]; methodology: string; meets_min_3_bothways: boolean; has_trading_or_security: boolean })
    | null;

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
      <h1 className="text-2xl font-semibold tracking-tight">Agent Advantage Report</h1>
      <p className="mt-1 text-xs text-neutral-400">Generated live from the receipts table.</p>

      <div className="mt-3 flex gap-2 text-xs">
        <Badge ok={rep.meets_min_3_bothways}>≥3 both-ways tasks</Badge>
        <Badge ok={rep.has_trading_or_security}>≥1 trading/security</Badge>
      </div>

      {rep.tasks.length === 0 ? (
        <div className="mt-4">
          <EmptyState>No receipts yet.</EmptyState>
        </div>
      ) : (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-neutral-400">
                <th className="border-b border-neutral-200 p-2">agent</th>
                <th className="border-b border-neutral-200 p-2">baseline</th>
                <th className="border-b border-neutral-200 p-2">metric</th>
                <th className="border-b border-neutral-200 p-2">n</th>
                <th className="border-b border-neutral-200 p-2">window</th>
                <th className="border-b border-neutral-200 p-2">avg delta</th>
                <th className="border-b border-neutral-200 p-2">best / worst</th>
                <th className="border-b border-neutral-200 p-2">verdict</th>
              </tr>
            </thead>
            <tbody>
              {rep.tasks.map((t) => (
                <tr key={t.agent_id}>
                  <td className="border-b border-neutral-100 p-2 font-medium">{t.name}</td>
                  <td className="border-b border-neutral-100 p-2 text-neutral-500">{t.baseline}</td>
                  <td className="border-b border-neutral-100 p-2 text-neutral-500">
                    {t.metric} {t.lower_is_better ? "↓" : "↑"}
                  </td>
                  <td className="border-b border-neutral-100 p-2">{t.n}</td>
                  <td className="border-b border-neutral-100 p-2">
                    {t.window_days == null ? "—" : `${round(t.window_days)}d`}
                  </td>
                  <td className="border-b border-neutral-100 p-2">
                    {t.avg_delta == null ? "—" : `${t.avg_delta >= 0 ? "+" : ""}${round(t.avg_delta)} ${t.unit}`}
                  </td>
                  <td className="border-b border-neutral-100 p-2 text-xs text-neutral-500">
                    {round(t.best_delta ?? 0)} / {round(t.worst_delta ?? 0)}
                  </td>
                  <td className="border-b border-neutral-100 p-2 text-xs">{t.advantage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-6 max-w-2xl text-xs text-neutral-500">{rep.methodology}</p>
    </div>
  );
}

function Badge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={`rounded px-2 py-0.5 ${ok ? "bg-emerald-50 text-emerald-700" : "bg-neutral-100 text-neutral-400"}`}
    >
      {ok ? "✓" : "○"} {children}
    </span>
  );
}
