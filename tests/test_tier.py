"""T-024: Tier 0 and Tier 1 cannot sign — by construction (spec.md §11.4)."""

from __future__ import annotations

import dataclasses

import pytest
from agents.base import ExecContext, TierViolation


class _FakeSigner:
    address = "0xdeadbeef"


@pytest.mark.parametrize("tier", [0, 1])
def test_low_tiers_never_hold_a_signer(tier):
    # even if a caller passes a signer, for_tier drops it
    ctx = ExecContext.for_tier(tier, signer=_FakeSigner())
    assert ctx.signer is None
    assert ctx.can_sign is False
    with pytest.raises(TierViolation):
        ctx.require_signer()


def test_execcontext_is_frozen():
    ctx = ExecContext.for_tier(0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.signer = _FakeSigner()  # frozen dataclass


def test_tier2_requires_a_signer_at_construction():
    with pytest.raises(TierViolation):
        ExecContext.for_tier(2, signer=None)

    signer = _FakeSigner()
    ctx = ExecContext.for_tier(2, signer=signer)
    assert ctx.can_sign is True
    assert ctx.require_signer() is signer


def test_bad_tier_rejected():
    with pytest.raises(ValueError):
        ExecContext.for_tier(3)
