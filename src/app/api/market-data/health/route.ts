import { NextResponse } from "next/server";
import { fetchMarketDataBridge, isBridgeObject, MarketDataBridgeError } from "@/lib/market-data-bridge";

export async function GET(request: Request) {
  try {
    const [health, universe] = await Promise.all([
      fetchMarketDataBridge("/api/v1/market/health", undefined, request.signal),
      fetchMarketDataBridge("/api/v1/market/universe", undefined, request.signal),
    ]);
    if (!isBridgeObject(health) || health.status !== "ok" || !isBridgeObject(universe) || !Array.isArray(universe.symbols) || !Array.isArray(universe.tickers) || !Array.isArray(universe.books)) {
      throw new MarketDataBridgeError("MALFORMED_RESPONSE", 502, "Market-data bridge health contract is invalid.");
    }
    return NextResponse.json({ state: "CONNECTED", mode: health.mode, upstream: health.upstream, universeCount: universe.symbols.length });
  } catch (error) {
    const status = error instanceof MarketDataBridgeError ? error.status : 502;
    const message = error instanceof MarketDataBridgeError ? error.message : "Unable to reach the market-data bridge.";
    return NextResponse.json({ state: "OFFLINE", error: { code: error instanceof MarketDataBridgeError ? error.code : "NETWORK", message } }, { status });
  }
}
