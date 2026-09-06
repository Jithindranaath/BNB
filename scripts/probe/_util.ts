import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
export const OUT = resolve(HERE, "output");
mkdirSync(OUT, { recursive: true });

export function save(name: string, data: unknown) {
  const path = resolve(OUT, name);
  writeFileSync(path, typeof data === "string" ? data : JSON.stringify(data, null, 2));
  console.log(`  wrote ${path}`);
}

export function ok(msg: string) {
  console.log(`  OK   ${msg}`);
}

/** Print a BLOCKED line in the exact shape plan.md T-003 asks for, and save it. */
export function blocked(name: string, source: string, error: string) {
  const rec = { status: "BLOCKED", source, error, at: new Date().toISOString() };
  save(name, rec);
  console.log(`  BLOCKED ${source} — ${error}`);
}

export async function main(fn: () => Promise<void>) {
  try {
    await fn();
  } catch (e) {
    console.error("  ERROR", (e as Error).message);
    process.exitCode = 1;
  }
}
