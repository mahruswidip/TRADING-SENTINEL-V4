import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BinanceMarketDataProvider } from "../src/data/binance-market-data-provider.ts";
import { MarketDataProviderError } from "../src/domain/market-data.ts";
import { isCurrentMarketResponse, isPrimaryUniverseSymbol, mergeMarketCandles, normalizeKlines, normalizeLiveKline, normalizeUniverse, universeAt } from "../src/lib/market-data.ts";

const day = 86_400_000;
const now = Date.parse("2026-09-11T00:00:00Z");
const symbol = (name, overrides = {}) => ({
  symbol: name,
  baseAsset: name.replace(/USDT$|USDC$/, ""),
  quoteAsset: "USDT",
  marginAsset: "USDT",
  contractType: "PERPETUAL",
  status: "TRADING",
  onboardDate: now - 100 * day,
  deliveryDate: 4133404800000,
  pricePrecision: 4,
  quantityPrecision: 0,
  filters: [
    { filterType: "PRICE_FILTER", tickSize: "0.0001" },
    { filterType: "LOT_SIZE", stepSize: "1", minQty: "1", maxQty: "1000000" },
    { filterType: "MIN_NOTIONAL", notional: "5" },
  ],
  ...overrides,
});
const ticker = (name, quoteVolume = "250000000", priceChangePercent = "4") => ({ symbol: name, quoteVolume, priceChangePercent, lastPrice: "1.0002", closeTime: now });
const book = (name, bidPrice = "1", askPrice = "1.0005", bidQty = "100000", askQty = "100000") => ({ symbol: name, bidPrice, askPrice, bidQty, askQty, time: now });

