"""BSC RPC reads. **Every batch read goes through Multicall3 `aggregate3`** —
never loop single `eth_call`s (architecture.md §5). Second provider on failure.

Contract addresses come only from packages/data/reference (R1).
Calls are expressed as explicit `Call(target, "name(argtypes)", args, [out types])`
so there is no hidden ABI — the probe (scripts/probe/bsc_rpc_multicall.ts) uses
the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import function_signature_to_4byte_selector, to_checksum_address
from pydantic import BaseModel, ConfigDict
from web3 import Web3

from .. import reference
from ..settings import settings

_W3_CACHE: dict[str, Web3] = {}


def web3_client(url: str | None = None) -> Web3:
    url = url or settings().bsc_rpc_url
    if url not in _W3_CACHE:
        _W3_CACHE[url] = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
    return _W3_CACHE[url]


def _clients() -> list[Web3]:
    s = settings()
    urls = [s.bsc_rpc_url, s.bsc_rpc_url_fallback]
    return [web3_client(u) for u in dict.fromkeys(urls)]


# --- call model -------------------------------------------------------------

def _arg_types(signature: str) -> list[str]:
    inner = signature[signature.index("(") + 1 : signature.rindex(")")].strip()
    return [t.strip() for t in inner.split(",")] if inner else []


@dataclass(frozen=True)
class Call:
    target: str
    signature: str          # e.g. "balanceOf(address)" or "slot0()"
    args: tuple = ()
    outputs: tuple[str, ...] = ()   # e.g. ("uint256",) — omit to keep raw bytes
    label: str | None = None

    def calldata(self) -> bytes:
        selector = function_signature_to_4byte_selector(self.signature)
        types = _arg_types(self.signature)
        encoded = abi_encode(types, list(self.args)) if types else b""
        return selector + encoded


@dataclass
class Result:
    call: Call
    success: bool
    raw: bytes
    decoded: tuple | None = None

    @property
    def value(self) -> Any:
        """Single-output convenience."""
        if self.decoded is None:
            return None
        return self.decoded[0] if len(self.decoded) == 1 else self.decoded


_MULTICALL3_AGG3 = "aggregate3((address,bool,bytes)[])"


def multicall(calls: list[Call], *, allow_failure: bool = True, block: int | str = "latest") -> list[Result]:
    """One eth_call to Multicall3. The RPC call is retried across providers;
    ABI decode errors are raised straight away (they are bugs, not flakiness)."""
    mc = to_checksum_address(reference.contract("multicall3"))
    payload = [(to_checksum_address(c.target), allow_failure, c.calldata()) for c in calls]
    inner = abi_encode(["(address,bool,bytes)[]"], [payload])
    data = function_signature_to_4byte_selector(_MULTICALL3_AGG3) + inner

    last_err: Exception | None = None
    ret: bytes | None = None
    for w3 in _clients():
        try:
            ret = w3.eth.call({"to": mc, "data": data}, block_identifier=block)
            break
        except Exception as e:  # noqa: BLE001 - network/provider error -> try the next
            last_err = e
    if ret is None:
        raise RuntimeError(f"multicall eth_call failed on all providers: {last_err}")

    (rows,) = abi_decode(["(bool,bytes)[]"], ret)
    out: list[Result] = []
    for call, (ok, rb) in zip(calls, rows, strict=True):
        decoded = None
        if ok and call.outputs and rb:
            decoded = abi_decode(list(call.outputs), rb)
        out.append(Result(call=call, success=ok, raw=rb, decoded=decoded))
    return out


def block_number() -> int:
    return _clients()[0].eth.block_number


def gas_price_wei() -> int:
    return _clients()[0].eth.gas_price


# --- typed readers --------------------------------------------------------

class Erc20Meta(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: str
    symbol: str
    decimals: int


def erc20_metadata(addresses: list[str]) -> dict[str, Erc20Meta]:
    calls: list[Call] = []
    for a in addresses:
        calls.append(Call(a, "symbol()", outputs=("string",), label=f"{a}:symbol"))
        calls.append(Call(a, "decimals()", outputs=("uint8",), label=f"{a}:decimals"))
    res = multicall(calls)
    out: dict[str, Erc20Meta] = {}
    for i, a in enumerate(addresses):
        sym_r, dec_r = res[2 * i], res[2 * i + 1]
        if sym_r.success and dec_r.success:
            out[to_checksum_address(a)] = Erc20Meta(
                address=to_checksum_address(a),
                symbol=sym_r.value,
                decimals=int(dec_r.value),
            )
    return out


class PoolState(BaseModel):
    model_config = ConfigDict(frozen=True)

    pool: str
    token0: str
    token1: str
    fee: int
    tick_spacing: int
    liquidity: int
    sqrt_price_x96: int
    tick: int

    @property
    def price_token1_per_token0(self) -> Decimal:
        # (sqrtPriceX96 / 2**96) ** 2, before decimal adjustment
        r = Decimal(self.sqrt_price_x96) / Decimal(2**96)
        return r * r


# PancakeSwap v3 slot0 differs from Uniswap v3: feeProtocol is uint32 (packs the
# token0/token1 protocol fees into 32 bits), not uint8. Confirmed by decode.
_SLOT0_OUT = ("uint160", "int24", "uint16", "uint16", "uint16", "uint32", "bool")


def pancake_v3_pool_state(pool: str) -> PoolState:
    """slot0 + immutables + liquidity for a PancakeSwap v3 pool, in one multicall."""
    res = multicall(
        [
            Call(pool, "slot0()", outputs=_SLOT0_OUT, label="slot0"),
            Call(pool, "liquidity()", outputs=("uint128",), label="liquidity"),
            Call(pool, "token0()", outputs=("address",), label="token0"),
            Call(pool, "token1()", outputs=("address",), label="token1"),
            Call(pool, "fee()", outputs=("uint24",), label="fee"),
            Call(pool, "tickSpacing()", outputs=("int24",), label="tickSpacing"),
        ],
        allow_failure=False,
    )
    slot0 = res[0].decoded
    return PoolState(
        pool=to_checksum_address(pool),
        sqrt_price_x96=slot0[0],
        tick=slot0[1],
        liquidity=res[1].value,
        token0=to_checksum_address(res[2].value),
        token1=to_checksum_address(res[3].value),
        fee=res[4].value,
        tick_spacing=res[5].value,
    )
