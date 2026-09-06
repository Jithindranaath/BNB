// Probe: Binance klines (no auth). architecture.md §5.
// R5: print the real response before writing packages/data/sources/binance.py.
import { save, ok, blocked, main } from "./_util.ts";

const BASE = process.env.BINANCE_BASE_URL ?? "https://api.binance.com";
const url = `${BASE}/api/v3/klines?symbol=BNBUSDT&interval=1h&limit=5`;

main(async () => {
  console.log(`GET ${url}`);
  const res = await fetch(url);
  if (!res.ok) return blocked("binance_klines.json", url, `HTTP ${res.status} ${await res.text()}`);
  const rows = (await res.json()) as unknown[][];
  save("binance_klines.json", {
    url,
    note: "each row: [openTime, open, high, low, close, volume, closeTime, quoteVol, trades, takerBuyBase, takerBuyQuote, ignore]",
    rowCount: rows.length,
    sample: rows,
  });
  ok(`${rows.length} klines; first close = ${rows[0]?.[4]}, cols = ${rows[0]?.length}`);
});
