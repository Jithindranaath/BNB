import Link from "next/link";
import { notFound } from "next/navigation";
import { api, round } from "@/lib/api";
import { CategoryLabel, PriceTag, TierBadges, EmptyState } from "@/components/ui";
import { CurveChart } from "@/components/Curve";
import { HirePanel } from "@/components/HirePanel";

export const dynamic = "force-dynamic";

export default async function AgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const agent = await api.agent(id);
  if (!agent) notFound();

  const prefill: Record<string, string> = {};
  const target = typeof sp.target === "string" ? sp.target : undefined;
  if (target && agent.inputs.target) prefill.target = target;

  const s = agent.stats;
  return (
    <div>
      <Link href={`/category/${agent.category}`} className="text-xs text-neutral-400 hover:text-neutral-700">
        ← <CategoryLabel slug={agent.category} />
      </Link>
      <div className="mt-2 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{agent.name}</h1>
          <p className="mt-1 text-sm text-neutral-600">{agent.one_liner}</p>
        </div>
        <div className="text-right">
          <TierBadges tiers={agent.tiers} />
          <div className="mt-1">
            <PriceTag pricing={agent.pricing} />
          </div>
        </div>
      </div>

      <section className="mt-5 grid gap-3 sm:grid-cols-4">
        {[
          ["advantage metric", `${agent.advantage_metric.name} (${agent.advantage_metric.unit})`],
          ["baseline", agent.baseline],
          ["runs", s.n_runs ? `n=${s.n_runs} · ${round(s.window_days ?? 0)}d` : "No runs yet"],
          [
            agent.category === "grid" ? "max drawdown" : "median advantage",
            agent.category === "grid"
              ? s.max_drawdown_pct == null
                ? "—"
                : `${round(s.max_drawdown_pct)}%`
              : s.median_delta == null
                ? "—"
                : `${s.median_delta >= 0 ? "+" : ""}${round(s.median_delta)} ${agent.advantage_metric.unit}`,
          ],
        ].map(([k, v]) => (
          <div key={k} className="rounded-lg border border-neutral-200 p-3">
            <div className="text-[11px] uppercase tracking-wide text-neutral-400">{k}</div>
            <div className="mt-1 text-sm">{v}</div>
          </div>
        ))}
      </section>

      <section className="mt-8 grid gap-6 lg:grid-cols-[1fr_360px]">
        <div>
          <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
            Agent vs baseline ({agent.curve.metric})
          </h2>
          <div className="mt-2">
            <CurveChart curve={agent.curve} />
          </div>

          <h2 className="mt-6 text-xs font-medium uppercase tracking-wide text-neutral-500">
            Receipt feed
          </h2>
          <div className="mt-2">
            {agent.recent_receipts.length === 0 ? (
              <EmptyState>No receipts yet. Hire the agent to produce one.</EmptyState>
            ) : (
              <ul className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 text-sm">
                {agent.recent_receipts.map((r) => (
                  <li key={r.id} className="flex items-center justify-between px-4 py-2">
                    <span className="text-neutral-500">
                      {new Date(r.created_at).toLocaleString()}
                    </span>
                    <span className={r.favorable ? "text-emerald-600" : "text-neutral-500"}>
                      {r.delta >= 0 ? "+" : ""}
                      {round(r.delta)} {r.unit}
                    </span>
                    <Link href={`/receipt/${r.id}`} className="text-xs text-neutral-400 hover:text-neutral-700">
                      verify →
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div>
          <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">Hire</h2>
          {agent.available ? (
            <>
              <p className="mt-1 mb-2 text-xs text-neutral-500">
                {agent.tiers.includes(0)
                  ? "No wallet, no funds. You get a real result."
                  : "Tier 1 is paper on live prices — no funds at risk."}
              </p>
              <HirePanel agent={agent} prefill={prefill} />
              {agent.kill_switch && (
                <p className="mt-2 text-xs text-neutral-400">
                  kill switch: halts at −{agent.kill_switch.max_loss_pct}% of capital.
                </p>
              )}
            </>
          ) : (
            <div className="mt-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <p className="font-medium">Not yet available</p>
              <p className="mt-1">{agent.unavailable_reason ?? "This agent is not deployed yet."}</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
