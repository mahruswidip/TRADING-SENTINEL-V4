"use client";

import { useEffect, useRef } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, createChart } from "lightweight-charts";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { MarketCandle, MarketTimeframe } from "@/domain/market-data";

export function MarketChart({ symbol, timeframe, candles }: { symbol: string; timeframe: MarketTimeframe; candles: readonly MarketCandle[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height: 500,
      layout: { background: { type: ColorType.Solid, color: "#090d12" }, textColor: "#83909d", attributionLogo: true },
      grid: { vertLines: { color: "#17212b" }, horzLines: { color: "#17212b" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#202b36" },
      timeScale: { borderColor: "#202b36", timeVisible: true, secondsVisible: false },
    });
    seriesRef.current = chart.addSeries(CandlestickSeries, { upColor: "#43d89b", downColor: "#ff667a", borderVisible: false, wickUpColor: "#43d89b", wickDownColor: "#ff667a" });
    chartRef.current = chart;
    return () => { chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !chartRef.current) return;
    seriesRef.current.setData(candles.map((candle) => ({ time: Math.floor(candle.openTime / 1000) as UTCTimestamp, open: candle.open, high: candle.high, low: candle.low, close: candle.close })));
    chartRef.current.timeScale().fitContent();
  }, [candles, symbol, timeframe]);

  return <div className="market-chart-shell">
    <div ref={containerRef} className="market-chart" aria-label={`${symbol} ${timeframe} Binance market chart`} />
    {!candles.length && <div className="replay-chart-empty">No market candles available.</div>}
  </div>;
}
