/**
 * Typed client for the orchestrator (spec.md §8). Fleshed out in T-050.
 * Base URL comes from NEXT_PUBLIC_ORCHESTRATOR_URL.
 */

export const ORCHESTRATOR_URL =
  process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://localhost:8080";

export type HealthReport = {
  status: string;
  deps: Record<string, string>;
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${ORCHESTRATOR_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET ${path} -> ${res.status}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => get<HealthReport>("/healthz"),
  // agents, agent detail, receipts, hires, report ... land in T-050/T-060.
};
