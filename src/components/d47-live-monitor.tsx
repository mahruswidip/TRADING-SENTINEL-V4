"use client";

import { useEffect, useRef, useState } from "react";
import type { D47MonitorSnapshot } from "@/data/d47-monitor";
import { Progress } from "@/components/progress";
import { StatusPill, statusTone } from "@/components/status-pill";

interface RateSample { processed: number; timestamp: number }

export function D47LiveMonitor({ initialSnapshot }: { initialSnapshot: D47MonitorSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [connection, setConnection] = useState<"LIVE" | "STALE">("LIVE");
  const [rate, setRate] = useState<number | null>(null);
  const sample = useRef<RateSample | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/api/research/d4-7", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const next = await response.json() as D47MonitorSnapshot;
        if (!active) return;
        const now = Date.now();
        if (sample.current) {
          const elapsedMinutes = (now - sample.current.timestamp) / 60_000;
          const delta = next.processed - sample.current.processed;
          if (delta > 0 && elapsedMinutes > 0) setRate(delta / elapsedMinutes);
        }
        sample.current = { processed: next.processed, timestamp: now };
        setSnapshot(next);
        setConnection("LIVE");
      } catch {
        if (active) setConnection("STALE");
      }
    };
    const timer = window.setInterval(refresh, 3_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const etaMinutes = rate && rate > 0 ? Math.ceil(snapshot.pending / rate) : null;
  const updated = new Date(snapshot.lastUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return <div className="d47-monitor">
    <div className="d47-monitor__headline">
      <div><strong>{snapshot.runId}</strong><span>Development-only signal replication · read-only monitor</span></div>
      <div className="panel-actions"><StatusPill label={connection} tone={connection === "LIVE" ? "positive" : "warning"} /><StatusPill label={snapshot.status} tone={statusTone(snapshot.status)} />{snapshot.finalDecision && <StatusPill label={snapshot.finalDecision} tone={statusTone(snapshot.finalDecision)} />}</div>
    </div>
    <Progress value={snapshot.progressPct} label={`${snapshot.processed} / ${snapshot.total} symbols accounted`} />
    <dl className="d47-monitor__metrics">
      <div><dt>Usable</dt><dd className="text-positive">{snapshot.completed}</dd></div>
      <div><dt>Failed</dt><dd className="text-negative">{snapshot.failed}</dd></div>
      <div><dt>Pending</dt><dd>{snapshot.pending}</dd></div>
      <div><dt>{snapshot.finalDecision ? "Final decision" : "Latest symbol"}</dt><dd>{snapshot.finalDecision ?? snapshot.latestSymbol ?? "—"}</dd></div>
      <div><dt>Throughput</dt><dd>{rate ? `${rate.toFixed(1)} sym/min` : "Measuring…"}</dd></div>
      <div><dt>ETA</dt><dd>{etaMinutes === null ? "Measuring…" : `${etaMinutes} min`}</dd></div>
      <div><dt>Configured workers</dt><dd>{snapshot.configuredWorkers}</dd></div>
      <div><dt>Updated</dt><dd>{updated}</dd></div>
    </dl>
    <div className="d47-monitor__footer"><span>Cache hits {snapshot.cacheHits.toLocaleString()} · Downloads {snapshot.downloads.toLocaleString()}</span><strong>{snapshot.oosAccess}</strong></div>
    {snapshot.recentFailures.length > 0 && <details className="d47-monitor__failures"><summary>Latest recorded failures ({snapshot.recentFailures.length})</summary>{snapshot.recentFailures.map((failure) => <div key={failure.symbol}><strong>{failure.symbol}</strong><span>{failure.status} · {failure.detail}</span></div>)}</details>}
  </div>;
}
