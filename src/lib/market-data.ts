import { MarketDataProviderError } from "../domain/market-data.ts";
import type { MarketCandle, MarketQuality, MarketQualityState, MarketQuote, MarketTimeframe, UniverseSnapshot, UniverseSymbol } from "../domain/market-data.ts";

type JsonObject = Record<string, unknown>;
const SUPPORTED_SETTLEMENT_ASSETS = new Set(["USDT", "USDC"]);
export const MARKET_INTERVAL_MS: Record<MarketTimeframe, number> = { "1D": 86_400_000, "1H": 3_600_000, "5M": 300_000 };

const isObject = (value: unknown): value is JsonObject => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => typeof value === "string" ? value : "";
const finite = (value: unknown): number | null => {
  const parsed = typeof value === "number" ? value : typeof value === "string" && value.trim() ? Number(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
};

export function isPrimaryUniverseSymbol(symbol: UniverseSymbol): boolean {
  return symbol.tradingStatus === "TRADING" && symbol.contractType === "PERPETUAL" && symbol.quoteAsset === symbol.marginAsset && SUPPORTED_SETTLEMENT_ASSETS.has(symbol.quoteAsset);
}

function filterValue(filters: unknown, type: string, key: string): number | null {
  if (!Array.isArray(filters)) return null;
  const filter = filters.find((item) => isObject(item) && item.filterType === type);
  return isObject(filter) ? finite(filter[key]) : null;
}

function qualityFor(symbol: JsonObject, ticker: JsonObject | undefined, book: JsonObject | undefined, now: number): MarketQuality {
  const onboardDate = finite(symbol.onboardDate) ?? now;
  const listingAgeDays = Math.max(0, Math.floor((now - onboardDate) / 86_400_000));
  const volume = ticker ? finite(ticker.quoteVolume) : null;
  const volatility = ticker ? finite(ticker.priceChangePercent) : null;
  const bid = book ? finite(book.bidPrice) : null;
  const ask = book ? finite(book.askPrice) : null;
  const bidQty = book ? finite(book.bidQty) : null;
  const askQty = book ? finite(book.askQty) : null;
  const updatedAt = book ? finite(book.time) : ticker ? finite(ticker.closeTime) : null;
  const midpoint = bid !== null && ask !== null ? (bid + ask) / 2 : null;
  const spreadBps = midpoint && midpoint > 0 && bid !== null && ask !== null ? ((ask - bid) / midpoint) * 10_000 : null;
  const topBookDepthUsd = bid !== null && ask !== null && bidQty !== null && askQty !== null ? bid * bidQty + ask * askQty : null;
  const qualityComplete = volume !== null && spreadBps !== null && topBookDepthUsd !== null && updatedAt !== null && now - updatedAt <= 120_000;
  const flags: MarketQualityState[] = [];
  if (!qualityComplete) flags.push("DATA_UNAVAILABLE");
  if (listingAgeDays < 7) flags.push("INSUFFICIENT_HISTORY");
  if (listingAgeDays < 30) flags.push("NEW_LISTING");
  if (spreadBps !== null && spreadBps > 25) flags.push("WIDE_SPREAD");
  if (topBookDepthUsd !== null && topBookDepthUsd < 50_000) flags.push("THIN_MARKET");
  if (volatility !== null && Math.abs(volatility) > 20) flags.push("EXTREME_VOLATILITY");
  const state = flags.find((flag) => flag !== "NEW_LISTING") ?? flags[0] ?? "GOOD_MARKET";
  const tier = !qualityComplete ? "UNCLASSIFIED" : listingAgeDays < 30 ? "N" : volume! >= 1_000_000_000 && spreadBps! <= 3 ? "A" : volume! >= 100_000_000 && spreadBps! <= 10 ? "B" : "C";
  return { state, tier, volume24hUsd: volume, spreadBps, topBookDepthUsd, volatility24hPct: volatility, flags };
}

function quoteFor(ticker: JsonObject | undefined, book: JsonObject | undefined): MarketQuote {
  const bidPrice = book ? finite(book.bidPrice) : null;
  const askPrice = book ? finite(book.askPrice) : null;
  return {
    displayedPrice: ticker ? finite(ticker.lastPrice) : null,
    markPrice: null,
    bidPrice,
    askPrice,
    expectedPriceImpactBps: null,
    executableBuyEstimate: askPrice,
    executableSellEstimate: bidPrice,
    timestamp: book ? finite(book.time) : ticker ? finite(ticker.closeTime) : null,
  };
}

export function normalizeUniverse(exchangeInfo: unknown, tickerPayload: unknown, bookPayload: unknown, now = Date.now()): UniverseSnapshot {
  if (!isObject(exchangeInfo) || !Array.isArray(exchangeInfo.symbols)) throw new MarketDataProviderError("MALFORMED_RESPONSE", "Binance exchange metadata is malformed.");
  const tickers = new Map((Array.isArray(tickerPayload) ? tickerPayload : []).filter(isObject).map((item) => [text(item.symbol), item]));
  const books = new Map((Array.isArray(bookPayload) ? bookPayload : []).filter(isObject).map((item) => [text(item.symbol), item]));

  const symbols = exchangeInfo.symbols.filter(isObject).map((item): UniverseSymbol => {
    const symbol = text(item.symbol);
    const quoteAsset = text(item.quoteAsset);
    const marginAsset = text(item.marginAsset);
    const tradingStatus = text(item.status || item.contractStatus);
    const contractType = text(item.contractType);
    const onboardDate = finite(item.onboardDate) ?? 0;
    const quality = qualityFor(item, tickers.get(symbol), books.get(symbol), now);
    const compatibleSettlement = quoteAsset === marginAsset && SUPPORTED_SETTLEMENT_ASSETS.has(quoteAsset);
    const exclusions = [] as UniverseSymbol["exclusionReasons"][number][];
    if (tradingStatus !== "TRADING") exclusions.push("NOT_TRADING");
    if (contractType !== "PERPETUAL") exclusions.push("NOT_PERPETUAL");
    if (!compatibleSettlement) exclusions.push("UNSUPPORTED_QUOTE_OR_MARGIN");
    if (quality.flags.includes("INSUFFICIENT_HISTORY")) exclusions.push("INSUFFICIENT_HISTORY");
    if (quality.flags.includes("DATA_UNAVAILABLE") || quality.flags.includes("UNAVAILABLE")) exclusions.push("MARKET_DATA_UNAVAILABLE");
    const primaryContract = tradingStatus === "TRADING" && contractType === "PERPETUAL" && compatibleSettlement;
    const researchEligible = primaryContract && onboardDate > 0 && !quality.flags.includes("INSUFFICIENT_HISTORY");
    const executionBlocks: readonly MarketQualityState[] = ["DATA_UNAVAILABLE", "UNAVAILABLE", "WIDE_SPREAD", "THIN_MARKET", "EXTREME_VOLATILITY", "INSUFFICIENT_HISTORY", "NEW_LISTING"];
    return {
      symbol,
      baseAsset: text(item.baseAsset),
      quoteAsset,
      marginAsset,
      contractType,
      tradingStatus,
      onboardDate,
      deliveryDate: finite(item.deliveryDate),
      tickSize: filterValue(item.filters, "PRICE_FILTER", "tickSize"),
      stepSize: filterValue(item.filters, "LOT_SIZE", "stepSize"),
      minQty: filterValue(item.filters, "LOT_SIZE", "minQty"),
      maxQty: filterValue(item.filters, "LOT_SIZE", "maxQty"),
      minNotional: filterValue(item.filters, "MIN_NOTIONAL", "notional"),
      pricePrecision: finite(item.pricePrecision),
      quantityPrecision: finite(item.quantityPrecision),
      firstAvailableCandle: null,
      lastAvailableCandle: null,
      listingAgeDays: Math.max(0, Math.floor((now - onboardDate) / 86_400_000)),
      quote: quoteFor(tickers.get(symbol), books.get(symbol)),
      marketQuality: quality,
      researchEligible,
      futureExecutionEligible: researchEligible && !quality.flags.some((flag) => executionBlocks.includes(flag)),
      exclusionReasons: exclusions,
    };
  }).sort((left, right) => left.symbol.localeCompare(right.symbol));

  const primary = symbols.filter(isPrimaryUniverseSymbol);
  const summary = {
    discovered: symbols.length,
    currentlyTrading: symbols.filter((item) => item.tradingStatus === "TRADING").length,
    eligiblePerpetuals: primary.length,
    researchEligible: symbols.filter((item) => item.researchEligible).length,
    executionQualityReady: symbols.filter((item) => item.futureExecutionEligible).length,
    insufficientHistory: primary.filter((item) => item.marketQuality.flags.includes("INSUFFICIENT_HISTORY")).length,
    marketQualityWarnings: primary.filter((item) => item.marketQuality.state !== "GOOD_MARKET").length,
    newListings: primary.filter((item) => item.marketQuality.flags.includes("NEW_LISTING")).length,
    unavailable: symbols.filter((item) => item.marketQuality.flags.includes("DATA_UNAVAILABLE") || item.marketQuality.flags.includes("UNAVAILABLE") || item.tradingStatus !== "TRADING").length,
  };
  return { exchange: "BINANCE_USDS_M_FUTURES", source: "BINANCE_LIVE", discoveredAt: now, state: "CONNECTED", symbols, summary, warnings: [] };
}

export function universeAt(symbols: readonly UniverseSymbol[], timestamp: number): readonly UniverseSymbol[] {
  return symbols.filter((symbol) => symbol.onboardDate <= timestamp && (symbol.deliveryDate === null || symbol.deliveryDate > timestamp));
}

export function normalizeKlines(payload: unknown, timeframe: MarketTimeframe, asOf = Date.now()): { candles: readonly MarketCandle[]; warnings: readonly string[] } {
  if (!Array.isArray(payload)) throw new MarketDataProviderError("MALFORMED_RESPONSE", "Binance candle response is malformed.");
  const deduped = new Map<number, MarketCandle>();
  let malformed = 0;
  for (const row of payload) {
    if (!Array.isArray(row) || row.length < 7) { malformed++; continue; }
    const [openTime, open, high, low, close, volume, closeTime] = row.map(finite);
    if ([openTime, open, high, low, close, volume, closeTime].some((value) => value === null) || high! < low! || open! < 0 || close! < 0 || volume! < 0) { malformed++; continue; }
    deduped.set(openTime!, { openTime: openTime!, closeTime: closeTime!, open: open!, high: high!, low: low!, close: close!, volume: volume!, isClosed: closeTime! <= asOf, updatedAt: closeTime! });
  }
  const candles = [...deduped.values()].sort((left, right) => left.openTime - right.openTime);
  let gaps = 0;
  const interval = MARKET_INTERVAL_MS[timeframe];
  for (let index = 1; index < candles.length; index++) if (candles[index].openTime - candles[index - 1].openTime > interval * 1.5) gaps++;
  const warnings = [...(malformed ? [`Ignored ${malformed} malformed candle row(s).`] : []), ...(gaps ? [`Detected ${gaps} candle gap(s).`] : [])];
  return { candles, warnings };
}

export function normalizeLiveKline(payload: unknown, timeframe: MarketTimeframe, receivedAt = Date.now()): MarketCandle {
  const root = isObject(payload) && isObject(payload.data) ? payload.data : payload;
  if (!isObject(root) || !isObject(root.k)) throw new MarketDataProviderError("MALFORMED_RESPONSE", "Binance live candle update is malformed.");
  const kline = root.k;
  const values = { openTime: finite(kline.t), closeTime: finite(kline.T), open: finite(kline.o), high: finite(kline.h), low: finite(kline.l), close: finite(kline.c), volume: finite(kline.v) };
  if (Object.values(values).some((value) => value === null) || values.high! < values.low!) throw new MarketDataProviderError("MALFORMED_RESPONSE", `Invalid ${timeframe} live candle values.`);
  return { openTime: values.openTime!, closeTime: values.closeTime!, open: values.open!, high: values.high!, low: values.low!, close: values.close!, volume: values.volume!, isClosed: kline.x === true || values.closeTime! <= receivedAt, updatedAt: finite(root.E) ?? receivedAt };
}

export function mergeMarketCandles(current: readonly MarketCandle[], incoming: readonly MarketCandle[], limit = 1_500): readonly MarketCandle[] {
  const byOpenTime = new Map(current.map((candle) => [candle.openTime, candle]));
  for (const candle of incoming) if ((byOpenTime.get(candle.openTime)?.updatedAt ?? -Infinity) <= candle.updatedAt) byOpenTime.set(candle.openTime, candle);
  return [...byOpenTime.values()].sort((left, right) => left.openTime - right.openTime).slice(-limit);
}

export function isCurrentMarketResponse(
  selectedSymbol: string,
  selectedTimeframe: MarketTimeframe,
  responseSymbol: string,
  responseTimeframe: MarketTimeframe,
  requestId: number,
  currentRequestId: number,
): boolean {
  return requestId === currentRequestId && responseSymbol === selectedSymbol && responseTimeframe === selectedTimeframe;
}
