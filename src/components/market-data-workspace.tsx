"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { DataSourceBadge } from "@/components/data-source-badge";
import { MarketChart } from "@/components/market-chart";
import { Panel } from "@/components/panel";
import { StatusPill, statusTone } from "@/components/status-pill";
import { binanceMarketData } from "@/data/binance-market-data-provider";
import type { MarketCandle, MarketDataSource, MarketTimeframe, ProviderState, UniverseSnapshot, UniverseSymbol, UniverseTier } from "@/domain/market-data";
import { isCurrentMarketResponse, isPrimaryUniverseSymbol, mergeMarketCandles } from "@/lib/market-data";

const timeframes = ["1D", "1H", "5M"] as const;
const tiers: readonly (UniverseTier | "ALL")[] = ["ALL", "A", "B", "C", "N", "UNCLASSIFIED"];
const priorUtcDate = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
const compactUsd = (value: number | null) => value === null ? "—" : new Intl.NumberFormat("en", { notation: "compact", style: "currency", currency: "USD", maximumFractionDigits: 1 }).format(value);
const decimal = (value: number | null, suffix = "") => value === null ? "—" : `${value.toFixed(2)}${suffix}`;
const messageOf = (error: unknown) => error instanceof Error ? error.message : "Unknown market-data error.";

