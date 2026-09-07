"""Venus (Core Pool) on-chain reads. spec.md §7.1: act ONLY on on-chain reads —
subgraph lag can get a user liquidated.

T-003 finding: the Comptroller at reference `venusComptroller` is an EIP-2535
Diamond. `getAllMarkets()`, `closeFactorMantissa()`, `getAccountLiquidity()`,
`markets(vToken)` all resolve; some classic getters (e.g.
`liquidationIncentiveMantissa()`) revert `Diamond: Function does not exist`.
The liquidation-incentive source is pinned down in T-044.
"""

from __future__ import annotations

from eth_utils import to_checksum_address
from pydantic import BaseModel, ConfigDict

from .. import reference
from .rpc import Call, multicall

# vBNB has no underlying(); its underlying is native BNB (18 decimals).
VBNB = "0xA07c5b74C9B40447a954e1466938b865b6BBea36"


class AccountLiquidity(BaseModel):
    model_config = ConfigDict(frozen=True)

    account: str
    error_code: int
    liquidity_usd_1e18: int   # excess collateral, scaled 1e18
    shortfall_usd_1e18: int   # > 0 means liquidatable

    @property
    def is_liquidatable(self) -> bool:
        return self.shortfall_usd_1e18 > 0


class VTokenSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    vtoken: str
    underlying: str | None
    supply_rate_per_block: int
    borrow_rate_per_block: int
    exchange_rate_stored: int
    total_borrows: int
    cash: int
    collateral_factor_mantissa: int


def get_all_markets() -> list[str]:
    (res,) = multicall(
        [Call(reference.contract("venusComptroller"), "getAllMarkets()", outputs=("address[]",))],
        allow_failure=False,
    )
    return [to_checksum_address(a) for a in res.value]


def get_account_liquidity(account: str) -> AccountLiquidity:
    (res,) = multicall(
        [
            Call(
                reference.contract("venusComptroller"),
                "getAccountLiquidity(address)",
                args=(to_checksum_address(account),),
                outputs=("uint256", "uint256", "uint256"),
            )
        ],
        allow_failure=False,
    )
    err, liq, short = res.decoded
    return AccountLiquidity(
        account=to_checksum_address(account),
        error_code=err,
        liquidity_usd_1e18=liq,
        shortfall_usd_1e18=short,
    )


def get_vtoken_snapshot(vtoken: str) -> VTokenSnapshot:
    comptroller = reference.contract("venusComptroller")
    calls = [
        Call(vtoken, "underlying()", outputs=("address",), label="underlying"),
        Call(vtoken, "supplyRatePerBlock()", outputs=("uint256",), label="supplyRate"),
        Call(vtoken, "borrowRatePerBlock()", outputs=("uint256",), label="borrowRate"),
        Call(vtoken, "exchangeRateStored()", outputs=("uint256",), label="exchangeRate"),
        Call(vtoken, "totalBorrows()", outputs=("uint256",), label="totalBorrows"),
        Call(vtoken, "getCash()", outputs=("uint256",), label="cash"),
        Call(comptroller, "markets(address)", args=(to_checksum_address(vtoken),),
             outputs=("bool", "uint256"), label="market"),
    ]
    r = multicall(calls)
    by = {c.label: res for c, res in zip(calls, r, strict=True)}
    # vBNB has no underlying() — tolerate the revert
    underlying = by["underlying"].value if by["underlying"].success else None
    market = by["market"].decoded if by["market"].success else (False, 0)
    return VTokenSnapshot(
        vtoken=to_checksum_address(vtoken),
        underlying=to_checksum_address(underlying) if underlying else None,
        supply_rate_per_block=by["supplyRate"].value or 0,
        borrow_rate_per_block=by["borrowRate"].value or 0,
        exchange_rate_stored=by["exchangeRate"].value or 0,
        total_borrows=by["totalBorrows"].value or 0,
        cash=by["cash"].value or 0,
        collateral_factor_mantissa=market[1],
    )


# --- account health (spec.md §7.1) --------------------------------

class MarketPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    vtoken: str
    symbol: str
    underlying_decimals: int
    supply_units: float          # underlying supplied
    borrow_units: float          # underlying borrowed
    price_usd: float
    collateral_factor: float
    supply_usd: float
    borrow_usd: float

    @property
    def collateral_adjusted_usd(self) -> float:
        return self.supply_usd * self.collateral_factor


class AccountHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    account: str
    markets: list[MarketPosition]
    total_supply_usd: float
    total_borrow_usd: float
    collateral_adjusted_usd: float
    liquidity_usd: float          # from Comptroller.getAccountLiquidity (excess)
    shortfall_usd: float

    @property
    def health_factor(self) -> float:
        if self.total_borrow_usd <= 0:
            return float("inf")
        return self.collateral_adjusted_usd / self.total_borrow_usd

    @property
    def dominant_collateral(self) -> MarketPosition | None:
        supplied = [m for m in self.markets if m.supply_usd > 0]
        return max(supplied, key=lambda m: m.supply_usd) if supplied else None


def _oracle_address() -> str:
    (res,) = multicall(
        [Call(reference.contract("venusComptroller"), "oracle()", outputs=("address",))],
        allow_failure=False,
    )
    return to_checksum_address(res.value)


def account_health(account: str) -> AccountHealth:
    """Full on-chain health snapshot: per-market supply/borrow in USD, the
    collateral-factor-adjusted collateral, and the health factor."""
    account = to_checksum_address(account)
    comptroller = reference.contract("venusComptroller")
    oracle = _oracle_address()

    (assets_res, liq_res) = multicall(
        [
            Call(comptroller, "getAssetsIn(address)", args=(account,), outputs=("address[]",)),
            Call(comptroller, "getAccountLiquidity(address)", args=(account,),
                 outputs=("uint256", "uint256", "uint256")),
        ],
        allow_failure=False,
    )
    vtokens = [to_checksum_address(a) for a in assets_res.value]
    _err, liquidity, shortfall = liq_res.decoded

    if not vtokens:
        return AccountHealth(account=account, markets=[], total_supply_usd=0.0,
                             total_borrow_usd=0.0, collateral_adjusted_usd=0.0,
                             liquidity_usd=liquidity / 1e18, shortfall_usd=shortfall / 1e18)

    calls: list[Call] = []
    for v in vtokens:
        calls += [
            Call(v, "symbol()", outputs=("string",), label=f"{v}:symbol"),
            Call(v, "underlying()", outputs=("address",), label=f"{v}:underlying"),
            Call(v, "exchangeRateStored()", outputs=("uint256",), label=f"{v}:exrate"),
            Call(v, "balanceOf(address)", args=(account,), outputs=("uint256",), label=f"{v}:bal"),
            Call(v, "borrowBalanceStored(address)", args=(account,), outputs=("uint256",),
                 label=f"{v}:borrow"),
            Call(comptroller, "markets(address)", args=(v,), outputs=("bool", "uint256"),
                 label=f"{v}:cf"),
            Call(oracle, "getUnderlyingPrice(address)", args=(v,), outputs=("uint256",),
                 label=f"{v}:price"),
        ]
    r = multicall(calls)
    by = {c.label: res for c, res in zip(calls, r, strict=True)}

    positions: list[MarketPosition] = []
    tot_supply = tot_borrow = tot_adj = 0.0
    for v in vtokens:
        underlying = by[f"{v}:underlying"].value if by[f"{v}:underlying"].success else None
        dec = 18
        if underlying:
            (d,) = multicall([Call(underlying, "decimals()", outputs=("uint8",))],
                             allow_failure=True)
            dec = int(d.value) if d.success else 18
        exrate = by[f"{v}:exrate"].value or 0
        vbal = by[f"{v}:bal"].value or 0
        borrow_raw = by[f"{v}:borrow"].value or 0
        price_raw = by[f"{v}:price"].value or 0      # scaled 1e(36 - dec)
        cf = (by[f"{v}:cf"].decoded[1] if by[f"{v}:cf"].success else 0) / 1e18

        supply_units_raw = vbal * exrate / 1e18       # underlying raw units
        supply_units = supply_units_raw / 10**dec
        borrow_units = borrow_raw / 10**dec
        price_usd = price_raw / 10 ** (36 - dec)
        supply_usd = supply_units * price_usd
        borrow_usd = borrow_units * price_usd

        positions.append(MarketPosition(
            vtoken=v, symbol=by[f"{v}:symbol"].value or v[:8],
            underlying_decimals=dec, supply_units=supply_units, borrow_units=borrow_units,
            price_usd=price_usd, collateral_factor=cf,
            supply_usd=supply_usd, borrow_usd=borrow_usd,
        ))
        tot_supply += supply_usd
        tot_borrow += borrow_usd
        tot_adj += supply_usd * cf

    return AccountHealth(
        account=account, markets=positions,
        total_supply_usd=tot_supply, total_borrow_usd=tot_borrow,
        collateral_adjusted_usd=tot_adj,
        liquidity_usd=liquidity / 1e18, shortfall_usd=shortfall / 1e18,
    )
