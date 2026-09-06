import { brand } from "@/config/brand";

const categories = [
  { slug: "security", label: "Security", agent: "bsc-sentry" },
  { slug: "yield", label: "Yield", agent: "pcs-yield" },
  { slug: "grid", label: "Grid trading", agent: "bnb-grid" },
  { slug: "rebalancing", label: "Rebalancing", agent: "pcs-rebalancer" },
  { slug: "health_factor", label: "Health factor", agent: "venus-guard" },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{brand.name}</h1>
      <p className="mt-3 text-neutral-600">{brand.tagline}</p>

      <p className="mt-8 inline-block rounded-md border border-neutral-300 px-4 py-2 text-sm">
        {brand.primaryCta}
      </p>

      <h2 className="mt-12 text-sm font-medium uppercase tracking-wide text-neutral-500">
        Categories
      </h2>
      <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {categories.map((c) => (
          <li
            key={c.slug}
            className="rounded-lg border border-neutral-200 p-4 text-sm"
          >
            <div className="font-medium">{c.label}</div>
            <div className="mt-1 text-neutral-500">{c.agent}</div>
          </li>
        ))}
      </ul>

      <p className="mt-12 text-xs text-neutral-400">
        Scaffold (T-001). Real landing page is T-051.
      </p>
    </main>
  );
}
