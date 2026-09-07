import Link from "next/link";
import { brand } from "@/config/brand";
import { api, round } from "@/lib/api";
import { CategoryLabel, EmptyState } from "@/components/ui";

export const dynamic = "force-dynamic";

// Prefilled example so a judge reaches a real sentry result with zero input.
const SENTRY_EXAMPLE = "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82"; // CAKE

const ORDER = ["security", "yield", "grid", "rebalancing", "health_factor"];

export default async function Home() {
  const [cards, cats, feed] = await Promise.all([
    api.agents(),
    api.categories(),
    api.activity(12),
  ]);
  const catById = new Map(cats.map((c) => [c.category, c]));
  const agentFor = (slug: string) => cards.find((c) => c.category === slug);

  return (
    <div>
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">{brand.tagline}</h1>
        <p className="mt-2 max-w-2xl text-sm text-neutral-600">
          Every agent run records a receipt: <code className="text-xs">{"{ agent_run, baseline_run, advantage_delta }"}</code>.
          You can verify the hash instead of trusting the dashboard.
        </p>
        <Link
          href={`/agent/bsc-sentry?target=${SENTRY_EXAMPLE}`}
          className="mt-4 inline-block rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"
        >
          {brand.primaryCta} →
        </Link>
      </section>

      <section className="mt-10">
        <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
          Categories
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ORDER.map((slug) => {
            const c = catById.get(slug);
            const a = agentFor(slug);
            return (
              <Link
                key={slug}
                href={`/category/${slug}`}
                className="rounded-xl border border-neutral-200 p-4 transition hover:border-neutral-400"
              >
                <div className="font-medium">
                  <CategoryLabel slug={slug} />
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {c ? `${c.agent_count} agent · ${c.live_runs} runs / 24h` : "—"}
                </div>
                {a && <div className="mt-2 text-sm text-neutral-600">{a.name}</div>}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mt-10">
        <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
          Live activity
        </h2>
        <div className="mt-3">
          {feed.length === 0 ? (
            <EmptyState>
              No runs yet — start the orchestrator ({api.base}) and hire an agent.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-neutral-100 rounded-xl border border-neutral-200 text-sm">
              {feed.map((r) => (
                <li key={r.id} className="flex items-center justify-between px-4 py-2">
                  <Link href={`/agent/${r.agent_id}`} className="font-medium hover:underline">
                    {r.agent_id}
                  </Link>
                  <span className={r.favorable ? "text-emerald-600" : "text-neutral-500"}>
                    {r.delta >= 0 ? "+" : ""}
                    {round(r.delta)} {r.unit} vs baseline
                  </span>
                  <Link
                    href={`/receipt/${r.id}`}
                    className="text-xs text-neutral-400 hover:text-neutral-700"
                  >
                    receipt →
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
