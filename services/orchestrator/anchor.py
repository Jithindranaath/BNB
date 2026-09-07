"""Merkle-batches receipt leaves and anchors the root on BSC via
ReceiptAnchor.sol (architecture.md §12). Full batching + on-chain submit lands in
T-062; `proof_for` is the read side the API needs now.
"""

from __future__ import annotations

from eth_utils import keccak
from sqlalchemy import text

from . import db


def _leaf_bytes(leaf_hex: str) -> bytes:
    return bytes.fromhex(leaf_hex.removeprefix("0x"))


def merkle_root(leaves: list[str]) -> str:
    """keccak Merkle root over the hex leaf strings (odd nodes promoted)."""
    if not leaves:
        return "0x" + "00" * 32
    level = [_leaf_bytes(x) for x in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else a
            nxt.append(keccak(a + b if a <= b else b + a))
        level = nxt
    return "0x" + level[0].hex()


def merkle_proof(leaves: list[str], index: int) -> list[str]:
    proof: list[str] = []
    level = [_leaf_bytes(x) for x in leaves]
    idx = index
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else a
            nxt.append(keccak(a + b if a <= b else b + a))
        sib = idx ^ 1
        if sib < len(level):
            proof.append("0x" + level[sib].hex())
        idx //= 2
        level = nxt
    return proof


def proof_for(receipt_id: str) -> tuple[list[str] | None, str | None]:
    """(merkle_proof, anchor_root) for a receipt, or (None, None) if unbatched."""
    with db.session() as s:
        row = s.execute(
            text("SELECT batch_id, merkle_leaf FROM receipts WHERE id = :id"),
            {"id": receipt_id},
        ).mappings().first()
        if not row or not row["batch_id"]:
            return None, None
        leaves = [
            r[0] for r in s.execute(
                text("SELECT merkle_leaf FROM receipts WHERE batch_id = :b ORDER BY created_at, id"),
                {"b": row["batch_id"]},
            ).all()
        ]
    try:
        idx = leaves.index(row["merkle_leaf"])
    except ValueError:
        return None, None
    return merkle_proof(leaves, idx), merkle_root(leaves)
