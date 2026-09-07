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
