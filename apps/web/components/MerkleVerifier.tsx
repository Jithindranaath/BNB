"use client";

import { useMemo } from "react";
import { keccak_256 } from "@noble/hashes/sha3";

function hex(b: Uint8Array): string {
  return "0x" + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
function bytes(h: string): Uint8Array {
  const s = h.startsWith("0x") ? h.slice(2) : h;
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.slice(i * 2, i * 2 + 2), 16);
  return out;
}
function le(a: Uint8Array, b: Uint8Array): boolean {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] < b[i];
  }
  return true;
}

/** Re-folds the leaf with the proof in the browser and compares to the on-chain
 * root — the point is that you verify the hash, not the dashboard. */
export function MerkleVerifier({
  leaf,
  proof,
  root,
}: {
  leaf: string;
  proof: string[] | null;
  root: string | null;
}) {
  const result = useMemo(() => {
    if (!proof || !root) return null;
    let node = bytes(leaf);
    for (const p of proof) {
      const sib = bytes(p);
      const [x, y] = le(node, sib) ? [node, sib] : [sib, node];
      const cat = new Uint8Array(64);
      cat.set(x, 0);
      cat.set(y, 32);
      node = keccak_256(cat);
    }
    return { computed: hex(node), ok: hex(node) === root.toLowerCase() };
  }, [leaf, proof, root]);

  if (!result) {
    return <span className="text-xs text-neutral-400">verifier idle — batch this receipt first</span>;
  }
  return (
    <div className="text-xs">
      <div className="font-mono">recomputed root: {result.computed}</div>
      <div className={result.ok ? "mt-1 text-emerald-600" : "mt-1 text-red-600"}>
        {result.ok ? "✓ verified — recomputed root matches the anchored root" : "✗ mismatch"}
      </div>
    </div>
  );
}
