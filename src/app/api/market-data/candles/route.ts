import { NextResponse } from "next/server";
import { normalizeKlines } from "@/lib/market-data";
import { MarketDataProviderError } from "@/domain/market-data";
import type { MarketTimeframe } from "@/domain/market-data";
import { fetchMarketDataBridge, isBridgeObject, MarketDataBridgeError } from "@/lib/market-data-bridge";

const interval: Record<MarketTimeframe, string> = { "1D": "1d", "1H": "1h", "5M": "5m" };

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol");
  const timeframe = searchParams.get("timeframe") as MarketTimeframe | null;
  const limitParam = searchParams.get("limit") ? Number(searchParams.get("limit")) : 300;

  if (!symbol || !/^[A-Z0-9]{5,30}$/.test(symbol) || !timeframe || !interval[timeframe] || !Number.isInteger(limitParam)) {
    return NextResponse.json({ error: { code: "MALFORMED_RESPONSE", message: "Invalid symbol or timeframe parameter." } }, { status: 400 });
  }
  if (searchParams.has("startTime") || searchParams.has("endTime")) {
    return NextResponse.json({ error: { code: "UNAVAILABLE", message: "The market-data bridge does not support candle time windows yet." } }, { status: 501 });
  }

  const requestedLimit = Math.max(1, Math.min(limitParam, 1_000));

  try {
    const params = new URLSearchParams({ symbol, interval: interval[timeframe], limit: String(requestedLimit) });
    const payload = await fetchMarketDataBridge("/api/v1/market/candles", params, request.signal);
    if (!isBridgeObject(payload) || payload.symbol !== symbol || payload.interval !== interval[timeframe] || !Array.isArray(payload.candles)) {
      throw new MarketDataBridgeError("MALFORMED_RESPONSE", 502, "Market-data bridge returned an invalid candle contract.");
    }
    const rows = payload.candles.map((candle) => isBridgeObject(candle)
      ? [candle.openTime, candle.open, candle.high, candle.low, candle.close, candle.volume, candle.closeTime]
      : candle);
    const asOf = Date.now();
    const normalized = normalizeKlines(rows, timeframe, asOf);
    if (!normalized.candles.length) {
      return NextResponse.json({ error: { code: "UNAVAILABLE", message: `No ${timeframe} candles are available for ${symbol}.` } }, { status: 404 });
    }

    return NextResponse.json({
      symbol,
      timeframe,
      source: "BINANCE_HISTORICAL",
      asOf,
      state: normalized.warnings.length ? "DEGRADED" : "CONNECTED",
      ...normalized,
    });
  } catch (error) {
    if (error instanceof MarketDataBridgeError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    }
    if (error instanceof MarketDataProviderError) {
      return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: 502 });
    }
    return NextResponse.json({ error: { code: "NETWORK", message: "Unable to reach the market-data bridge." } }, { status: 502 });
  }
}
