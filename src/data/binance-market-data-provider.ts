import type { CandleRequest, CandleSnapshot, LiveCandleUpdate, LiveSubscription, MarketDataProvider, MarketTimeframe, ProviderState, UniverseSnapshot } from "../domain/market-data.ts";
import { MarketDataProviderError } from "../domain/market-data.ts";

const universeTtlMs = 5 * 60_000;
const candleTtlMs = 15_000;

type CacheValue<T> = { readonly expiresAt: number; readonly value: T };

async function sameOriginJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new MarketDataProviderError("NETWORK", "Unable to reach Trading Sentinel market-data API.");
  }
  const payload = (await response.json().catch(() => null)) as unknown;
  const isObj = typeof payload === "object" && payload !== null;
  const err = isObj && "error" in payload && typeof payload.error === "object" && payload.error !== null ? (payload.error as { code?: string; message?: string }) : null;
  if (!response.ok) {
    const fallback = response.status === 429 ? "RATE_LIMIT" : response.status === 403 || response.status === 451 ? "UNAVAILABLE" : "NETWORK";
    const code = err?.code;
    throw new MarketDataProviderError(code === "RATE_LIMIT" || code === "MALFORMED_RESPONSE" || code === "UNAVAILABLE" ? code : fallback, err?.message ? err.message : `Market-data API returned HTTP ${response.status}.`);
  }
  if (!isObj) throw new MarketDataProviderError("MALFORMED_RESPONSE", "Market-data API returned invalid JSON.");
  return payload as T;
}

export class BinanceMarketDataProvider implements MarketDataProvider {
  private universeCache: CacheValue<UniverseSnapshot> | null = null;
  private universeRequest: Promise<UniverseSnapshot> | null = null;
  private candleCache = new Map<string, CacheValue<CandleSnapshot>>();
  private candleRequests = new Map<string, Promise<CandleSnapshot>>();

  async discoverUniverse(signal?: AbortSignal): Promise<UniverseSnapshot> {
    if (this.universeCache && this.universeCache.expiresAt > Date.now()) return this.universeCache.value;
    if (signal) return this.fetchUniverse(signal);
    if (this.universeRequest) return this.universeRequest;
    this.universeRequest = this.fetchUniverse().finally(() => { this.universeRequest = null; });
    return this.universeRequest;
  }

  private async fetchUniverse(signal?: AbortSignal): Promise<UniverseSnapshot> {
    const value = await sameOriginJson<UniverseSnapshot>("/api/market-data/universe", signal);
    this.universeCache = { value, expiresAt: Date.now() + universeTtlMs };
    return value;
  }

  async getCandles(request: CandleRequest, signal?: AbortSignal): Promise<CandleSnapshot> {
    const key = JSON.stringify(request);
    const cached = this.candleCache.get(key);
    if (cached && cached.expiresAt > Date.now()) return cached.value;
    if (signal) return this.fetchCandles(request, signal);
    const pending = this.candleRequests.get(key);
    if (pending) return pending;
    const promise = this.fetchCandles(request, signal).finally(() => { this.candleRequests.delete(key); });
    this.candleRequests.set(key, promise);
    return promise;
  }

  private async fetchCandles(request: CandleRequest, signal?: AbortSignal): Promise<CandleSnapshot> {
    const params = new URLSearchParams({ symbol: request.symbol, timeframe: request.timeframe, limit: String(request.limit ?? 500) });
    if (request.startTime !== undefined) params.set("startTime", String(request.startTime));
    if (request.endTime !== undefined) params.set("endTime", String(request.endTime));
    const value = await sameOriginJson<CandleSnapshot>(`/api/market-data/candles?${params}`, signal);
    if (value.symbol !== request.symbol || value.timeframe !== request.timeframe) throw new MarketDataProviderError("MALFORMED_RESPONSE", "Market-data response does not match the requested symbol and timeframe.");
    this.candleCache.set(JSON.stringify(request), { value, expiresAt: Date.now() + candleTtlMs });
    return value;
  }

  subscribeCandles(symbol: string, timeframe: MarketTimeframe, onUpdate: (update: LiveCandleUpdate) => void, onState: (state: ProviderState, message?: string) => void): LiveSubscription {
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const snapshot = await this.fetchCandles({ symbol, timeframe, limit: 2 });
        const candle = snapshot.candles.at(-1);
        if (!closed && candle) {
          onUpdate({ symbol, timeframe, source: "BINANCE_LIVE", receivedAt: Date.now(), candle });
          onState("CONNECTED");
        } else if (!closed) onState("DEGRADED", "No candle received for the selected symbol and timeframe.");
      } catch (error) {
        if (!closed) onState("ERROR", error instanceof Error ? error.message : "Market-data bridge polling failed.");
      }
      if (!closed) timer = setTimeout(poll, 5_000);
    };
    onState("LOADING", "Waiting for the next bridge market-data poll.");
    timer = setTimeout(poll, 5_000);
    return { close: () => { closed = true; clearTimeout(timer); } };
  }
}

export const binanceMarketData = new BinanceMarketDataProvider();
