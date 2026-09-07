import Link from "next/link";
import type { AgentCard, Pricing } from "@/lib/api";
import { fmtAdvantage } from "@/lib/api";

export function TierBadges({ tiers }: { tiers: number[] }) {
  const label: Record<number, string> = { 0: "T0 · no wallet", 1: "T1 · paper", 2: "T2 · live" };
  return (
    <span className="flex flex-wrap gap-1">
      {tiers.map((t) => (
        <span
          key={t}
          className="rounded border border-neutral-300 px-1.5 py-0.5 text-[11px] text-neutral-600"
        >
          {label[t] ?? `T${t}`}
        </span>
      ))}
    </span>
  );
}

export function PriceTag({ pricing }: { pricing: Pricing }) {
  const txt =
    pricing.model === "free"
      ? "Free"
      : pricing.model === "perf_fee"
        ? `${((pricing.bps ?? 0) / 100).toFixed(1)}% perf fee`
        : pricing.model === "flat"
          ? "Flat fee"
          : "Price TBD";
  return <span className="text-xs text-neutral-500">{txt}</span>;
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-neutral-300 p-6 text-sm text-neutral-500">
      {children}
    </div>
  );
}

export function CategoryLabel({ slug }: { slug: string }) {
  const m: Record<string, string> = {
    security: "Security",
    yield: "Yield",
    grid: "Grid trading",
    rebalancing: "Rebalancing",
    health_factor: "Health factor",
  };
  return <>{m[slug] ?? slug}</>;
}

export function AgentCardView({ card }: { card: AgentCard }) {
  return (
    <Link
      href={`/agent/${card.id}`}
      className="block rounded-xl border border-neutral-200 p-4 transition hover:border-neutral-400"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium">{card.name}</div>
          <div className="text-xs uppercase tracking-wide text-neutral-400">
            <CategoryLabel slug={card.category} />
          </div>
        </div>
        <TierBadges tiers={card.tiers} />
      </div>
      <p className="mt-2 text-sm text-neutral-600">{card.one_liner}</p>
      <div className="mt-3 flex items-center justify-between">
        <PriceTag pricing={card.pricing} />
        {card.sentry_gate && (
          <span className="text-[11px] text-emerald-600">security-gated</span>
        )}
      </div>
      {card.available ? (
        <div
          className={`mt-3 rounded-md px-2 py-1.5 text-xs ${
            card.has_runs ? "bg-neutral-50 text-neutral-700" : "bg-neutral-50 text-neutral-400"
          }`}
        >
          {fmtAdvantage(card)}
        </div>
      ) : (
        <div className="mt-3 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-700">
          <span className="font-medium">Not yet available</span>
          {card.unavailable_reason ? ` — ${card.unavailable_reason}` : ""}
        </div>
      )}
    </Link>
  );
}
