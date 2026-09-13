type BridgeErrorCode = "NETWORK" | "RATE_LIMIT" | "MALFORMED_RESPONSE" | "UNAVAILABLE";

export class MarketDataBridgeError extends Error {
  constructor(readonly code: BridgeErrorCode, readonly status: number, message: string) {
    super(message);
    this.name = "MarketDataBridgeError";
  }
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

export async function fetchMarketDataBridge(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<unknown> {
  const configured = process.env.MARKET_DATA_BASE_URL?.trim();
  if (!configured) throw new MarketDataBridgeError("UNAVAILABLE", 503, "Market-data bridge is not configured.");
  const url = `${configured.replace(/\/$/, "")}${path}${params ? `?${params}` : ""}`;

  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000),
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = isObject(payload) && isObject(payload.detail) ? payload.detail : null;
      const code = response.status === 429 ? "RATE_LIMIT" : response.status === 404 || response.status === 409 || response.status === 422 ? "UNAVAILABLE" : "NETWORK";
      const message = detail && typeof detail.message === "string" ? detail.message : `Market-data bridge returned HTTP ${response.status}.`;
      throw new MarketDataBridgeError(code, response.status, message);
    }
    return payload;
  } catch (error) {
    if (error instanceof MarketDataBridgeError) throw error;
    throw new MarketDataBridgeError("NETWORK", 502, "Unable to reach the market-data bridge.");
  }
}

export const isBridgeObject = isObject;
