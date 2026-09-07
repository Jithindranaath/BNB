import type { Curve } from "@/lib/api";

/** Minimal dual-line SVG: agent value vs baseline value over the receipt feed. */
export function CurveChart({ curve }: { curve: Curve }) {
  const pts = curve.points;
  if (pts.length < 2) {
    return (
      <div className="rounded-lg border border-dashed border-neutral-300 p-6 text-sm text-neutral-500">
        Not enough receipts yet to draw the {curve.metric} curve.
      </div>
    );
  }
  const W = 640;
  const H = 200;
  const pad = 28;
  const all = pts.flatMap((p) => [p.agent_value, p.baseline_value]);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i: number) => pad + (i / (pts.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  const path = (key: "agent_value" | "baseline_value") =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

  return (
    <figure className="rounded-lg border border-neutral-200 p-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#e5e5e5" />
        <path d={path("baseline_value")} fill="none" stroke="#a3a3a3" strokeWidth={1.5} />
        <path d={path("agent_value")} fill="none" stroke="#0f766e" strokeWidth={2} />
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-neutral-500">
        <span>
          <span className="text-teal-700">■</span> agent &nbsp;
          <span className="text-neutral-400">■</span> baseline &nbsp;({curve.unit})
        </span>
        <span>
          window: {curve.window_days == null ? "—" : `${curve.window_days.toFixed(1)}d`} · n=
          {pts.length}
        </span>
      </figcaption>
    </figure>
  );
}
