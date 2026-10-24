export type LibraryQuote = {
  symbol: string;
  price: number;
  change_pct: number | null;
  feed_origin: string;
  delayed: boolean;
  // ATLAS feed status fields (/api/catalog/quotes): live | delayed | market_closed | stale | no_data, source, Toronto time.
  status?: "live" | "delayed" | "market_closed" | "stale" | "no_data";
  source?: string | null;
  observed_at?: string | null;
  observed_at_toronto?: string | null;
  execution_permission: "none";
};

export function libraryQuoteSymbols(
  items: Array<{ symbol: string; exchange: string }>,
  selected = ""
): string[] {
  const eligible = (symbol: string, exchange: string) =>
    exchange !== "UNLISTED" && !/^EQ\d+$/.test(symbol) && !/^PERP\d+-USD$/.test(symbol);
  const window = items.filter((item) => eligible(item.symbol, item.exchange)).slice(-80).map((item) => item.symbol);
  if (selected && !window.includes(selected)) {
    const row = items.find((item) => item.symbol === selected);
    if (row && eligible(row.symbol, row.exchange)) window.unshift(selected);
  }
  return window.slice(0, 80);
}

export async function fetchLibraryQuotes(symbols: string[], signal?: AbortSignal): Promise<LibraryQuote[]> {
  const unique = [...new Set(symbols.map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))].slice(0, 80);
  if (unique.length === 0) return [];
  const quotes: LibraryQuote[] = [];
  for (let index = 0; index < unique.length; index += 40) {
    const batch = unique.slice(index, index + 40);
    const response = await fetch(`/api/catalog/quotes?symbols=${encodeURIComponent(batch.join(","))}`, {
      cache: "no-store",
      signal,
    });
    if (!response.ok) continue;
    const body = (await response.json()) as { quotes?: LibraryQuote[]; execution_permission?: string };
    if (body.execution_permission !== "none" || !Array.isArray(body.quotes)) continue;
    for (const row of body.quotes) {
      if (row && typeof row.price === "number" && row.price > 0 && row.execution_permission === "none") {
        quotes.push(row);
      }
    }
  }
  return quotes;
}