test("dynamic universe accepts discovered non-major perpetuals without a symbol whitelist", () => {
  const names = ["ALPHAUSDT", "MEMEUSDT", "MICROUSDT"];
  const snapshot = normalizeUniverse({ symbols: names.map((name) => symbol(name)) }, names.map((name) => ticker(name)), names.map((name) => book(name)), now);
  assert.deepEqual(snapshot.symbols.filter(isPrimaryUniverseSymbol).map((item) => item.symbol), names);
  assert.equal(snapshot.summary.eligiblePerpetuals, 3);
  assert.equal(snapshot.symbols[0].quote.bidPrice, 1);
  assert.equal(snapshot.symbols[0].quote.executableBuyEstimate, 1.0005);
  assert.equal(snapshot.symbols[0].quote.markPrice, null);
  const source = ["src/lib/market-data.ts", "src/components/market-data-workspace.tsx"].map((file) => readFileSync(file, "utf8")).join("\n");
  assert.doesNotMatch(source, /\[\s*["']BTCUSDT["']/);
});

test("primary universe requires trading perpetual and compatible settlement", () => {
  const symbols = [
    symbol("VALIDUSDT"),
    symbol("QUARTERUSDT", { contractType: "CURRENT_QUARTER" }),
    symbol("HALTEDUSDT", { status: "SETTLING" }),
    symbol("WRONGUSD", { quoteAsset: "BUSD", marginAsset: "BUSD" }),
    symbol("VALIDUSDC", { quoteAsset: "USDC", marginAsset: "USDC" }),
  ];
  const snapshot = normalizeUniverse({ symbols }, symbols.map((item) => ticker(item.symbol)), symbols.map((item) => book(item.symbol)), now);
  assert.deepEqual(snapshot.symbols.filter(isPrimaryUniverseSymbol).map((item) => item.symbol), ["VALIDUSDC", "VALIDUSDT"]);
  assert.match(snapshot.symbols.find((item) => item.symbol === "QUARTERUSDT").exclusionReasons.join(), /NOT_PERPETUAL/);
});

test("historical Universe(t) respects onboard and delivery dates", () => {
  const onboardDate = now - 10 * day;
  const deliveryDate = now + 10 * day;
  const snapshot = normalizeUniverse({ symbols: [symbol("NEWUSDT", { onboardDate, deliveryDate })] }, [ticker("NEWUSDT")], [book("NEWUSDT")], now);
  assert.equal(universeAt(snapshot.symbols, onboardDate - 1).length, 0);
  assert.equal(universeAt(snapshot.symbols, onboardDate).length, 1);
  assert.equal(universeAt(snapshot.symbols, deliveryDate).length, 0);
});

test("market quality uses execution conditions and keeps new listings visible", () => {
  const snapshot = normalizeUniverse({ symbols: [symbol("NEWUSDT", { onboardDate: now - 2 * day }), symbol("THINUSDT")] }, [ticker("NEWUSDT"), ticker("THINUSDT")], [book("NEWUSDT"), book("THINUSDT", "1", "1.01", "10", "10")], now);
  const newlyListed = snapshot.symbols.find((item) => item.symbol === "NEWUSDT");
  const thin = snapshot.symbols.find((item) => item.symbol === "THINUSDT");
  assert.equal(newlyListed.marketQuality.tier, "N");
  assert.ok(isPrimaryUniverseSymbol(newlyListed));
  assert.match(newlyListed.marketQuality.flags.join(), /NEW_LISTING/);
  assert.match(thin.marketQuality.flags.join(), /THIN_MARKET|WIDE_SPREAD/);
});

test("ticker and book enrichment maps BTC quality without defaulting missing data to Tier C", () => {
  const complete = normalizeUniverse({ symbols: [symbol("BTCUSDT")] }, [ticker("BTCUSDT", "10000000000")], [book("BTCUSDT", "77000", "77001", "10", "8")], now).symbols[0];
  assert.equal(complete.quote.displayedPrice, 1.0002);
  assert.equal(complete.marketQuality.volume24hUsd, 10000000000);
  assert.equal(complete.quote.bidPrice, 77000);
  assert.equal(complete.quote.askPrice, 77001);
  assert.equal(complete.marketQuality.tier, "A");
  assert.ok(complete.marketQuality.spreadBps > 0);
  assert.ok(complete.marketQuality.topBookDepthUsd > 0);

  const missing = normalizeUniverse({ symbols: [symbol("MISSINGUSDT")] }, [], [], now).symbols[0];
  assert.equal(missing.marketQuality.state, "DATA_UNAVAILABLE");
  assert.equal(missing.marketQuality.tier, "UNCLASSIFIED");
});

test("bridge-shaped BTC candles normalize to realistic numeric OHLC", () => {
  const raw = { openTime: 1789113600000, open: "77188.20", high: "77230.00", low: "77141.00", close: "77141.00", volume: "213.047", closeTime: 1789113899999 };
  const normalized = normalizeKlines([[raw.openTime, raw.open, raw.high, raw.low, raw.close, raw.volume, raw.closeTime]], "5M", raw.closeTime + 1).candles[0];
  assert.deepEqual({ open: normalized.open, high: normalized.high, low: normalized.low, close: normalized.close }, { open: 77188.2, high: 77230, low: 77141, close: 77141 });
});

test("klines normalize, sort, deduplicate, validate, and expose gaps", () => {
  const row = (openTime, close, closeTime = openTime + 299999) => [openTime, "10", "12", "9", String(close), "100", closeTime, "0", 1, "0", "0", "0"];
  const result = normalizeKlines([row(600000, 11), row(0, 10), row(0, 10.5), ["bad"]], "5M", 1_000_000);
  assert.deepEqual(result.candles.map((candle) => candle.openTime), [0, 600000]);
  assert.equal(result.candles[0].close, 10.5);
  assert.match(result.warnings.join(), /malformed/);
  assert.match(result.warnings.join(), /gap/);
  const merged = mergeMarketCandles(result.candles, [{ ...result.candles[1], close: 12 }]);
  assert.equal(merged.length, 2);
  assert.equal(merged[1].close, 12);
  const preserved = mergeMarketCandles(merged, [{ ...merged[1], close: 8, updatedAt: merged[1].updatedAt - 1 }]);
  assert.equal(preserved[1].close, 12);
});

test("live public kline payload normalizes into the market contract", () => {
  const candle = normalizeLiveKline({ e: "kline", E: 300000, k: { t: 0, T: 299999, o: "10", h: "12", l: "9", c: "11", v: "100", x: true } }, "5M", 300000);
  assert.equal(candle.close, 11);
  assert.equal(candle.isClosed, true);
  assert.equal(candle.updatedAt, 300000);
});

test("provider surfaces public endpoint failures", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ error: { code: "RATE_LIMIT", message: "Binance public market data returned HTTP 429." } }), { status: 429 });
  try {
    await assert.rejects(new BinanceMarketDataProvider().discoverUniverse(), (error) => error instanceof MarketDataProviderError && error.code === "RATE_LIMIT");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("provider switches dynamic symbols and all required timeframes", async () => {
  const originalFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async (input) => {
    const url = String(input);
    urls.push(url);
    const searchParams = new URL(url, "http://localhost").searchParams;
    const symbol = searchParams.get("symbol") || "ALPHAUSDT";
    const timeframe = searchParams.get("timeframe") || "1D";
    return Response.json({
      symbol,
      timeframe,
      source: "BINANCE_HISTORICAL",
      asOf: Date.now(),
      state: "CONNECTED",
      candles: [{ openTime: 0, closeTime: 299999, open: 10, high: 12, low: 9, close: 11, volume: 100, isClosed: true, updatedAt: 299999 }],
      warnings: [],
    });
  };
  try {
    const provider = new BinanceMarketDataProvider();
    for (const [name, timeframe] of [["ALPHAUSDT", "1D"], ["MEMEUSDT", "1H"], ["MICROUSDT", "5M"]]) {
      const snapshot = await provider.getCandles({ symbol: name, timeframe, limit: 10 });
      assert.equal(snapshot.symbol, name);
      assert.equal(snapshot.source, "BINANCE_HISTORICAL");
    }
    for (const value of ["1D", "1H", "5M"]) assert.ok(urls.some((url) => url.includes(`timeframe=${value}`)));
    for (const name of ["ALPHAUSDT", "MEMEUSDT", "MICROUSDT"]) assert.ok(urls.some((url) => url.includes(`symbol=${name}`)));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("provider rejects stale wrong-symbol and wrong-timeframe responses", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ symbol: "OLDUSDT", timeframe: "1H", source: "BINANCE_HISTORICAL", asOf: now, state: "CONNECTED", candles: [], warnings: [] });
  try {
    await assert.rejects(new BinanceMarketDataProvider().getCandles({ symbol: "BTCUSDT", timeframe: "5M" }), (error) => error instanceof MarketDataProviderError && error.code === "MALFORMED_RESPONSE");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("old symbol, timeframe, and async generation can never mutate visible candles", () => {
  assert.equal(isCurrentMarketResponse("BTCUSDT", "5M", "BEATUSDT", "5M", 3, 3), false);
  assert.equal(isCurrentMarketResponse("BTCUSDT", "5M", "BTCUSDT", "1H", 3, 3), false);
  assert.equal(isCurrentMarketResponse("BTCUSDT", "5M", "BTCUSDT", "5M", 2, 3), false);
  assert.equal(isCurrentMarketResponse("BTCUSDT", "5M", "BTCUSDT", "5M", 3, 3), true);
  const workspace = readFileSync("src/components/market-data-workspace.tsx", "utf8");
  assert.match(workspace, /isCurrentMarketResponse/);
  assert.match(workspace, /series\.symbol === selectedSymbol && series\.timeframe === timeframe/);
});

test("UI consumes the provider and labels fixture versus Binance sources", () => {
  const workspace = readFileSync("src/components/market-data-workspace.tsx", "utf8");
  const chart = readFileSync("src/components/market-chart.tsx", "utf8");
  const badge = readFileSync("src/components/data-source-badge.tsx", "utf8");
  assert.match(workspace, /discoverUniverse/);
  assert.match(workspace, /type="search"/);
  assert.doesNotMatch(chart, /binance\.com|fetch\(|WebSocket/);
  assert.match(badge, /DEVELOPMENT FIXTURE · NOT CURRENT MARKET DATA/);
  assert.match(badge, /LIVE — BINANCE/);
  assert.match(badge, /HISTORICAL — BINANCE/);
});

test("D2.5 contains no authenticated Binance or execution functionality", () => {
  const source = ["src/data/binance-market-data-provider.ts", "src/components/market-data-workspace.tsx", "src/domain/market-data.ts", "src/app/api/market-data/universe/route.ts", "src/app/api/market-data/candles/route.ts"].map((file) => readFileSync(file, "utf8")).join("\n");
  assert.doesNotMatch(source, /X-MBX-APIKEY|signature=|listenKey|\/fapi\/v\d+\/order|\/account|change.*leverage/i);
  assert.doesNotMatch(source, /fapi\.binance\.com|fstream\.binance\.com|new WebSocket/);
  assert.match(readFileSync("src/lib/market-data-bridge.ts", "utf8"), /process\.env\.MARKET_DATA_BASE_URL/);
  assert.match(readFileSync("src/components/global-header.tsx", "utf8"), /MARKET DATA[\s\S]*marketData/);
});
