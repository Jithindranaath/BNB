// Probe: BscScan API — verified source + contract creation. architecture.md §5.
// Free key needed for reliable use; a keyless call is heavily rate-limited.
// Uses the Etherscan v2 multichain endpoint (chainid=56).
import { save, ok, blocked, main } from "./_util.ts";

const KEY = process.env.BSCSCAN_API_KEY ?? "";
const BASE = "https://api.etherscan.io/v2/api";
// PancakeV3Factory — known verified contract, from our reference data.
const TARGET = "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865";

async function call(params: Record<string, string>) {
  const u = new URL(BASE);
  u.searchParams.set("chainid", "56");
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  if (KEY) u.searchParams.set("apikey", KEY);
  const res = await fetch(u);
  const text = await res.text();
  try {
    return { httpStatus: res.status, json: JSON.parse(text) };
  } catch {
    return { httpStatus: res.status, raw: text.slice(0, 500) };
  }
}

main(async () => {
  if (!KEY) console.log("  (BSCSCAN_API_KEY unset — trying keyless; expect rate-limit / key-required)");

  const getsource = await call({ module: "contract", action: "getsourcecode", address: TARGET });
  const creation = await call({ module: "contract", action: "getcontractcreation", contractaddresses: TARGET });

  const srcRow = (getsource as any).json?.result?.[0];
  const looksOk =
    srcRow && typeof srcRow === "object" && "ContractName" in srcRow && srcRow.ABI !== "Contract source code not verified";

  save("bscscan_source.json", {
    endpoint: BASE,
    target: TARGET,
    hasKey: !!KEY,
    getsourcecode: {
      status: (getsource as any).json?.status,
      message: (getsource as any).json?.message,
      contractName: srcRow?.ContractName,
      compilerVersion: srcRow?.CompilerVersion,
      abiLength: typeof srcRow?.ABI === "string" ? srcRow.ABI.length : null,
      raw: looksOk ? "(ABI + source omitted for size)" : (getsource as any).json?.result,
    },
    getcontractcreation: (creation as any).json,
  });

  if (looksOk) ok(`verified source: ${srcRow.ContractName}, compiler ${srcRow.CompilerVersion}`);
  else
    blocked(
      "bscscan_source.json",
      "BscScan API (etherscan v2, chainid=56)",
      KEY ? `unexpected: ${JSON.stringify((getsource as any).json)?.slice(0, 200)}` : "needs BSCSCAN_API_KEY",
    );
});
