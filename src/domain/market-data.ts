export type MarketTimeframe = "1D" | "1H" | "5M";
export type MarketDataSource = "FIXTURE" | "BACKTEST" | "BINANCE_HISTORICAL" | "BINANCE_LIVE";
export type ProviderState = "LOADING" | "CONNECTED" | "DEGRADED" | "ERROR";
export type UniverseTier = "A" | "B" | "C" | "N" | "UNCLASSIFIED";
export type MarketQualityState = "GOOD_MARKET" | "THIN_MARKET" | "WIDE_SPREAD" | "INSUFFICIENT_HISTORY" | "NEW_LISTING" | "EXTREME_VOLATILITY" | "DATA_UNAVAILABLE" | "UNAVAILABLE";
export type ExclusionReason = "NOT_TRADING" | "NOT_PERPETUAL" | "UNSUPPORTED_QUOTE_OR_MARGIN" | "INSUFFICIENT_HISTORY" | "MARKET_DATA_UNAVAILABLE";

export type MarketQuality = {
  readonly state: MarketQualityState;
  readonly tier: UniverseTier;
  readonly volume24hUsd: number | null;
  readonly spreadBps: number | null;
  readonly topBookDepthUsd: number | null;
  readonly volatility24hPct: number | null;
  readonly flags: readonly MarketQualityState[];
};

export type MarketQuote = {
  readonly displayedPrice: number | null;
  readonly markPrice: number | null;
  readonly bidPrice: number | null;
  readonly askPrice: number | null;
  readonly expectedPriceImpactBps: number | null;
  readonly executableBuyEstimate: number | null;
  readonly executableSellEstimate: number | null;
  readonly timestamp: number | null;
};

export type UniverseSymbol = {
  readonly symbol: string;
  readonly baseAsset: string;
  readonly quoteAsset: string;
  readonly marginAsset: string;
  readonly contractType: string;
  readonly tradingStatus: string;
  readonly onboardDate: number;
  readonly deliveryDate: number | null;
  readonly tickSize: number | null;
  readonly stepSize: number | null;
  readonly minQty: number | null;
  readonly maxQty: number | null;
  readonly minNotional: number | null;
  readonly pricePrecision: number | null;
  readonly quantityPrecision: number | null;
  readonly firstAvailableCandle: number | null;
  readonly lastAvailableCandle: number | null;
  readonly listingAgeDays: number;
  readonly quote: MarketQuote;
  readonly marketQuality: MarketQuality;
  readonly researchEligible: boolean;
  readonly futureExecutionEligible: boolean;
  readonly exclusionReasons: readonly ExclusionReason[];
};

export type UniverseSummary = {
  readonly discovered: number;
  readonly currentlyTrading: number;
  readonly eligiblePerpetuals: number;
  readonly researchEligible: number;
  readonly executionQualityReady: number;
  readonly insufficientHistory: number;
  readonly marketQualityWarnings: number;
  readonly newListings: number;
  readonly unavailable: number;
};

export type UniverseSnapshot = {
  readonly exchange: "BINANCE_USDS_M_FUTURES";
  readonly source: "BINANCE_LIVE";
  readonly discoveredAt: number;
  readonly state: ProviderState;
  readonly symbols: readonly UniverseSymbol[];
  readonly summary: UniverseSummary;
  readonly warnings: readonly string[];
};

export type MarketCandle = {
  readonly openTime: number;
  readonly closeTime: number;
  readonly open: number;
  readonly high: number;
  readonly low: number;
  readonly close: number;
  readonly volume: number;
  readonly isClosed: boolean;
  readonly updatedAt: number;
};

export type CandleRequest = {
  readonly symbol: string;
  readonly timeframe: MarketTimeframe;
  readonly startTime?: number;
  readonly endTime?: number;
  readonly limit?: number;
};

export type CandleSnapshot = {
  readonly symbol: string;
  readonly timeframe: MarketTimeframe;
  readonly source: "BINANCE_HISTORICAL";
  readonly asOf: number;
  readonly state: ProviderState;
  readonly candles: readonly MarketCandle[];
  readonly warnings: readonly string[];
};

export type LiveCandleUpdate = {
  readonly symbol: string;
  readonly timeframe: MarketTimeframe;
  readonly source: "BINANCE_LIVE";
  readonly receivedAt: number;
  readonly candle: MarketCandle;
};

export type LiveSubscription = { close(): void };

export interface MarketDataProvider {
  discoverUniverse(signal?: AbortSignal): Promise<UniverseSnapshot>;
  getCandles(request: CandleRequest, signal?: AbortSignal): Promise<CandleSnapshot>;
  subscribeCandles(symbol: string, timeframe: MarketTimeframe, onUpdate: (update: LiveCandleUpdate) => void, onState: (state: ProviderState, message?: string) => void): LiveSubscription;
}

export class MarketDataProviderError extends Error {
  readonly code: "NETWORK" | "RATE_LIMIT" | "MALFORMED_RESPONSE" | "UNAVAILABLE";

  constructor(code: "NETWORK" | "RATE_LIMIT" | "MALFORMED_RESPONSE" | "UNAVAILABLE", message: string) {
    super(message);
    this.code = code;
    this.name = "MarketDataProviderError";
  }
}
