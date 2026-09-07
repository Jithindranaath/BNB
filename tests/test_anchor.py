"""T-062: merkle batching + proof verification (the fold matches the browser
verifier and ReceiptAnchor's sorted-pair convention).

The full deploy -> anchor() -> BatchAnchored -> proof flow is exercised by
scripts/anchor_receipts.py against the local anvil.
"""

from __future__ import annotations

import pytest
from eth_utils import keccak
from orchestrator.anchor import merkle_proof, merkle_root, verify_proof


def _leaves(n: int) -> list[str]:
    return ["0x" + keccak(text=f"receipt-{i}").hex() for i in range(n)]


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 13])
def test_every_leaf_proof_verifies_against_the_root(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        proof = merkle_proof(leaves, i)
        assert verify_proof(leaf, proof, root), f"leaf {i}/{n} failed"


def test_tampered_leaf_fails():
    leaves = _leaves(6)
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, 2)
    bad = "0x" + keccak(text="not-a-real-receipt").hex()
    assert verify_proof(bad, proof, root) is False


def test_single_leaf_root_is_the_leaf():
    (leaf,) = _leaves(1)
    assert merkle_root([leaf]) == leaf
    assert verify_proof(leaf, [], leaf) is True


def test_root_is_deterministic_but_pairing_order_matters():
    a = _leaves(5)
    assert merkle_root(a) == merkle_root(list(a))
    # re-pairing the leaves (not just swapping within a pair) changes the root
    assert merkle_root(a) != merkle_root([a[2], a[0], a[4], a[1], a[3]])
