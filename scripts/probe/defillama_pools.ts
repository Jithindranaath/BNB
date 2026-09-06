// Probe: DefiLlama yields (no auth). architecture.md §5. Used for pcs-yield TVL/APR + dilution.
import { save, ok, blocked, main } from "./_util.ts";

const BASE = process.env.DEFILLAMA_BASE_URL ?? "https://yields.llama.fi";

main(async () => {
  const poolsUrl = `${BASE}/pools`;
  console.log(`GET ${poolsUrl}`);
  const res = await fetch(poolsUrl);
  if (!res.ok) return blocked("defillama_pools.json", poolsUrl, `HTTP ${res.status}`);
  const body = (await res.json()) as { status: string; data: any[] };

  const bscPcs = body.data
    .filter((p) => p.chain === "BSC" && String(p.project).toLowerCase().includes("pancakeswap"))
    .sort((a, b) => (b.tvlUsd ?? 0) - (a.tvlUsd ?? 0))
    .slice(0, 5);

  save("defillama_pools.json", {
    url: poolsUrl,
    totalPools: body.data.length,
    keys: Object.keys(body.data[0] ?? {}),
    bscPancakeswapTop5: bscPcs,
  });
  ok(`${body.data.length} pools total; ${bscPcs.length} BSC/pancakeswap sampled`);

  // chart history for one pool
  const pid = bscPcs[0]?.pool;
  if (pid) {
    const chartUrl = `${BASE}/chart/${pid}`;
    console.log(`GET ${chartUrl}`);
    const cres = await fetch(chartUrl);
    if (cres.ok) {
      const chart = (await cres.json()) as { status: string; data: any[] };
      save("defillama_chart.json", {
        url: chartUrl,
        pool: pid,
        points: chart.data.length,
        firstPoint: chart.data[0],
        lastPoint: chart.data[chart.data.length - 1],
      });
      ok(`chart for ${pid}: ${chart.data.length} daily points`);
    } else {
      blocked("defillama_chart.json", chartUrl, `HTTP ${cres.status}`);
    }
  }
});
