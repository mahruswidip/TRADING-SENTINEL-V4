import type { MarketDataSource } from "@/domain/market-data";

export function DataSourceBadge({ source, date }: { source: MarketDataSource; date?: string }) {
  const label = source === "FIXTURE" ? "DEVELOPMENT FIXTURE · NOT CURRENT MARKET DATA" : source === "BACKTEST" ? "REAL BACKTEST · BINANCE HISTORICAL" : source === "BINANCE_LIVE" ? "LIVE — BINANCE" : `HISTORICAL — BINANCE${date ? ` · ${date}` : ""}`;
  return <span className={`source-badge source-badge--${source.toLowerCase()}`}>{label}</span>;
}
