"""Merkle-batches receipt leaves and anchors the root on-chain via
ReceiptAnchor.sol (architecture.md §12).

  create_batch()          -> group unbatched receipts, assign a batch_id
  submit_batch(w3, ..)    -> call ReceiptAnchor.anchor(batchId, root, count)
  proof_for(receipt_id)   -> (merkle_proof, anchor_root) for the /receipt page

A BSC-mainnet anchor needs ANCHOR_PRIVATE_KEY + RECEIPT_ANCHOR_ADDRESS in .env
(a low-value key that ONLY calls anchor()). scripts/anchor_receipts.py runs the
whole flow on the local anvil to prove it end to end without mainnet funds.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from eth_utils import keccak, to_checksum_address
from sqlalchemy import text

from . import db

_REPO = Path(__file__).resolve().parents[2]
ANCHOR_ABI = [
    {"name": "anchor", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "batchId", "type": "uint256"}, {"name": "root", "type": "bytes32"},
                {"name": "count", "type": "uint256"}], "outputs": []},
    {"name": "BatchAnchored", "type": "event", "anonymous": False, "inputs": [
        {"name": "batchId", "type": "uint256", "indexed": True},
        {"name": "root", "type": "bytes32", "indexed": False},
        {"name": "count", "type": "uint256", "indexed": False},
        {"name": "ts", "type": "uint256", "indexed": False}]},
]


def batch_id_to_uint(batch_id: str) -> int:
    return int.from_bytes(uuid.UUID(batch_id).bytes, "big")  # fits uint128


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
        if idx == len(level) - 1 and len(level) % 2 == 1:
            proof.append("0x" + level[idx].hex())          # odd tail — sibling is itself
        else:
            proof.append("0x" + level[idx ^ 1].hex())
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else a
            nxt.append(keccak(a + b if a <= b else b + a))
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


def batch_leaves(batch_id: str) -> list[str]:
    with db.session() as s:
        return [
            r[0] for r in s.execute(
                text("SELECT merkle_leaf FROM receipts WHERE batch_id = :b ORDER BY created_at, id"),
                {"b": batch_id},
            ).all()
        ]


def create_batch(*, min_size: int = 1) -> str | None:
    """Assign a fresh batch_id to every currently-unbatched receipt. Returns the
    batch_id, or None if there is nothing to batch."""
    with db.session() as s:
        n = s.execute(text("SELECT count(*) FROM receipts WHERE batch_id IS NULL")).scalar_one()
        if n < min_size:
            return None
        bid = str(uuid.uuid4())
        s.execute(text("UPDATE receipts SET batch_id = :b WHERE batch_id IS NULL"), {"b": bid})
        s.commit()
    return bid


def submit_batch(w3, account, anchor_address: str, batch_id: str) -> dict:
    """Call ReceiptAnchor.anchor(batchId, root, count). Records anchored_tx on the
    batch's receipts. `w3` is a connected Web3; `account` an unlocked address or
    a LocalAccount."""
    leaves = batch_leaves(batch_id)
    if not leaves:
        raise ValueError(f"batch {batch_id} has no receipts")
    root = merkle_root(leaves)
    c = w3.eth.contract(address=to_checksum_address(anchor_address), abi=ANCHOR_ABI)
    fn = c.functions.anchor(batch_id_to_uint(batch_id), bytes.fromhex(root[2:]), len(leaves))

    if hasattr(account, "key"):  # LocalAccount -> sign
        tx = fn.build_transaction({
            "from": account.address, "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 200_000, "gasPrice": w3.eth.gas_price,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        sender = account.address
    else:
        tx_hash = fn.transact({"from": account})
        sender = account

    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if rcpt["status"] != 1:
        raise RuntimeError(f"anchor() reverted (batch {batch_id})")
    tx_hex = rcpt["transactionHash"].hex()
    with db.session() as s:
        s.execute(text("UPDATE receipts SET anchored_tx = :t WHERE batch_id = :b"),
                  {"t": tx_hex, "b": batch_id})
        s.commit()
    return {"batch_id": batch_id, "root": root, "count": len(leaves),
            "tx": tx_hex, "block": rcpt["blockNumber"], "anchor": anchor_address, "sender": sender}


def verify_proof(leaf: str, proof: list[str], root: str) -> bool:
    """The exact fold the browser verifier does — sorted-pair keccak."""
    node = bytes.fromhex(leaf.removeprefix("0x"))
    for p in proof:
        sib = bytes.fromhex(p.removeprefix("0x"))
        node = keccak(node + sib) if node <= sib else keccak(sib + node)
    return ("0x" + node.hex()) == root
