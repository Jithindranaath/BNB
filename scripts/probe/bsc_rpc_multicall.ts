// Probe: BSC RPC + Multicall3 aggregate3 (no auth on PublicNode). architecture.md §5.
// Confirms the multicall pattern packages/data/sources/rpc.py will use — never loop single calls.
import { createPublicClient, http, parseAbi } from "viem";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { save, ok, blocked, main } from "./_util.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ref = JSON.parse(
  readFileSync(resolve(HERE, "../../packages/data/reference/addresses.json"), "utf8"),
).bsc.contracts;
const tokens = JSON.parse(
  readFileSync(resolve(HERE, "../../packages/data/reference/tokens.json"), "utf8"),
).bsc.tokens;

const RPC = process.env.BSC_RPC_URL ?? "https://bsc-rpc.publicnode.com";

main(async () => {
  console.log(`RPC ${RPC}`);
  const client = createPublicClient({ transport: http(RPC) });

  const erc20 = parseAbi(["function decimals() view returns (uint8)", "function symbol() view returns (string)"]);
  const factoryAbi = parseAbi(["function owner() view returns (address)"]);

  try {
    const [block, results] = await Promise.all([
      client.getBlockNumber(),
      client.multicall({
        multicallAddress: ref.multicall3.address,
        allowFailure: true,
        contracts: [
          { address: tokens.WBNB.address, abi: erc20, functionName: "symbol" },
          { address: tokens.WBNB.address, abi: erc20, functionName: "decimals" },
          { address: tokens.USDT.address, abi: erc20, functionName: "symbol" },
          { address: ref.pancakeV3Factory.address, abi: factoryAbi, functionName: "owner" },
        ],
      }),
    ]);
    save("bsc_rpc_multicall.json", {
      rpc: RPC,
      multicall3: ref.multicall3.address,
      blockNumber: block.toString(),
      results,
    });
    ok(`block ${block}; multicall returned ${results.length} results, statuses = ${results.map((r) => r.status).join(",")}`);
  } catch (e) {
    blocked("bsc_rpc_multicall.json", RPC, (e as Error).message);
  }
});
