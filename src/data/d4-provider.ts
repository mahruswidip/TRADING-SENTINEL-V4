import { promises as fs } from "node:fs";
import path from "node:path";
import type { ResearchRun, StrategyVersion } from "@/domain/contracts";

const stateRoot = path.join(process.cwd(), "state");

export interface DevelopmentExpansionRun {
  runId: string;
  status: string;
  stage: string;
  developmentWindow: { start: number; end: number };
  symbolCount: number;
  oosAccess: "OOS_NOT_ACCESSED";
  candidates: readonly {
    strategy: string;
    status: string;
    passed: boolean;
    metrics: { trade_count: number; expectancy: number; profit_factor: number; max_drawdown: number };
    breadth: { top_symbol_pnl_share: number };
    cost_stress: Record<string, number>;
  }[];
}

interface ReferenceEquitySummary {
  aggregate_normalized_net_return_pct: number;
  portfolio_equity_return_pct: number;
  portfolio_max_drawdown_pct: number;
  starting_equity: number;
  ending_equity: number;
  bankrupt: boolean;
}

export interface AccountingAudit {
  auditId: string;
  sourceRunId: string;
  finding: string;
  decision: string;
  oosAccess: "OOS_NOT_ACCESSED";
  v3Created: false;
  referenceEquity: Readonly<Record<string, ReferenceEquitySummary>>;
}

export interface D44ResearchRun {
  runId: string;
  status: string;
  gateStatus: string;
  oosAccess: "OOS_NOT_ACCESSED";
  triage: readonly {
    family: string;
    decision: string;
    grossExpectancy: number;
    netExpectancy: number;
  }[];
  fvg: {
    metrics: { trade_count: number; expectancy: number; profit_factor: number; max_drawdown: number; LONG: { trade_count: number; expectancy: number; profit_factor: number }; SHORT: { trade_count: number; expectancy: number; profit_factor: number }; reference_equity: { portfolio_equity_return_pct: number; portfolio_max_drawdown_pct: number } };
    funnel: { fvgs_formed: number; fvgs_touched: number; confirmations: number; entries: number; rejected_entries: number };
    failedGates: readonly string[];
    costStress: Readonly<Record<string, number>>;
  };
}

export interface D45SignalDiscovery {
  runId: string;
  status: string;
  oosAccess: "OOS_NOT_ACCESSED";
  featureCatalogCount: number;
  availableFeatureCount: number;
  horizons: readonly string[];
  observationCount: number;
  effectiveObservationCounts: Readonly<Record<string, number>>;
  symbolCount: number;
  promisingSignalCount: number;
  findings: readonly {
    findingId: string;
    feature: string;
    bucket: string;
    horizon: string;
    direction: "POSITIVE" | "NEGATIVE";
    effectBps: number;
    effectiveSample: number;
    symbolCount: number;
    temporalClassification: string;
    discoveryStatus: string;
  }[];
}

export interface D46SignalReplication {
  milestone: "D4.6" | "D4.6B";
  runId: string;
  status: string;
  sourceRun: string;
  latestStage: string;
  decision: string;
  usableSymbolCount: number;
  eligibleUniverseCount: number;
  costHurdleBps: number;
  oosAccess: "OOS_NOT_ACCESSED";
  signals: readonly {
    signalId: "A" | "B";
    sourceFindingId: string;
    status: string;
    expectedDirection: "POSITIVE" | "NEGATIVE";
    effectBps: number;
    medianEffectBps: number;
    directionalHitRate: number;
    costHurdleStatus: string;
    rawSample: number;
    effectiveSample: number;
    symbolCount: number;
    profitableSymbolCount: number;
    topSymbolContribution: number;
    temporalClassification: string;
  }[];
}

export async function getD4Strategies(): Promise<readonly StrategyVersion[]> {
  try {
    const [latest, d44] = await Promise.all([getLatestResearchRun(), getLatestD44Run()]);
    const families = await fs.readdir(path.join(stateRoot, "research"));
    const values = await Promise.all(families.map(async (family) => {
      const root = path.join(stateRoot, "research", family);
      const runs = await fs.readdir(root);
      return Promise.all(runs.map(async (run) => {
        try { return JSON.parse(await fs.readFile(path.join(root, run, "strategy.json"), "utf8")) as StrategyVersion; }
        catch { return null; }
      }));
    }));
    return values.flat()
      .filter((value): value is StrategyVersion => value !== null)
      .filter((value) => value.strategyId === "FVG_PULLBACK" ? value.researchRunId === d44?.runId : !latest || value.researchRunId === latest.runId)
      .sort((left, right) => right.robustnessScore - left.robustnessScore || left.strategyId.localeCompare(right.strategyId));
  } catch { return []; }
}

