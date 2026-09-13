"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, CrosshairMode, LineStyle, createChart, createSeriesMarkers } from "lightweight-charts";
import type { IChartApi, IPriceLine, ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";
import type { Candle, PriceRange, ReplayTimeframe, TradingEvent } from "@/domain/replay";

type RangeBox = { id: string; label: string; left: number; top: number; width: number; height: number; color: string };

function annotationColor(event: TradingEvent): string {
  if (event.type === "STOP_LOSS" || event.type === "INVALIDATION" || ("direction" in event && ["SHORT", "BEARISH"].includes(event.direction))) return "#ff667a";
  if (event.type === "TAKE_PROFIT" || event.type === "TRADE_CLOSED" || ("direction" in event && ["LONG", "BULLISH"].includes(event.direction))) return "#43d89b";
  if (event.type === "ENTRY_PLAN" || event.type === "ENTRY_TRIGGERED") return "#58a6ff";
  return "#f5b942";
}

function marker(event: TradingEvent): SeriesMarker<Time> | null {
  if (["LIQUIDITY", "FVG", "POI", "ENTRY_PLAN", "STOP_LOSS", "TAKE_PROFIT", "INVALIDATION"].includes(event.type)) return null;
  const bullish = "direction" in event && ["LONG", "BULLISH"].includes(event.direction);
  const bearish = "direction" in event && ["SHORT", "BEARISH"].includes(event.direction);
  return {
    time: event.timestamp as UTCTimestamp,
    position: bullish ? "belowBar" : "aboveBar",
    shape: bullish ? "arrowUp" : bearish ? "arrowDown" : "circle",
    color: annotationColor(event),
    text: event.label,
  };
}

export function ReplayChart({ timeframe, candles, annotations, currentTimestamp }: { timeframe: ReplayTimeframe; candles: readonly Candle[]; annotations: readonly TradingEvent[]; currentTimestamp: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const annotationsRef = useRef(annotations);
  const currentTimestampRef = useRef(currentTimestamp);
  const [rangeBoxes, setRangeBoxes] = useState<readonly RangeBox[]>([]);

  const updateRanges = useCallback(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    const boxes: RangeBox[] = [];
    for (const event of annotationsRef.current) {
      if (!("priceRange" in event)) continue;
      const range = event.priceRange as PriceRange;
      const left = chart.timeScale().timeToCoordinate(range.timeStart as UTCTimestamp);
      const right = chart.timeScale().timeToCoordinate((range.timeEnd ?? currentTimestampRef.current) as UTCTimestamp);
      const high = series.priceToCoordinate(range.priceHigh);
      const low = series.priceToCoordinate(range.priceLow);
      if (left === null || right === null || high === null || low === null) continue;
      boxes.push({ id: event.id, label: event.label, left: Math.min(left, right), top: Math.min(high, low), width: Math.max(Math.abs(right - left), 2), height: Math.max(Math.abs(low - high), 2), color: annotationColor(event) });
    }
    setRangeBoxes(boxes);
  }, []);

  useEffect(() => {
    annotationsRef.current = annotations;
    currentTimestampRef.current = currentTimestamp;
    queueMicrotask(updateRanges);
  }, [annotations, currentTimestamp, updateRanges]);

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
    const series = chart.addSeries(CandlestickSeries, { upColor: "#43d89b", downColor: "#ff667a", borderVisible: false, wickUpColor: "#43d89b", wickDownColor: "#ff667a" });
    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    chart.timeScale().subscribeVisibleTimeRangeChange(updateRanges);
    const resizeObserver = new ResizeObserver(updateRanges);
    resizeObserver.observe(containerRef.current);
    return () => {
      resizeObserver.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateRanges);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
    };
  }, [updateRanges]);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;
    series.setData(candles.map((candle) => ({ ...candle, time: candle.timestamp as UTCTimestamp })));
    chart.timeScale().fitContent();
    queueMicrotask(updateRanges);
  }, [candles, timeframe, updateRanges]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    markersRef.current?.setMarkers(annotations.map(marker).filter((item): item is SeriesMarker<Time> => item !== null).sort((left, right) => Number(left.time) - Number(right.time)));
    for (const line of priceLinesRef.current) series.removePriceLine(line);
    priceLinesRef.current = annotations.flatMap((event) => {
      const price = "price" in event ? event.price : undefined;
      if (!["ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT"].includes(event.type) || price === undefined) return [];
      return [series.createPriceLine({ price, color: annotationColor(event), lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: event.label })];
    });
    queueMicrotask(updateRanges);
  }, [annotations, updateRanges]);

  return <div className="replay-chart-shell">
    <div ref={containerRef} className="replay-chart" aria-label={`${timeframe} candlestick chart`} />
    <div className="replay-ranges" aria-hidden="true">{rangeBoxes.map((box) => <div key={box.id} className="replay-range" style={{ left: box.left, top: box.top, width: box.width, height: box.height, borderColor: box.color, backgroundColor: `${box.color}18` }}><span style={{ color: box.color }}>{box.label}</span></div>)}</div>
    {!candles.length && <div className="replay-chart-empty">No candles are visible at this replay timestamp.</div>}
  </div>;
}
