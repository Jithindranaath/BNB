"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { AgentDetail, InputSpec } from "@/lib/api";
import { api } from "@/lib/api";

type Step = "configure" | "review" | "run";

export function HirePanel({ agent, prefill }: { agent: AgentDetail; prefill: Record<string, string> }) {
  const [tier] = useState<number>(agent.tiers[0]);
  const [step, setStep] = useState<Step>("configure");
  const [values, setValues] = useState<Record<string, string>>(() => {
    const v: Record<string, string> = {};
    for (const [name, spec] of Object.entries(agent.inputs)) {
      v[name] =
        prefill[name] ??
        (spec.default != null ? String(spec.default) : "");
    }
    return v;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [hireId, setHireId] = useState<string | null>(null);
  const [log, setLog] = useState<{ phase: string; message?: string }[]>([]);
  const [done, setDone] = useState<null | {
    status: string;
    delta: number | null;
    receiptId: string | null;
    metric?: string;
    value?: number;
    alert?: string;
  }>(null);

  const coerced = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const [name, spec] of Object.entries(agent.inputs)) {
      const raw = values[name];
      if (raw === "" || raw == null) continue;
      out[name] = spec.type === "number" ? Number(raw) : raw;
    }
    return out;
  }, [values, agent.inputs]);

  async function submit() {
    setStep("run");
    setLog([{ phase: "submitting" }]);
    const res = await api.createHire({ agent_id: agent.id, tier, inputs: coerced });
    if (!res.ok) {
      setErrors(res.json.detail?.errors ?? { _: `HTTP ${res.status}` });
      setStep("configure");
      return;
    }
    const id = res.json.hire_id!;
    setHireId(id);
    const es = new EventSource(api.streamUrl(id));
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.phase && d.phase !== "closed")
        setLog((l) => [...l, { phase: d.phase, message: d.message }]);
      if (d.phase === "closed" || ["ok", "failed", "halted"].includes(d.status)) {
        es.close();
        void finish(id);
      }
    };
    es.onerror = () => {
      es.close();
      void finish(id);
    };
  }

  async function finish(id: string) {
    const s = await api.hire(id);
    if (!s) return;
    const outputs = (s.result?.outputs ?? {}) as Record<string, unknown>;
    setDone({
      status: s.status,
      delta: s.delta,
      receiptId: s.receipt?.id ?? null,
      metric: s.result?.metric,
      value: s.result?.value,
      alert: typeof outputs.alert === "string" ? outputs.alert : undefined,
    });
  }

  return (
    <div className="rounded-xl border border-neutral-200 p-4">
      <div className="mb-3 flex gap-2 text-xs">
        {(["configure", "review", "run"] as Step[]).map((s, i) => (
          <span
            key={s}
            className={`rounded px-2 py-0.5 ${step === s ? "bg-teal-700 text-white" : "bg-neutral-100 text-neutral-500"}`}
          >
            {i + 1}. {s}
          </span>
        ))}
      </div>

      {step === "configure" && (
        <div className="space-y-3">
          {Object.entries(agent.inputs).map(([name, spec]) => (
            <Field
              key={name}
              name={name}
              spec={spec}
              value={values[name] ?? ""}
              error={errors[name]}
              onChange={(v) => setValues((s) => ({ ...s, [name]: v }))}
            />
          ))}
          {errors._ && <p className="text-xs text-red-600">{errors._}</p>}
          <button
            onClick={() => setStep("review")}
            className="rounded-lg bg-neutral-900 px-3 py-1.5 text-sm text-white"
          >
            Review
          </button>
        </div>
      )}

      {step === "review" && (
        <div className="space-y-3 text-sm">
          <p className="text-neutral-600">
            Tier {tier} — {tier < 2 ? "no funds at risk. This runs on live prices, paper only." : "live execution via a scoped session key."}
          </p>
          <pre className="overflow-x-auto rounded bg-neutral-50 p-3 text-xs">
            {JSON.stringify({ agent: agent.id, tier, inputs: coerced }, null, 2)}
          </pre>
          <div className="flex gap-2">
            <button onClick={() => setStep("configure")} className="rounded-lg border px-3 py-1.5 text-sm">
              Back
            </button>
            <button onClick={submit} className="rounded-lg bg-teal-700 px-3 py-1.5 text-sm text-white">
              Run
            </button>
          </div>
        </div>
      )}

      {step === "run" && (
        <div className="space-y-2 text-sm">
          <ol className="space-y-1">
            {log.map((e, i) => (
              <li key={i} className="text-neutral-600">
                <span className="font-mono text-xs text-neutral-400">{e.phase}</span> {e.message}
              </li>
            ))}
          </ol>
          {!done && <p className="text-xs text-neutral-400">running…</p>}
          {done && (
            <div className="rounded-lg bg-neutral-50 p-3">
              <div className="font-medium">
                {done.status === "ok" ? "Done" : done.status}
                {done.metric != null && done.value != null && (
                  <> — {done.metric} = {done.value.toFixed(3)}</>
                )}
              </div>
              {done.delta != null && (
                <div className="text-neutral-600">
                  advantage vs baseline: {done.delta >= 0 ? "+" : ""}
                  {done.delta.toFixed(3)}
                </div>
              )}
              {done.alert && <p className="mt-1 text-neutral-700">{done.alert}</p>}
              {done.receiptId && (
                <Link
                  href={`/receipt/${done.receiptId}`}
                  className="mt-2 inline-block text-teal-700 hover:underline"
                >
                  view receipt →
                </Link>
              )}
            </div>
          )}
          {hireId && (
            <Link href={`/hire/${hireId}`} className="text-xs text-neutral-400 hover:text-neutral-700">
              open full run view →
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

function Field({
  name,
  spec,
  value,
  error,
  onChange,
}: {
  name: string;
  spec: InputSpec;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs text-neutral-500">
        {name}
        {spec.required && <span className="text-red-500"> *</span>}
        {spec.type === "number" && spec.min != null && (
          <span className="text-neutral-400"> ({spec.min}–{spec.max})</span>
        )}
      </span>
      {spec.type === "enum" ? (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
        >
          {(spec.values ?? []).map((v) => (
            <option key={String(v)} value={String(v)}>
              {String(v)}
            </option>
          ))}
        </select>
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.type === "address" ? "0x…" : spec.type}
          className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm"
        />
      )}
      {error && <span className="text-xs text-red-600">{error}</span>}
    </label>
  );
}