export async function getLatestResearchRun(): Promise<ResearchRun | null> {
  try {
    const root = path.join(stateRoot, "research-runs");
    const runs = await fs.readdir(root);
    const values = await Promise.all(runs.map(async (run) => {
      try { return JSON.parse(await fs.readFile(path.join(root, run, "research-run.json"), "utf8")) as ResearchRun; }
      catch { return null; }
    }));
    return values.filter((value): value is ResearchRun => value !== null).sort((left, right) => right.startedAt.localeCompare(left.startedAt))[0] ?? null;
  } catch { return null; }
}

export async function getLatestDevelopmentExpansion(): Promise<DevelopmentExpansionRun | null> {
  try {
    const root = path.join(stateRoot, "research-runs");
    const runs = (await fs.readdir(root)).filter((run) => run.startsWith("d4_2_"));
    const values = await Promise.all(runs.map(async (run) => {
      try { return JSON.parse(await fs.readFile(path.join(root, run, "expansion-run.json"), "utf8")) as DevelopmentExpansionRun; }
      catch { return null; }
    }));
    return values.filter((value): value is DevelopmentExpansionRun => value !== null).sort((left, right) => right.runId.localeCompare(left.runId))[0] ?? null;
  } catch { return null; }
}

export async function getLatestAccountingAudit(): Promise<AccountingAudit | null> {
  try {
    const root = path.join(stateRoot, "accounting-audit");
    const runs = await fs.readdir(root);
    const candidates = await Promise.all(runs.map(async (run) => {
      const runRoot = path.join(root, run);
      try {
        const [audit, semantics, stat] = await Promise.all([
          fs.readFile(path.join(runRoot, "accounting-audit.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, "equity-semantics.json"), "utf8").then(JSON.parse),
          fs.stat(path.join(runRoot, "accounting-audit.json")),
        ]);
        return {
          modifiedAt: stat.mtimeMs,
          value: {
            auditId: audit.audit_id,
            sourceRunId: audit.source_d4_2_run_id,
            finding: audit.finding,
            decision: audit.breakout_regime_decision,
            oosAccess: audit.oos_access,
            v3Created: audit.v3_created,
            referenceEquity: semantics.reference_portfolio_equity,
          } as AccountingAudit,
        };
      } catch { return null; }
    }));
    return candidates.filter((item): item is NonNullable<typeof item> => item !== null).sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.value ?? null;
  } catch { return null; }
}

export async function getLatestD44Run(): Promise<D44ResearchRun | null> {
  try {
    const runsRoot = path.join(stateRoot, "research-runs");
    const folders = (await fs.readdir(runsRoot)).filter((item) => item.startsWith("d4_4_"));
    const completed = await Promise.all(folders.map(async (folder) => {
      try {
        const runPath = path.join(runsRoot, folder, "d4.4-run.json");
        const [run, stat] = await Promise.all([fs.readFile(runPath, "utf8").then(JSON.parse), fs.stat(runPath)]);
        return { run, modifiedAt: stat.mtimeMs };
      } catch { return null; }
    }));
    const selected = completed.filter((item): item is NonNullable<typeof item> => item !== null).sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.run;
    if (!selected) return null;
    const researchRoot = path.join(stateRoot, "research", "FVG_PULLBACK_V1", selected.runId);
    const triageRoot = path.join(stateRoot, "triage", selected.triageId);
    const [summary, funnel, gates, stress, triage] = await Promise.all([
      fs.readFile(path.join(researchRoot, "dev-summary.json"), "utf8").then(JSON.parse),
      fs.readFile(path.join(researchRoot, "fvg-funnel.json"), "utf8").then(JSON.parse),
      fs.readFile(path.join(researchRoot, "gate-result.json"), "utf8").then(JSON.parse),
      fs.readFile(path.join(researchRoot, "cost-stress.json"), "utf8").then(JSON.parse),
      fs.readFile(path.join(triageRoot, "remaining-families.json"), "utf8").then(JSON.parse),
    ]);
    return {
      runId: selected.runId,
      status: selected.status,
      gateStatus: selected.fvgGateStatus,
      oosAccess: selected.oosAccess,
      triage: triage.families.map((item: { family: string; decision: string; gross_expectancy: number; net_expectancy: number }) => ({ family: item.family, decision: item.decision, grossExpectancy: item.gross_expectancy, netExpectancy: item.net_expectancy })),
      fvg: {
        metrics: summary,
        funnel,
        failedGates: Object.entries(gates.gates).filter(([, passed]) => !passed).map(([name]) => name),
        costStress: Object.fromEntries(Object.entries(stress).map(([name, value]) => [name, (value as { metrics: { expectancy: number } }).metrics.expectancy])),
      },
    };
  } catch { return null; }
}

export async function getLatestD45Discovery(): Promise<D45SignalDiscovery | null> {
  try {
    const root = path.join(stateRoot, "signal-discovery");
    const folders = (await fs.readdir(root)).filter((item) => item.startsWith("d4_5_"));
    const completed = await Promise.all(folders.map(async (folder) => {
      try {
        const runRoot = path.join(root, folder);
        const [manifest, plan, ranking, stat] = await Promise.all([
          fs.readFile(path.join(runRoot, "manifest.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, "resource-plan.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, "discovery-ranking.json"), "utf8").then(JSON.parse),
          fs.stat(path.join(runRoot, "manifest.json")),
        ]);
        const findings = (ranking.ranked_findings as readonly {
          finding_id: string; feature: string; bucket: string; horizon: string; direction: "POSITIVE" | "NEGATIVE";
          mean_forward_return: number; effective_observation_count: number; symbol_count: number; temporal_classification: string; discovery_status: string;
        }[]).filter((item) => item.discovery_status === "PROMISING_SIGNAL").slice(0, 5);
        return {
          modifiedAt: stat.mtimeMs,
          value: {
            runId: manifest.run_id, status: manifest.status, oosAccess: manifest.oos_access,
            featureCatalogCount: plan.feature_catalog_count, availableFeatureCount: plan.available_feature_count,
            horizons: manifest.horizons, observationCount: manifest.observation_count,
            effectiveObservationCounts: manifest.effective_observation_counts, symbolCount: manifest.symbols.length,
            promisingSignalCount: ranking.status_counts.PROMISING_SIGNAL ?? 0,
            findings: findings.map((item) => ({ findingId: item.finding_id, feature: item.feature, bucket: item.bucket, horizon: item.horizon, direction: item.direction, effectBps: item.mean_forward_return * 10_000, effectiveSample: item.effective_observation_count, symbolCount: item.symbol_count, temporalClassification: item.temporal_classification, discoveryStatus: item.discovery_status })),
          } as D45SignalDiscovery,
        };
      } catch { return null; }
    }));
    return completed.filter((item): item is NonNullable<typeof item> => item !== null).sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.value ?? null;
  } catch { return null; }
}

export async function getLatestD46Replication(): Promise<D46SignalReplication | null> {
  try {
    const root = path.join(stateRoot, "signal-replication");
    const folders = (await fs.readdir(root)).filter((item) => item.startsWith("d4_6_") || item.startsWith("d4_6b_"));
    const completed = await Promise.all(folders.map(async (folder) => {
      try {
        const runRoot = path.join(root, folder);
        const broader = folder.startsWith("d4_6b_");
        const [manifest, gate, signalA, signalB, stat] = await Promise.all([
          fs.readFile(path.join(runRoot, "manifest.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, "replication-gate.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, broader ? "signal-a.json" : "signal-a-replication.json"), "utf8").then(JSON.parse),
          fs.readFile(path.join(runRoot, broader ? "signal-b.json" : "signal-b-replication.json"), "utf8").then(JSON.parse),
          fs.stat(path.join(runRoot, "manifest.json")),
        ]);
        const signals = [signalA, signalB].map((signal) => ({
          signalId: signal.signal_id,
          sourceFindingId: signal.source_definition.source_finding_id,
          status: signal.replication_status,
          expectedDirection: signal.source_definition.expected_direction,
          effectBps: signal.replication.mean_forward_return * 10_000,
          medianEffectBps: signal.replication.median_forward_return * 10_000,
          directionalHitRate: signal.replication.direction_hit_rate,
          costHurdleStatus: signal.replication.cost_hurdle_state,
          rawSample: signal.replication.observation_count,
          effectiveSample: signal.replication.effective_observation_count,
          symbolCount: signal.replication.symbol_count,
          profitableSymbolCount: signal.replication.breadth.profitable_direction_symbol_count,
          topSymbolContribution: signal.replication.breadth.top_symbol_contribution,
          temporalClassification: signal.replication.temporal_classification,
        })) as D46SignalReplication["signals"];
        return {
          modifiedAt: stat.mtimeMs,
          value: {
            milestone: broader ? "D4.6B" : "D4.6",
            runId: manifest.run_id,
            status: manifest.status,
            sourceRun: manifest.source_run,
            latestStage: manifest.latest_stage,
            decision: gate.decision,
            usableSymbolCount: manifest.usable_symbol_count,
            eligibleUniverseCount: manifest.eligible_universe_count,
            costHurdleBps: manifest.cost_hurdle_bps,
            oosAccess: manifest.oos_access,
            signals,
          } as D46SignalReplication,
        };
      } catch { return null; }
    }));
    return completed.filter((item): item is NonNullable<typeof item> => item !== null).sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.value ?? null;
  } catch { return null; }
}
