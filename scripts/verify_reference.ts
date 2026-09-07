/**
 * R1 enforcement (context.md §5, plan.md T-002).
 *
 * For every entry in packages/data/reference/addresses.json + tokens.json:
 *   1. `address` is a valid address, `source` is non-empty, `verified` is true
 *   2. the address has bytecode on BSC (BSC_RPC_URL, or the public default)
 *   3. its `identity` check passes — a real eth_call whose result must match
 *      (`expect` address, `expectNonZero`, or token symbol/decimals)
 *
 * subgraphs.json is reported but NOT gated here: resolving a subgraph needs a
 * live GRAPH_API_KEY and is done in T-003. A subgraph marked verified:true still
 * gets flagged as "unverifiable by this script".
 *
 * Exit 0  iff every address + token check passes.
 *
 * Run:  cd scripts && npm install && npm run verify:reference
 */

import "./_env.ts";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import {
  createPublicClient,
  http,
  isAddress,
  getAddress,
  type AbiFunction,
} from "viem";

const HERE = dirname(fileURLToPath(import.meta.url));
const REF = resolve(HERE, "../packages/data/reference");
const RPC =
  process.env.BSC_RPC_URL ??
  process.env.FORK_RPC_URL ??
  "https://bsc-rpc.publicnode.com";

const client = createPublicClient({ transport: http(RPC) });

type Problem = { where: string; reason: string };
const problems: Problem[] = [];
const ok: string[] = [];

function load(name: string): any {
  return JSON.parse(readFileSync(resolve(REF, name), "utf8"));
}

/** "feeAmountTickSpacing(uint24)(int24)" -> AbiFunction */
function parseSig(sig: string): AbiFunction {
  const m = sig.match(/^(\w+)\(([^)]*)\)\(([^)]*)\)$/);
  if (!m) throw new Error(`bad identity.call signature: ${sig}`);
  const [, name, ins, outs] = m;
  const toParams = (s: string) =>
    s
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .map((type) => ({ type }));
  return {
    type: "function",
    name,
    stateMutability: "view",
    inputs: toParams(ins),
    outputs: toParams(outs),
  };
}

function isIntType(t: string) {
  return /^u?int/.test(t);
}

async function hasBytecode(address: string): Promise<boolean> {
  const code = await client.getCode({ address: address as `0x${string}` });
  return !!code && code !== "0x";
}

async function callIdentity(address: string, identity: any): Promise<void> {
  const fn = parseSig(identity.call as string);
  const args =
    identity.arg !== undefined
      ? [isIntType(fn.inputs[0]?.type ?? "") ? BigInt(identity.arg) : identity.arg]
      : [];
  const result = await client.readContract({
    address: address as `0x${string}`,
    abi: [fn],
    functionName: fn.name,
    args,
  });

  if (identity.expect !== undefined) {
    const got = String(result).toLowerCase();
    const want = String(identity.expect).toLowerCase();
    if (got !== want)
      throw new Error(`${identity.call} => ${result}, expected ${identity.expect}`);
  } else if (identity.expectNonZero) {
    if (BigInt(result as any) === 0n)
      throw new Error(`${identity.call} => 0, expected non-zero`);
  } else {
    throw new Error(`identity for ${address} has neither expect nor expectNonZero`);
  }
}

async function checkAddressEntry(label: string, e: any): Promise<void> {
  const a = (e.address ?? "").trim();
  if (!isAddress(a)) return void problems.push({ where: label, reason: `invalid address: ${a || "(empty)"}` });
  if (getAddress(a) !== a)
    problems.push({ where: label, reason: `address not checksummed: ${a}` });
  if (!(e.source ?? "").trim())
    problems.push({ where: label, reason: "empty source" });
  if (e.verified !== true)
    problems.push({ where: label, reason: "verified !== true" });

  try {
    if (!(await hasBytecode(a)))
      return void problems.push({ where: label, reason: "no bytecode on BSC" });
    if (e.identity && !e.identity.bytecodeOnly) {
      await callIdentity(a, e.identity);
    }
    ok.push(label);
  } catch (err) {
    problems.push({ where: label, reason: (err as Error).message });
  }
}

