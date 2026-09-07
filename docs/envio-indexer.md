# PancakeSwap v3 BSC data — Envio HyperIndex (T-033 enrichment)

**Status:** optional upgrade. `pcs-yield` ships today on DefiLlama (PancakeSwap
**v2** BSC) + Binance vol + the on-chain sentry gate. This indexer adds real
PancakeSwap **v3** per-pool fee / TVL / volume day-data — The Graph's
decentralised network has no synced PCS v3 BSC subgraph (see
`docs/findings/T-003.md`), so we run our own.

Once it is live, set `PCS_V3_GRAPHQL_URL` in `.env` and `pcs-yield` can switch
`fee_apr_source` from `apyMean30d` (DefiLlama) to the indexer's `poolDayData`
without any change to the net-APR maths.

---

## Why our own indexer

`enviodev/uniswap-v3-indexer` is a maintained 1:1 behavioural port of the
Uniswap v3 subgraph (same entities: `Pool`, `PoolDayData`, `PoolHourData` with
`feesUSD` / `tvlUSD` / `volumeUSD`, `Token`, `Position`, `Swap`). PancakeSwap v3
is a near-exact fork of Uniswap v3 — the pool events (`Initialize`, `Mint`,
`Burn`, `Collect`, `Swap`) are byte-identical — so the indexer works unchanged
once it is pointed at PancakeSwap's factory and given BSC pricing constants.

Envio's HyperIndex synced the full PancakeSwap v3 BSC history (1.7B events) in
~10 days for Revert Finance; a recent-only start block syncs in hours.

## Deploy

```bash
git clone https://github.com/enviodev/uniswap-v3-indexer pcs-v3-indexer
cd pcs-v3-indexer
```

### 1. Add the BSC / PancakeSwap chain block to `config.yaml`

The repo's checked-in `config.yaml` has Ethereum / Optimism / Arbitrum. Add:

```yaml
  - id: 56 # BSC — PancakeSwap v3
    start_block: 26956207   # PancakeSwapV3PoolDeployer / factory deploy (Envio's Revert Finance backfill start)
    contracts:
      - name: UniswapV3Factory
        address:
          - "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865"   # PancakeSwap v3 factory
      - name: UniswapV3Pool
      - name: NonfungiblePositionManager
        address:
          - "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364"   # PancakeSwap v3 NPM
```

Set `start_block` to a recent block (e.g. ~14 days back) if you only need current
fee-APR ranking and want a fast first sync; use `26956207` for full history.

### 2. Add the BSC entry to `src/handlers/utils/chains.ts`

The repo already has a `[ChainId.BSC]` block pointed at **Uniswap** v3 on BSC.
Replace its `factoryAddress` and `stablecoinWrappedNativePoolId` with
PancakeSwap's, and widen the whitelist:

```ts
  [ChainId.BSC]: {
    factoryAddress: "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865", // PancakeSwap v3
    stablecoinWrappedNativePoolId: "0x172fcd41e0913e95784454622d1c3724f546f849", // PCS v3 WBNB/USDT 0.01%
    wrappedNativeAddress: "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", // WBNB
    minimumNativeLocked: new BigDecimal("100"),
    stablecoinAddresses: [
      "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", // USDC
      "0x55d398326f99059ff775485246999027b3197955", // USDT (BSC-USD)
      "0xe9e7cea3dedca5984780bafc599bd69add087d56", // BUSD
    ],
    whitelistTokens: [
      "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", // WBNB
      "0x55d398326f99059ff775485246999027b3197955", // USDT
      "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", // USDC
      "0xe9e7cea3dedca5984780bafc599bd69add087d56", // BUSD
      "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82", // CAKE
      "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c", // BTCB
      "0x2170ed0880ac9a755fd29b2688956bd959f933f8", // ETH
    ],
    tokenOverrides: [],
    poolsToSkip: [],
    poolMappings: [],
    nativeTokenDetails: { symbol: "BNB", name: "Binance Coin", decimals: BigInt(18) },
  },
```

> Verify the NPM address and the WBNB/USDT v3 pool id against
> `packages/data/reference/addresses.json` conventions before deploying — run
> `PancakeV3Factory.getPool(WBNB, USDT, 100)` to reconfirm the pool id.

### 3. Codegen + run

```bash
pnpm i
pnpm codegen
# local (Docker: Postgres + Hasura on :8080)
pnpm dev
# GraphQL at http://localhost:8080/v1/graphql  (Hasura dialect, admin secret in .env)
```

Envio's CLI wants Node 18–22; this repo's box has Node 24. If `pnpm dev` fails on
the Node version, use `fnm`/`nvm` to pin 22 for this directory, or deploy to
**Envio Cloud** instead (below).

### 4. Deploy to Envio Cloud (hosted, free tier)

1. Push the fork to your GitHub.
2. [envio.dev/app](https://envio.dev/app) → **Add Indexer** → connect the repo.
3. It builds + syncs on Envio's infra and gives you a hosted GraphQL URL.
4. Token for the CLI (`envio` login / deploy) is `ENVIO_API_TOKEN` in `.env`
   (already set) — from [envio.dev/app/api-tokens](https://envio.dev/app/api-tokens).

### 5. Wire it in

```
PCS_V3_GRAPHQL_URL=https://<your-indexer>.envio.dev/v1/graphql   # or http://localhost:8080/v1/graphql
```

Then `packages/data/sources/subgraph.py` gets a small rewrite for the Hasura
dialect (`Pool(where: {...}, order_by: {...}, limit: N)` instead of
`pools(first: N, orderBy: ...)`; IDs are `<chainId>-<address>`), a probe under
`scripts/probe/` per rule R5, and `pcs_yield/sources.py` gains an
`envio_fee_apr(pool)` that reads `PoolDayData.feesUSD / PoolDayData.tvlUSD`
over the last 30 days. The economics in `pcs_yield/economics.py` do not change.

---

## Entities we need (all present in the Uniswap v3 schema the indexer ports)

| Entity | Fields used |
|---|---|
| `Pool` | `id`, `token0/1 { id symbol decimals }`, `feeTier`, `totalValueLockedUSD`, `volumeUSD`, `feesUSD`, `feeGrowthGlobal0X128/1X128`, `token0Price/token1Price` |
| `PoolDayData` | `date`, `feesUSD`, `tvlUSD`, `volumeUSD` — the fee-APR series |
| `Token` | `id`, `symbol`, `decimals`, `totalValueLockedUSD` |
