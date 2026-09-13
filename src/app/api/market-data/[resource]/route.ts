import { NextResponse } from "next/server";
import { fetchMarketDataBridge, MarketDataBridgeError } from "@/lib/market-data-bridge";

const resources = new Set(["ticker", "book", "funding", "open-interest"]);

export async function GET(request: Request, context: { params: Promise<{ resource: string }> }) {
  const { resource } = await context.params;
  const symbol = new URL(request.url).searchParams.get("symbol");
  if (!resources.has(resource)) return NextResponse.json({ error: { code: "UNAVAILABLE", message: "Unknown market-data resource." } }, { status: 404 });
  if (!symbol || !/^[A-Z0-9]{5,30}$/.test(symbol)) return NextResponse.json({ error: { code: "MALFORMED_RESPONSE", message: "Invalid symbol parameter." } }, { status: 400 });

  try {
    return NextResponse.json(await fetchMarketDataBridge(`/api/v1/market/${resource}`, new URLSearchParams({ symbol }), request.signal));
  } catch (error) {
    if (error instanceof MarketDataBridgeError) return NextResponse.json({ error: { code: error.code, message: error.message } }, { status: error.status });
    return NextResponse.json({ error: { code: "NETWORK", message: "Unable to reach the market-data bridge." } }, { status: 502 });
  }
}
