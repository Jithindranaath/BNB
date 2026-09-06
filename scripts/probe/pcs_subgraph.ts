// Probe: PancakeSwap v3 subgraph. architecture.md §5, §13.
// Live queries on The Graph decentralised network REQUIRE GRAPH_API_KEY.
// Tries, in order: (1) Graph gateway with each candidate id, (2) any legacy
// hosted URL. Records exactly what worked so T-002's subgraphs.json can be
// finalised. plan.md T-003: "confirm the subgraph id resolves and return one pool".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { save, ok, blocked, main } from "./_util.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const sg = JSON.parse(
  readFileSync(resolve(HERE, "../../packages/data/reference/subgraphs.json"), "utf8"),
).pancakeswapV3Bsc;

const KEY = process.env.GRAPH_API_KEY ?? "";
const QUERY = `{ pools(first: 1, orderBy: totalValueLockedUSD, orderDirection: desc) {
  id feeTier token0 { symbol } token1 { symbol } totalValueLockedUSD
  poolDayData(first: 2, orderBy: date, orderDirection: desc) { date feesUSD tvlUSD volumeUSD }
} }`;

async function tryGraphql(url: string) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: QUERY }),
  });
  const text = await res.text();
  let json: any;
  try {
    json = JSON.parse(text);
  } catch {
    return { url, httpStatus: res.status, ok: false, raw: text.slice(0, 500) };
  }
  const pool = json?.data?.pools?.[0];
  return { url, httpStatus: res.status, ok: !!pool, errors: json?.errors, pool };
}

main(async () => {
  const attempts: any[] = [];
  const ids = [sg.id, sg.id_alt].filter(Boolean);

  if (KEY) {
    for (const id of ids) {
      const url = sg.gateway.replace("{GRAPH_API_KEY}", KEY).replace("{id}", id);
      console.log(`POST gateway id=${id}`);
      attempts.push({ ...(await tryGraphql(url)), id, url: url.replace(KEY, "***") });
    }
  } else {
    attempts.push({ note: "GRAPH_API_KEY unset — skipped decentralised-network gateway" });
  }

  // legacy hosted service (decommissioned ~2024, but record the response)
  for (const url of [
    "https://api.thegraph.com/subgraphs/name/pancakeswap/exchange-v3-bsc",
  ]) {
    console.log(`POST legacy ${url}`);
    try {
      attempts.push(await tryGraphql(url));
    } catch (e) {
      attempts.push({ url, ok: false, error: (e as Error).message });
    }
  }

  const winner = attempts.find((a) => a.ok);
  if (winner) {
    save("pcs_subgraph.json", { resolvedVia: winner.url, id: winner.id, attempts });
    ok(`resolved: pool ${winner.pool?.id} ${winner.pool?.token0?.symbol}/${winner.pool?.token1?.symbol}, ${winner.pool?.poolDayData?.length} day-data points`);
  } else {
    blocked(
      "pcs_subgraph.json",
      "PancakeSwap v3 BSC subgraph",
      KEY ? "no candidate id returned a pool — see attempts[]" : "GRAPH_API_KEY not set",
    );
    save("pcs_subgraph_attempts.json", { attempts });
  }
});
