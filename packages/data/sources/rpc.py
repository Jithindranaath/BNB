"""BSC RPC — live pool state, positions, Venus reads.
multicall3 for ANY batch read; never loop single calls. Second provider on 429s.
Addresses come ONLY from packages/data/reference/addresses.json (R1). Impl: T-010.
"""

from __future__ import annotations

RAISE = NotImplementedError("rpc source client lands in T-010 (probe first: T-003)")
