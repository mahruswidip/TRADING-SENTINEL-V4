import { MarketDataWorkspace } from "@/components/market-data-workspace";
import { PageHeading } from "@/components/page-heading";

export default function DataSystemPage() {
  return <><PageHeading eyebrow="D2.5 public market data" title="Binance Universe & Market Data" description="Dynamic USDⓈ-M perpetual discovery, quality classification, and read-only candles. No account or execution access." /><MarketDataWorkspace /></>;
}
