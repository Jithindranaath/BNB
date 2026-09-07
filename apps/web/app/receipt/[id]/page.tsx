import Link from "next/link";
import { notFound } from "next/navigation";
import { api, round } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ReceiptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const r = await api.receipt(id);
  if (!r) notFound();

  const rows: [string, string][] = [
    ["agent", r.agent_id],
    ["metric", `${r.metric} (${r.unit})`],
    ["agent value", String(round(r.agent_value, 4))],
    ["baseline value", String(round(r.baseline_value, 4))],
    ["advantage delta", `${r.delta >= 0 ? "+" : ""}${round(r.delta, 4)} — ${r.favorable ? "favorable" : "unfavorable"}`],
    ["created", new Date(r.created_at).toLocaleString()],
    ["agent run", r.agent_run_id],
    ["baseline run", r.baseline_run_id],
  ];

  return (
    <div>
      <Link href={`/agent/${r.agent_id}`} className="text-xs text-neutral-400 hover:text-neutral-700">
        ← {r.agent_id}
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">Receipt</h1>
      <p className="text-xs text-neutral-400">{r.id}</p>

      <table className="mt-5 w-full border-collapse text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="w-40 border-b border-neutral-100 py-2 text-xs text-neutral-400">{k}</td>
              <td className="border-b border-neutral-100 py-2 font-mono text-xs">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <section className="mt-6 rounded-xl border border-neutral-200 p-4 text-sm">
        <h2 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
          Merkle verification
        </h2>
        <div className="mt-2 space-y-1 font-mono text-xs">
          <div>leaf: {r.merkle_leaf}</div>
          <div>batch: {r.batch_id ?? "— (unbatched)"}</div>
          <div>anchor root: {r.anchor_root ?? "—"}</div>
          <div>anchor tx: {r.anchored_tx ?? "—"}</div>
        </div>
        {r.merkle_proof && r.merkle_proof.length > 0 ? (
          <details className="mt-2">
            <summary className="cursor-pointer text-neutral-600">proof ({r.merkle_proof.length} nodes)</summary>
            <ul className="mt-1 font-mono text-[11px] text-neutral-500">
              {r.merkle_proof.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <p className="mt-3 text-xs text-neutral-500">{r.verified_hint}</p>
      </section>
    </div>
  );
}
