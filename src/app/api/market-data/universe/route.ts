import { NextResponse } from "next/server";
import { normalizeUniverse } from "@/lib/market-data";
import { fetchMarketDataBridge, isBridgeObject, MarketDataBridgeError } from "@/lib/market-data-bridge";

export async function GET(request: Request) {
  const { signal } = request;
  try {
    const [health, universe] = await Promise.all([
      fetchMarketDataBridge("/api/v1/market/health", undefined, signal),
      fetchMarketDataBridge("/api/v1/market/universe", undefined, signal),
    ]);
    if (!isBridgeObject(health) || health.status !== "ok" || !isBridgeObject(universe) || !Array.isArray(universe.symbols) || !Array.isArray(universe.tickers) || !Array.isArray(universe.books)) {
      throw new MarketDataBridgeError("MALFORMED_RESPONSE", 502, "Market-data bridge returned an invalid universe contract.");
    }
    const discoveredAt = typeof universe.serverTime === "number" ? universe.serverTime : Date.now();
    return NextResponse.json(normalizeUniverse({ symbols: universe.symbols }, universe.tickers, universe.books, discoveredAt));
  } catch (error) {
    if (error instanceof MarketDataBridgeError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    return NextResponse.json({ error: { code: "NETWORK", message: "Unable to reach the market-data bridge." } }, { status: 502 });
  }
}
