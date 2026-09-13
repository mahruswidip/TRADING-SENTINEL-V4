"use client";

import { useEffect, useState } from "react";
import type { SystemHealth } from "@/domain/contracts";
import { Clock } from "@/components/clock";
import { StatusPill, statusTone } from "@/components/status-pill";

export function GlobalHeader({ system }: { system: SystemHealth }) {
  const [marketData, setMarketData] = useState<"CONNECTED" | "OFFLINE">("OFFLINE");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/market-data/health", { signal: controller.signal }).then(async (response) => {
      const payload: unknown = await response.json().catch(() => null);
      setMarketData(response.ok && typeof payload === "object" && payload !== null && "state" in payload && payload.state === "CONNECTED" ? "CONNECTED" : "OFFLINE");
    }).catch(() => { if (!controller.signal.aborted) setMarketData("OFFLINE"); });
    return () => controller.abort();
  }, []);
  return <header className="global-header"><div><p className="eyebrow">Operations console</p><h1>Trading Sentinel <span>V4</span></h1></div><div className="global-header__status"><div><small>SYSTEM</small><StatusPill label="MOCK" tone="neutral" /></div><div><small>MARKET DATA</small><StatusPill label={marketData} tone={statusTone(marketData)} /></div><div><small>ENVIRONMENT</small><StatusPill label={system.environment} tone="info" /></div><div><small>ENGINE</small><StatusPill label={system.engineStatus} tone={statusTone(system.engineStatus)} /></div><div><small>EXECUTION</small><StatusPill label={system.executionControl} tone="warning" /></div><Clock /></div></header>;
}
