import Link from "next/link";
import { api } from "@/lib/api";
import { AgentCardView, CategoryLabel, EmptyState } from "@/components/ui";
import { Compare } from "./compare";

export const dynamic = "force-dynamic";

export default async function CategoryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const all = await api.agents();
  const inCat = all.filter((a) => a.category === slug);

  return (
    <div>
      <Link href="/" className="text-xs text-neutral-400 hover:text-neutral-700">
        ← Marketplace
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">
        <CategoryLabel slug={slug} />
      </h1>

      {inCat.length === 0 ? (
        <EmptyState>No agents in this category.</EmptyState>
      ) : (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {inCat.map((c) => (
              <AgentCardView key={c.id} card={c} />
            ))}
          </div>
          {inCat.length > 1 && (
            <div className="mt-8">
              <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
                Compare
              </h2>
              <Compare agents={inCat} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