export function MarketDataWorkspace() {
  const [universe, setUniverse] = useState<UniverseSnapshot | null>(null);
  const [universeState, setUniverseState] = useState<ProviderState>("LOADING");
  const [universeError, setUniverseError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [timeframe, setTimeframe] = useState<MarketTimeframe>("5M");
  const [mode, setMode] = useState<"LIVE" | "HISTORICAL">("LIVE");
  const [historicalDate, setHistoricalDate] = useState(priorUtcDate);
  const [series, setSeries] = useState<{ readonly symbol: string; readonly timeframe: MarketTimeframe; readonly candles: readonly MarketCandle[] }>({ symbol: "", timeframe: "5M", candles: [] });
  const candleRequestId = useRef(0);
  const liveRequestId = useRef(0);
  const [candleState, setCandleState] = useState<ProviderState>("LOADING");
  const [candleError, setCandleError] = useState<string | null>(null);
  const [candleWarnings, setCandleWarnings] = useState<readonly string[]>([]);
  const [liveState, setLiveState] = useState<ProviderState>("LOADING");
  const [liveMessage, setLiveMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [tier, setTier] = useState<UniverseTier | "ALL">("ALL");

  useEffect(() => {
    const controller = new AbortController();
    binanceMarketData.discoverUniverse(controller.signal).then((snapshot) => {
      setUniverse(snapshot);
      setUniverseState(snapshot.state);
      setSelectedSymbol((current) => current || [...snapshot.symbols].filter(isPrimaryUniverseSymbol).sort((left, right) => (right.marketQuality.volume24hUsd ?? 0) - (left.marketQuality.volume24hUsd ?? 0))[0]?.symbol || "");
    }).catch((error) => {
      if (controller.signal.aborted) return;
      setUniverseState("ERROR");
      setUniverseError(messageOf(error));
    });
    return () => controller.abort();
  }, [reloadToken]);

  useEffect(() => {
    if (!selectedSymbol) return;
    const requestId = ++candleRequestId.current;
    const controller = new AbortController();
    const endTime = mode === "HISTORICAL" ? Date.parse(`${historicalDate}T23:59:59.999Z`) : undefined;
    binanceMarketData.getCandles({ symbol: selectedSymbol, timeframe, endTime, limit: 300 }, controller.signal).then((snapshot) => {
      if (!isCurrentMarketResponse(selectedSymbol, timeframe, snapshot.symbol, snapshot.timeframe, requestId, candleRequestId.current)) return;
      setSeries({ symbol: snapshot.symbol, timeframe: snapshot.timeframe, candles: snapshot.candles });
      setCandleWarnings(snapshot.warnings);
      setCandleState(snapshot.state);
    }).catch((error) => {
      if (controller.signal.aborted || requestId !== candleRequestId.current) return;
      setCandleState("ERROR");
      setCandleError(messageOf(error));
    });
    return () => controller.abort();
  }, [historicalDate, mode, selectedSymbol, timeframe]);

  useEffect(() => {
    if (!selectedSymbol || mode !== "LIVE") return;
    const requestId = ++liveRequestId.current;
    let active = true;
    const subscription = binanceMarketData.subscribeCandles(selectedSymbol, timeframe, (update) => {
      if (!active || !isCurrentMarketResponse(selectedSymbol, timeframe, update.symbol, update.timeframe, requestId, liveRequestId.current)) return;
      setSeries((current) => current.symbol === selectedSymbol && current.timeframe === timeframe ? { ...current, candles: mergeMarketCandles(current.candles, [update.candle]) } : current);
      setLiveState("CONNECTED");
      setLiveMessage(null);
    }, (state, message) => { if (active) { setLiveState(state); setLiveMessage(message ?? null); } });
    return () => { active = false; subscription.close(); };
  }, [mode, selectedSymbol, timeframe]);

  const resetCandles = () => { candleRequestId.current++; liveRequestId.current++; setSeries({ symbol: "", timeframe, candles: [] }); setCandleState("LOADING"); setCandleError(null); setCandleWarnings([]); };
  const selectSymbol = (value: string) => { resetCandles(); setLiveState("LOADING"); setLiveMessage("Connecting to the selected Binance kline stream."); setSelectedSymbol(value); };
  const selectTimeframe = (value: MarketTimeframe) => { resetCandles(); setLiveState("LOADING"); setLiveMessage("Connecting to the selected Binance kline stream."); setTimeframe(value); };
  const selectMode = (value: "LIVE" | "HISTORICAL") => { resetCandles(); setLiveState("LOADING"); setLiveMessage(value === "LIVE" ? "Connecting to the selected Binance kline stream." : null); setMode(value); };

  const primarySymbols = useMemo(() => universe?.symbols.filter(isPrimaryUniverseSymbol) ?? [], [universe]);
  const filteredSymbols = useMemo(() => primarySymbols.filter((symbol) => (tier === "ALL" || symbol.marketQuality.tier === tier) && symbol.symbol.toLowerCase().includes(search.trim().toLowerCase())), [primarySymbols, search, tier]);
  const selectorSymbols = useMemo(() => selectedSymbol && !filteredSymbols.some((symbol) => symbol.symbol === selectedSymbol) ? [primarySymbols.find((symbol) => symbol.symbol === selectedSymbol), ...filteredSymbols].filter((symbol): symbol is UniverseSymbol => Boolean(symbol)) : filteredSymbols, [filteredSymbols, primarySymbols, selectedSymbol]);
  const selected = primarySymbols.find((symbol) => symbol.symbol === selectedSymbol) ?? null;
  const exclusions = universe?.symbols.filter((symbol) => !isPrimaryUniverseSymbol(symbol)) ?? [];
  const candles = series.symbol === selectedSymbol && series.timeframe === timeframe ? series.candles : [];
  const source: MarketDataSource = mode === "HISTORICAL" ? "BINANCE_HISTORICAL" : liveState === "CONNECTED" ? "BINANCE_LIVE" : "BINANCE_HISTORICAL";

  if (universeState === "LOADING" && !universe) return <div className="data-state data-state--loading">Discovering Binance USDⓈ-M contracts…</div>;
  if (universeError && !universe) return <div className="data-state data-state--error"><div><strong>MARKET DATA OFFLINE</strong><p>{universeError}</p><button onClick={() => { setUniverseState("LOADING"); setUniverseError(null); setReloadToken((value) => value + 1); }}>Retry market-data bridge</button></div></div>;
  if (!universe) return <div className="data-state">No universe data available.</div>;

  return <>
    <div className="universe-summary">
      <div><small>Market data</small><StatusPill label={universeState === "CONNECTED" ? "CONNECTED" : "OFFLINE"} tone={statusTone(universeState === "CONNECTED" ? "CONNECTED" : "OFFLINE")} /></div>
      {Object.entries({ Discovered: universe.summary.discovered, Trading: universe.summary.currentlyTrading, "Eligible perpetuals": universe.summary.eligiblePerpetuals, "Research-ready": universe.summary.researchEligible, "Execution-quality-ready": universe.summary.executionQualityReady, "New listings": universe.summary.newListings }).map(([label, value]) => <div key={label}><small>{label}</small><strong>{value.toLocaleString()}</strong></div>)}
    </div>

    <Panel title="Current / historical market" eyebrow="Read-only · public Binance data" action={<DataSourceBadge source={source} date={mode === "HISTORICAL" ? historicalDate : undefined} />} className="market-panel">
      <div className="market-toolbar">
        <label><span>Search symbols</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search discovered contracts…" /></label>
        <label><span>Symbol</span><select aria-label="Binance perpetual symbol" value={selectedSymbol} onChange={(event) => selectSymbol(event.target.value)}>{selectorSymbols.map((symbol) => <option key={symbol.symbol} value={symbol.symbol}>{symbol.symbol} · Tier {symbol.marketQuality.tier}</option>)}</select></label>
        <div className="market-filter"><span>Tier</span><div>{tiers.map((value) => <button key={value} className={tier === value ? "is-active" : ""} onClick={() => setTier(value)}>{value}</button>)}</div></div>
        <div className="market-filter"><span>Mode</span><div><button className={mode === "LIVE" ? "is-active" : ""} onClick={() => selectMode("LIVE")}>Current</button><button className={mode === "HISTORICAL" ? "is-active" : ""} onClick={() => selectMode("HISTORICAL")}>Historical</button></div></div>
        {mode === "HISTORICAL" && <label><span>UTC date</span><input type="date" max={new Date().toISOString().slice(0, 10)} value={historicalDate} onChange={(event) => { resetCandles(); setHistoricalDate(event.target.value); }} /></label>}
        <div className="timeframe-tabs" role="group" aria-label="Market chart timeframe">{timeframes.map((value) => <button key={value} className={timeframe === value ? "is-active" : ""} aria-pressed={timeframe === value} onClick={() => selectTimeframe(value)}>{value}</button>)}</div>
      </div>
      {selected && <div className="market-symbol-strip"><strong>{selected.symbol}</strong><span>{selected.baseAsset}/{selected.quoteAsset}</span><StatusPill label={`TIER ${selected.marketQuality.tier}`} tone={selected.marketQuality.tier === "A" ? "positive" : selected.marketQuality.tier === "N" ? "warning" : "info"} /><StatusPill label={selected.marketQuality.state} tone={statusTone(selected.marketQuality.state)} /><span>Bid {selected.quote.bidPrice?.toLocaleString() ?? "—"}</span><span>Ask {selected.quote.askPrice?.toLocaleString() ?? "—"}</span><span>24H {compactUsd(selected.marketQuality.volume24hUsd)}</span><span>Spread {decimal(selected.marketQuality.spreadBps, " bps")}</span><span>Top book {compactUsd(selected.marketQuality.topBookDepthUsd)}</span><span>Listed {selected.listingAgeDays.toLocaleString()}d</span></div>}
      <MarketChart symbol={selectedSymbol} timeframe={timeframe} candles={candles} />
      <div className="market-provider-status"><StatusPill label={candleState} tone={statusTone(candleState)} /><span>{candleError ?? (candleWarnings.join(" · ") || `${candles.length} normalized candles`)}</span>{mode === "LIVE" && <><StatusPill label={`STREAM ${liveState}`} tone={statusTone(liveState)} /><span>{liveMessage ?? "Selected-symbol stream active."}</span></>}</div>
    </Panel>

    <div className="universe-grid">
      <Panel title="Universe registry" eyebrow={`Showing ${filteredSymbols.length.toLocaleString()} dynamically discovered perpetuals`}>
        <div className="table-wrap"><table className="universe-table"><thead><tr><th>Symbol</th><th>Tier</th><th>Quality</th><th>24h volume</th><th>Spread</th><th>Depth</th><th>Age</th><th>Research</th><th>Future execution</th></tr></thead><tbody>{filteredSymbols.slice(0, 150).map((symbol) => <tr key={symbol.symbol}><td><strong>{symbol.symbol}</strong><small>{symbol.baseAsset}/{symbol.quoteAsset}</small></td><td>{symbol.marketQuality.tier}</td><td><StatusPill label={symbol.marketQuality.state} tone={statusTone(symbol.marketQuality.state)} /></td><td>{compactUsd(symbol.marketQuality.volume24hUsd)}</td><td>{decimal(symbol.marketQuality.spreadBps, " bps")}</td><td>{compactUsd(symbol.marketQuality.topBookDepthUsd)}</td><td>{symbol.listingAgeDays}d</td><td>{symbol.researchEligible ? "ELIGIBLE" : symbol.exclusionReasons.join(", ")}</td><td>{symbol.futureExecutionEligible ? "QUALITY READY" : "QUALITY GATED"}</td></tr>)}</tbody></table></div>
        {filteredSymbols.length > 150 && <p className="table-note">Showing first 150 matches. Narrow the dynamic registry with search or tier filters.</p>}
      </Panel>
      <Panel title="Integrity & exclusions" eyebrow="Provider-derived reasons"><div className="integrity-list"><div><strong>{universe.summary.insufficientHistory}</strong><span>Insufficient history</span></div><div><strong>{universe.summary.marketQualityWarnings}</strong><span>Market-quality warnings</span></div><div><strong>{universe.summary.unavailable}</strong><span>Unavailable / not trading</span></div></div><div className="exclusion-list">{exclusions.slice(0, 12).map((symbol) => <article key={symbol.symbol}><strong>{symbol.symbol}</strong><span>{symbol.exclusionReasons.join(" · ") || "MARKET_DATA_UNAVAILABLE"}</span></article>)}</div>{!exclusions.length && <p className="inline-empty">No excluded contracts reported.</p>}</Panel>
    </div>
  </>;
}
