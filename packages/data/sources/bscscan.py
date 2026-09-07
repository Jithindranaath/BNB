"""BscScan (via the Etherscan API V2 multichain endpoint, chainid=56).

Confirmed in T-003 (docs/findings/T-003.md):
  - getsourcecode / getabi  -> work on the free tier
  - getcontractcreation     -> NOT free for BSC ("upgrade your api plan")
  - the old api.bscscan.com V1 host is fully deprecated

Rate: Etherscan free tier is 5 req/s; we run at 4 (token bucket).
"""

from __future__ import annotations

import json as _json

from pydantic import BaseModel, ConfigDict

from ..settings import settings
from ._http import TokenBucket, get_json

_V2 = "https://api.etherscan.io/v2/api"
_BUCKET = TokenBucket(rate=4.0, capacity=4.0)


class ContractSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: str
    verified: bool
    contract_name: str | None = None
    compiler_version: str | None = None
    proxy: bool = False
    implementation: str | None = None
    abi: list | None = None
    source_code: str | None = None


class BscScanError(RuntimeError):
    pass


def _call(params: dict) -> dict:
    key = settings().bscscan_api_key
    if not key:
        raise BscScanError("BSCSCAN_API_KEY not set (see docs/findings/T-003.md)")
    _BUCKET.take()
    q = {"chainid": "56", "apikey": key, **params}
    return get_json(_V2, params=q)


def get_contract_source(address: str) -> ContractSource:
    """Verified source + ABI for a contract. `verified=False` when BscScan has no
    verified source (still a valid, useful answer for bsc-sentry)."""
    body = _call({"module": "contract", "action": "getsourcecode", "address": address})
    if body.get("status") != "1" or not body.get("result"):
        raise BscScanError(f"getsourcecode failed: {body.get('result') or body.get('message')}")
    row = body["result"][0]
    raw_abi = row.get("ABI", "")
    verified = raw_abi not in ("", "Contract source code not verified")
    return ContractSource(
        address=address,
        verified=verified,
        contract_name=row.get("ContractName") or None,
        compiler_version=row.get("CompilerVersion") or None,
        proxy=row.get("Proxy") == "1",
        implementation=row.get("Implementation") or None,
        abi=_json.loads(raw_abi) if verified else None,
        source_code=row.get("SourceCode") or None,
    )


def is_verified(address: str) -> bool:
    return get_contract_source(address).verified


def get_contract_creation(address: str) -> dict | None:
    """Creation tx + creator. Returns None when the API plan doesn't cover it on
    BSC (free tier) — callers must treat contract age as UNVERIFIED then (T-031)."""
    body = _call(
        {"module": "contract", "action": "getcontractcreation", "contractaddresses": address}
    )
    result = body.get("result")
    if isinstance(result, list) and result:
        return result[0]
    return None  # e.g. "Free API access is not supported for this chain"
