"""DefiLlama /pools, /chart/{pool} — TVL + APR history, independent cross-check.
No auth. 5 min TTL. Used for pcs-yield dilution_adjustment (TVL trend). Impl: T-010.
"""

from __future__ import annotations

RAISE = NotImplementedError("llama source client lands in T-010 (probe first: T-003)")
