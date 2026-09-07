"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { api, type HireStatus } from "@/lib/api";

export default function HireRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [status, setStatus] = useState<HireStatus | null>(null);
  const [log, setLog] = useState<{ phase: string; message?: string }[]>([]);

  useEffect(() => {
    const es = new EventSource(api.streamUrl(id));
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.phase && d.phase !== "closed" && d.message !== "keepalive")
        setLog((l) => [...l, { phase: d.phase, message: d.message }]);
      if (d.phase === "closed" || ["ok", "failed", "halted"].includes(d.status)) {
        es.close();
        void api.hire(id).then(setStatus);
      }
    };
    es.onerror = () => {
      es.close();
      void api.hire(id).then(setStatus);
    };
    void api.hire(id).then(setStatus);
    return () => es.close();
  }, [id]);

  const outputs = (status?.result?.outputs ?? {}) as Record<string, unknown>;
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Run</h1>
      <p className="text-xs text-neutral-400">{id}</p>

      <ol className="mt-4 space-y-1 text-sm">
        {log.map((e, i) => (
          <li key={i} className="text-neutral-600">
            <span className="font-mono text-xs text-neutral-400">{e.phase}</span> {e.message}
          </li>
        ))}
      </ol>

      {status && ["ok", "failed", "halted"].includes(status.status) && (
        <div className="mt-4 rounded-xl border border-neutral-200 p-4 text-sm">
          <div className="font-medium">{status.status}</div>
          {status.result && (
            <div className="text-neutral-700">
              {status.result.metric} = {status.result.value.toFixed(3)} · advantage{" "}
              {status.delta != null && `${status.delta >= 0 ? "+" : ""}${status.delta.toFixed(3)}`}
            </div>
          )}
          {typeof outputs.alert === "string" && (
            <p className="mt-1 text-neutral-700">{outputs.alert}</p>
          )}
          {status.receipt && (
            <Link href={`/receipt/${status.receipt.id}`} className="mt-2 inline-block text-teal-700 hover:underline">
              view receipt →
            </Link>
          )}
          {status.error && <p className="mt-1 text-red-600">{status.error}</p>}
        </div>
      )}
    </div>
  );
}
