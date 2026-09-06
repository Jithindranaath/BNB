/**
 * R1 enforcement (context.md §5, plan.md T-002).
 *
 * Fails (exit 1) unless EVERY entry in packages/data/reference/*.json:
 *   - has a non-empty `address` / `id`
 *   - has a non-empty `source`
 *   - has `verified: true`
 *   - (addresses) has on-chain bytecode at BSC_RPC_URL
 *
 * Scaffold state: all entries are blank -> this exits 1 by design until T-002
 * populates them from the official docs.
 *
 * Run:  cd scripts && npm install && npm run verify:reference
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { createPublicClient, http, isAddress } from "viem";

const HERE = dirname(fileURLToPath(import.meta.url));
const REF = resolve(HERE, "../packages/data/reference");
const RPC = process.env.BSC_RPC_URL ?? "";

type Problem = { file: string; path: string; reason: string };
const problems: Problem[] = [];

function load(name: string): any {
  return JSON.parse(readFileSync(resolve(REF, name), "utf8"));
}

function checkEntry(file: string, path: string, e: Record<string, any>, idKey: "address" | "id") {
  const id = (e[idKey] ?? "").toString().trim();
  if (!id) problems.push({ file, path, reason: `empty ${idKey}` });
  if (!(e.source ?? e.note ?? "").toString().trim())
    problems.push({ file, path, reason: "empty source/note" });
  if (e.verified !== true) problems.push({ file, path, reason: "verified !== true" });
  if (idKey === "address" && id && !isAddress(id))
    problems.push({ file, path, reason: `not a valid address: ${id}` });
  return id;
}

async function main() {
  const addresses = load("addresses.json");
  const tokens = load("tokens.json");
  const subgraphs = load("subgraphs.json");

  const onchain: string[] = [];

  for (const [k, v] of Object.entries<any>(addresses.bsc?.contracts ?? {})) {
    const id = checkEntry("addresses.json", `bsc.contracts.${k}`, v, "address");
    if (id && isAddress(id)) onchain.push(id);
  }
  for (const [k, v] of Object.entries<any>(tokens.bsc?.tokens ?? {})) {
    const id = checkEntry("tokens.json", `bsc.tokens.${k}`, v, "address");
    if (id && isAddress(id)) onchain.push(id);
  }
  for (const [k, v] of Object.entries<any>(subgraphs)) {
    if (k.startsWith("_")) continue;
    checkEntry("subgraphs.json", k, v, "id");
  }

  if (onchain.length && RPC) {
    const client = createPublicClient({ transport: http(RPC) });
    for (const addr of onchain) {
      try {
        const code = await client.getCode({ address: addr as `0x${string}` });
        if (!code || code === "0x")
          problems.push({ file: "on-chain", path: addr, reason: "no bytecode at BSC_RPC_URL" });
      } catch (err) {
        problems.push({ file: "on-chain", path: addr, reason: `RPC error: ${(err as Error).message}` });
      }
    }
  } else if (onchain.length && !RPC) {
    problems.push({ file: "env", path: "BSC_RPC_URL", reason: "unset — cannot check bytecode" });
  }

  if (problems.length) {
    console.error(`\nverify_reference: ${problems.length} problem(s)\n`);
    for (const p of problems) console.error(`  ✗ [${p.file}] ${p.path} — ${p.reason}`);
    console.error("\nR1: populate packages/data/reference/*.json from official docs, then re-run.\n");
    process.exit(1);
  }

  console.log("verify_reference: OK — every reference entry is populated and verified.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