async function checkTokenEntry(label: string, e: any): Promise<void> {
  const a = (e.address ?? "").trim();
  if (!isAddress(a)) return void problems.push({ where: label, reason: `invalid address: ${a || "(empty)"}` });
  if (e.verified !== true)
    problems.push({ where: label, reason: "verified !== true" });
  try {
    if (!(await hasBytecode(a)))
      return void problems.push({ where: label, reason: "no bytecode on BSC" });
    const erc20 = [
      { type: "function", name: "symbol", stateMutability: "view", inputs: [], outputs: [{ type: "string" }] },
      { type: "function", name: "decimals", stateMutability: "view", inputs: [], outputs: [{ type: "uint8" }] },
    ] as const;
    const [symbol, decimals] = await Promise.all([
      client.readContract({ address: a as `0x${string}`, abi: erc20, functionName: "symbol" }),
      client.readContract({ address: a as `0x${string}`, abi: erc20, functionName: "decimals" }),
    ]);
    if (e.identity?.symbol && symbol !== e.identity.symbol)
      problems.push({ where: label, reason: `symbol() => ${symbol}, expected ${e.identity.symbol}` });
    if (Number(decimals) !== Number(e.decimals))
      problems.push({ where: label, reason: `decimals() => ${decimals}, reference says ${e.decimals}` });
    if (!problems.some((p) => p.where === label)) ok.push(label);
  } catch (err) {
    problems.push({ where: label, reason: (err as Error).message });
  }
}

async function main() {
  console.log(`verify_reference: RPC = ${RPC}\n`);

  const addresses = load("addresses.json");
  const tokens = load("tokens.json");
  const subgraphs = load("subgraphs.json");

  for (const [k, v] of Object.entries<any>(addresses.bsc?.contracts ?? {}))
    await checkAddressEntry(`addresses.${k}`, v);

  for (const [k, v] of Object.entries<any>(tokens.bsc?.tokens ?? {}))
    await checkTokenEntry(`tokens.${k}`, v);

  // subgraphs: PENDING while verified:false; once verified:true, prove it with a live _meta query
  const GRAPH_KEY = process.env.GRAPH_API_KEY ?? "";
  const subEntries = Object.entries<any>(subgraphs).filter(([k]) => !k.startsWith("_"));
  const subPending = subEntries.filter(([, v]) => v.verified !== true);
  const subClaimed = subEntries.filter(([, v]) => v.verified === true);

  for (const s of ok) console.log(`  ok  ${s}`);
  console.log("");
  for (const [k] of subPending)
    console.log(`  --  subgraphs.${k}: PENDING (needs a Graph query API key; finalised in T-003)`);

  for (const [k, v] of subClaimed) {
    const label = `subgraphs.${k}`;
    if (!GRAPH_KEY) {
      problems.push({ where: label, reason: "verified:true but GRAPH_API_KEY unset — cannot confirm" });
      continue;
    }
    try {
      const url = String(v.gateway).replace("{GRAPH_API_KEY}", GRAPH_KEY).replace("{id}", v.id);
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: "{ _meta { block { number } } }" }),
      });
      const j: any = await res.json();
      const block = j?.data?._meta?.block?.number;
      if (!block) throw new Error(j?.errors?.[0]?.message ?? "no _meta.block.number");
      ok.push(`${label} (indexed to block ${block})`);
      console.log(`  ok  ${label} (block ${block})`);
    } catch (err) {
      problems.push({ where: label, reason: (err as Error).message });
    }
  }

  if (problems.length) {
    console.error(`\n${problems.length} problem(s):\n`);
    for (const p of problems) console.error(`  x  [${p.where}] ${p.reason}`);
    console.error("\nR1: fix packages/data/reference/*.json from official docs, then re-run.\n");
    process.exit(1);
  }

  console.log(
    `\nOK — ${ok.length} address/token entries verified on-chain. ` +
      `${subPending.length} subgraph(s) pending (T-003).`,
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
