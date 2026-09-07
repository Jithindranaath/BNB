"""T-010 acceptance: one live test per source, asserting a non-empty typed result.

These hit real APIs / RPC. Run just these:   pytest -m live
Skip them:                                   pytest -m "not live"
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from data.reference import contract, token_address
from data.settings import settings
from data.sources import binance, bscscan, llama, rpc, subgraph, venus

pytestmark = pytest.mark.live

# Venus vUSDT (Core Pool) — confirmed in scripts/probe/output/venus_reads.json
VUSDT = "0xfD5840Cd36d94D7229439859C0112a4185BC0255"


def test_binance_klines_typed_nonempty():
    ks = binance.get_klines("BNB-USDT", "1h", limit=50)
    assert len(ks) == 50
    assert isinstance(ks[0], binance.Kline)
    assert ks[0].close > 0 and ks[0].volume >= 0
    assert ks[0].open_time < ks[-1].open_time  # ascending


def test_defillama_pools_and_chart():
    pools = llama.get_pools(chain="BSC", project="pancakeswap")
    assert pools and isinstance(pools[0], llama.Pool)
    with_tvl = [p for p in pools if p.tvl_usd]
    assert with_tvl, "expected at least one BSC pancakeswap pool with TVL"
    chart = llama.get_pool_chart(with_tvl[0].pool)
    assert chart and isinstance(chart[0], llama.ChartPoint)


def test_rpc_multicall_erc20_metadata():
    wbnb, usdt = token_address("WBNB"), token_address("USDT")
    meta = rpc.erc20_metadata([wbnb, usdt])
    assert set(meta) == {wbnb, usdt}
    assert meta[wbnb].decimals == 18 and meta[wbnb].symbol == "WBNB"
    assert meta[usdt].decimals == 18


def test_rpc_pancake_v3_pool_state():
    wbnb, usdt = token_address("WBNB"), token_address("USDT")
    (gp,) = rpc.multicall(
        [rpc.Call(contract("pancakeV3Factory"), "getPool(address,address,uint24)",
                  (wbnb, usdt, 500), ("address",))],
        allow_failure=False,
    )
    pool = gp.value
    assert int(pool, 16) != 0, "WBNB/USDT 0.05% pool should exist"
    state = rpc.pancake_v3_pool_state(pool)
    assert {state.token0, state.token1} == {wbnb, usdt}
    assert state.fee == 500 and state.tick_spacing == 10
    assert state.liquidity >= 0 and state.sqrt_price_x96 > 0


def test_venus_markets_and_vtoken():
    markets = venus.get_all_markets()
    assert len(markets) >= 20
    snap = venus.get_vtoken_snapshot(VUSDT)
    assert snap.underlying and snap.underlying.lower() == token_address("USDT").lower()
    assert snap.exchange_rate_stored > 0


def test_venus_account_liquidity_typed():
    # A contract with no Venus position -> (0, 0, 0); we only assert the shape.
    al = venus.get_account_liquidity(contract("multicall3"))
    assert isinstance(al, venus.AccountLiquidity)
    assert al.error_code == 0


@pytest.mark.skipif(not settings().has_bscscan_key, reason="BSCSCAN_API_KEY not set")
def test_bscscan_verified_source():
    src = bscscan.get_contract_source(contract("pancakeV3Factory"))
    assert src.verified is True
    assert src.contract_name == "PancakeV3Factory"
    assert src.abi and isinstance(src.abi, list)


def test_subgraph_pool_or_skip():
    try:
        p = subgraph.get_pool(_wbnb_usdt_pool())
    except subgraph.SubgraphUnavailable as e:
        pytest.skip(f"subgraph not ready: {e}")
    assert p.tvl_usd > Decimal(0)
    assert {p.token0_symbol, p.token1_symbol} == {"WBNB", "USDT"}
    assert p.fee_tier == 500


def _wbnb_usdt_pool() -> str:
    wbnb, usdt = token_address("WBNB"), token_address("USDT")
    (gp,) = rpc.multicall(
        [rpc.Call(contract("pancakeV3Factory"), "getPool(address,address,uint24)",
                  (wbnb, usdt, 500), ("address",))],
        allow_failure=False,
    )
    return gp.value
