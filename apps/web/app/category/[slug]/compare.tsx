"use client";

import { useState } from "react";
import type { AgentCard } from "@/lib/api";
import { round } from "@/lib/api";

export function Compare({ agents }: { agents: AgentCard[] }) {
  const [picked, setPicked] = useState<string[]>(agents.slice(0, 2).map((a) => a.id));
  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length < 3 ? [...p, id] : p,
    );
  const sel = agents.filter((a) => picked.includes(a.id));

  const rows: [string, (a: AgentCard) => string][] = [
    ["one-liner", (a) => a.one_liner],
    ["tiers", (a) => a.tiers.join(", ")],
    ["price", (a) => (a.pricing.model === "perf_fee" ? `${(a.pricing.bps ?? 0) / 100}%` : a.pricing.model)],
    ["metric", (a) => `${a.advantage_metric.name} (${a.advantage_metric.unit})`],
    ["n runs", (a) => String(a.stats.n_runs)],
    ["window (d)", (a) => (a.stats.window_days == null ? "—" : String(round(a.stats.window_days)))],
    ["median advantage", (a) => (a.stats.median_delta == null ? "No runs yet" : `${a.stats.median_delta >= 0 ? "+" : ""}${round(a.stats.median_delta)}`)],
    ["win rate", (a) => (a.stats.win_rate == null ? "—" : `${Math.round(a.stats.win_rate * 100)}%`)],
    ["max drawdown", (a) => (a.stats.max_drawdown_pct == null ? "—" : `${round(a.stats.max_drawdown_pct)}%`)],
  ];

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {agents.map((a) => (
          <button
            key={a.id}
            onClick={() => toggle(a.id)}
            className={`rounded-full border px-3 py-1 text-xs ${
              picked.includes(a.id)
                ? "border-teal-700 bg-teal-50 text-teal-800"
                : "border-neutral-300 text-neutral-500"
            }`}
          >
            {a.name}
          </button>
        ))}
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[480px] border-collapse text-sm">
          <thead>
            <tr>
              <th className="w-40 border-b border-neutral-200 p-2 text-left text-xs text-neutral-400" />
              {sel.map((a) => (
                <th key={a.id} className="border-b border-neutral-200 p-2 text-left font-medium">
                  {a.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, fn]) => (
              <tr key={label}>
                <td className="border-b border-neutral-100 p-2 text-xs text-neutral-400">{label}</td>
                {sel.map((a) => (
                  <td key={a.id} className="border-b border-neutral-100 p-2 align-top">
                    {fn(a)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
