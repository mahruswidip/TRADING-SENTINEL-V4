"use client";

import { useState } from "react";
import type { StrategyLifecycleStage, StrategyVersion } from "@/domain/contracts";
import { StatusPill, statusTone } from "@/components/status-pill";
import { plainPercent, usd } from "@/lib/format";

type SortKey = "strategy" | "version" | "family" | "direction" | "stage" | "dev" | "oos" | "walkForward" | "expectancy" | "profitFactor" | "maxDrawdown" | "trades" | "robustness" | "rejection";
type SortDirection = "asc" | "desc";
const columns: readonly [SortKey, string][] = [["strategy", "Strategy"], ["version", "Version"], ["family", "Family"], ["direction", "Direction"], ["stage", "Stage"], ["dev", "Dev"], ["oos", "OOS"], ["walkForward", "Walk Forward"], ["expectancy", "Net Expectancy"], ["profitFactor", "PF"], ["maxDrawdown", "Aggregate fixed-notional DD"], ["trades", "Trades"], ["robustness", "Robustness"], ["rejection", "Rejection Reason"]];

function sortValue(strategy: StrategyVersion, key: SortKey): string | number {
  const values: Record<SortKey, string | number> = {
    strategy: strategy.name, version: Number(strategy.strategyVersion.replace(/\D/g, "")), family: strategy.family ?? strategy.strategyId,
    direction: strategy.directionValidity ?? strategy.directionSupport, stage: strategy.lifecycle.stage, dev: strategy.devExpectancy ?? -Infinity,
    oos: strategy.oosExpectancy ?? -Infinity, walkForward: strategy.walkForwardExpectancy ?? -Infinity, expectancy: strategy.devExpectancy ?? -Infinity,
    profitFactor: strategy.metrics.profitFactor, maxDrawdown: strategy.metrics.maxDrawdownPct, trades: strategy.metrics.tradeCount,
    robustness: strategy.robustnessScore, rejection: strategy.rejectionReasons?.join(",") ?? "",
  };
  return values[key];
}

export function StrategyInventory({ strategies }: { strategies: readonly StrategyVersion[] }) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState<StrategyLifecycleStage | "ALL">("ALL");
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({ key: "robustness", direction: "desc" });
  const stages = [...new Set(strategies.map((strategy) => strategy.lifecycle.stage))];
  const rows = strategies.filter((strategy) => `${strategy.name} ${strategy.strategyId} ${strategy.strategyVersion} ${strategy.family ?? ""}`.toLowerCase().includes(query.toLowerCase()) && (stage === "ALL" || strategy.lifecycle.stage === stage)).sort((left, right) => {
    const a = sortValue(left, sort.key), b = sortValue(right, sort.key);
    const comparison = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
    return sort.direction === "asc" ? comparison : -comparison;
  });
  const changeSort = (key: SortKey) => setSort((current) => ({ key, direction: current.key === key && current.direction === "desc" ? "asc" : "desc" }));
  const expectancy = (value?: number) => value === undefined ? "—" : usd(value);

  return <><div className="inventory-toolbar"><label><span>Filter inventory</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Strategy, family, or version" /></label><label><span>Lifecycle stage</span><select value={stage} onChange={(event) => setStage(event.target.value as StrategyLifecycleStage | "ALL")}><option value="ALL">All stages</option>{stages.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label><small>{rows.length} of {strategies.length} artifacts</small></div>
    <div className="table-scroll"><table className="strategy-table"><thead><tr>{columns.map(([key, label]) => <th key={key} aria-sort={sort.key === key ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}><button onClick={() => changeSort(key)}>{label}{sort.key === key && <span>{sort.direction === "asc" ? " ↑" : " ↓"}</span>}</button></th>)}</tr></thead><tbody>{rows.map((strategy) => <tr key={`${strategy.strategyId}-${strategy.strategyVersion}`}><td><strong>{strategy.name}</strong><small>{strategy.source ?? "MOCK"}</small></td><td>{strategy.strategyVersion}</td><td>{strategy.family ?? strategy.strategyId}</td><td>{strategy.directionValidity ?? strategy.directionSupport}</td><td><StatusPill label={strategy.lifecycle.stage} tone={statusTone(strategy.lifecycle.stage)} /></td><td>{expectancy(strategy.devExpectancy)}</td><td>{expectancy(strategy.oosExpectancy)}</td><td>{expectancy(strategy.walkForwardExpectancy)}</td><td>{expectancy(strategy.devExpectancy)}</td><td>{strategy.metrics.profitFactor.toFixed(2)}</td><td>{plainPercent(strategy.metrics.maxDrawdownPct)}</td><td>{strategy.metrics.tradeCount}</td><td><strong>{strategy.robustnessScore}</strong></td><td><small>{strategy.rejectionReasons?.join(" · ") || "—"}</small></td></tr>)}</tbody></table></div>{!rows.length && <div className="inline-empty">No strategy artifacts match the current filters.</div>}</>;
}
