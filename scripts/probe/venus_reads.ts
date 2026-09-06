// Probe: Venus on-chain reads (no auth). architecture.md §5, spec.md §7.
// spec.md §7.1: act only on on-chain reads. This confirms the read shapes.
import { createPublicClient, http, parseAbi } from "viem";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { save, ok, blocked, main } from "./_util.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const ref = JSON.parse(
  readFileSync(resolve(HERE, "../../packages/data/reference/addresses.json"), "utf8"),
).bsc.contracts;
const RPC = process.env.BSC_RPC_URL ?? "https://bsc-rpc.publicnode.com";

// vUSDT (Core Pool) — from docs-v4.venus.io/deployed-contracts/markets, verified below by underlying()==USDT
const vUSDT = "0xfD5840Cd36d94D7229439859C0112a4185BC0255";

// NOTE (T-003 finding): the Venus Core Pool Comptroller at this address is now an
// EIP-2535 Diamond proxy. Some legacy getters exist (getAllMarkets, closeFactorMantissa,
// oracle), others revert with "Diamond: Function does not exist" (e.g.
// liquidationIncentiveMantissa). T-044 must locate the liquidation-incentive source
// (per-market view or a specific facet) rather than assume the classic Comptroller ABI.
const comptrollerAbi = parseAbi([
  "function getAllMarkets() view returns (address[])",
  "function closeFactorMantissa() view returns (uint256)",
  "function getAccountLiquidity(address) view returns (uint256, uint256, uint256)",
  "function markets(address) view returns (bool isListed, uint256 collateralFactorMantissa)",
]);
const vTokenAbi = parseAbi([
  "function underlying() view returns (address)",
  "function exchangeRateStored() view returns (uint256)",
  "function supplyRatePerBlock() view returns (uint256)",
  "function borrowRatePerBlock() view returns (uint256)",
  "function totalBorrows() view returns (uint256)",
  "function getCash() view returns (uint256)",
]);

main(async () => {
  console.log(`RPC ${RPC}`);
  const client = createPublicClient({ transport: http(RPC) });
  const comptroller = ref.venusComptroller.address as `0x${string}`;

  try {
    const [markets, closeFactor, vUnderlying, exRate, supplyRate, borrowRate, totalBorrows, cash, mkt] =
      await Promise.all([
        client.readContract({ address: comptroller, abi: comptrollerAbi, functionName: "getAllMarkets" }),
        client.readContract({ address: comptroller, abi: comptrollerAbi, functionName: "closeFactorMantissa" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "underlying" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "exchangeRateStored" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "supplyRatePerBlock" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "borrowRatePerBlock" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "totalBorrows" }),
        client.readContract({ address: vUSDT, abi: vTokenAbi, functionName: "getCash" }),
        client.readContract({ address: comptroller, abi: comptrollerAbi, functionName: "markets", args: [vUSDT] }),
      ]);

    save("venus_reads.json", {
      rpc: RPC,
      comptroller,
      comptrollerIsDiamond: true,
      comptrollerNote: "EIP-2535 Diamond; liquidationIncentiveMantissa() reverts 'Diamond: Function does not exist'. T-044 to find the real source.",
      marketCount: (markets as string[]).length,
      markets,
      closeFactorMantissa: (closeFactor as bigint).toString(),
      vUSDT: {
        address: vUSDT,
        underlying: vUnderlying,
        isListed: (mkt as any[])[0],
        collateralFactorMantissa: (mkt as any[])[1]?.toString(),
        exchangeRateStored: (exRate as bigint).toString(),
        supplyRatePerBlock: (supplyRate as bigint).toString(),
        borrowRatePerBlock: (borrowRate as bigint).toString(),
        totalBorrows: (totalBorrows as bigint).toString(),
        getCash: (cash as bigint).toString(),
      },
      note: "getAccountLiquidity(account) returns (err, liquidity, shortfall); a real liquidated account is supplied in T-044 for the no_action replay baseline.",
    });
    ok(`${(markets as string[]).length} markets; vUSDT.underlying = ${vUnderlying}`);
  } catch (e) {
    blocked("venus_reads.json", RPC, (e as Error).message);
  }
});
