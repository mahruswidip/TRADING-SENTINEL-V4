import { promises as fs } from "node:fs";
import path from "node:path";

const replicationRoot = path.join(process.cwd(), "state", "signal-replication");

interface SymbolResult {
  status?: string;
  detail?: string;
  downloads?: number;
  cache_hits?: number;
}

interface CheckpointArtifact {
  completed_symbols?: Readonly<Record<string, SymbolResult>>;
  failed_symbols?: Readonly<Record<string, SymbolResult>>;
}

interface ResourcePlanArtifact {
  run_id?: string;
  selected_symbol_count?: number;
  target_symbol_count?: number;
  worker_count?: number;
  oos_access?: string;
  symbols?: readonly string[];
}

export interface D47MonitorSnapshot {
  runId: string;
  status: "RUNNING" | "DEGRADED" | "FINALIZING" | "COMPLETED";
  finalDecision: string | null;
  completed: number;
  failed: number;
  pending: number;
  processed: number;
  total: number;
  progressPct: number;
  configuredWorkers: number;
  lastUpdatedAt: string;
  latestSymbol: string | null;
  cacheHits: number;
  downloads: number;
  oosAccess: string;
  recentFailures: readonly { symbol: string; status: string; detail: string }[];
}

async function latestD47Directory(): Promise<string | null> {
  try {
    const folders = (await fs.readdir(replicationRoot)).filter((name) => name.startsWith("d4_7_"));
    const candidates = await Promise.all(folders.map(async (name) => {
      const checkpointPath = path.join(replicationRoot, name, "checkpoint.json");
      try { return { name, modifiedAt: (await fs.stat(checkpointPath)).mtimeMs }; }
      catch { return null; }
    }));
    return candidates
      .filter((candidate): candidate is NonNullable<typeof candidate> => candidate !== null)
      .sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.name ?? null;
  } catch {
    return null;
  }
}

export async function getD47MonitorSnapshot(): Promise<D47MonitorSnapshot | null> {
  const directory = await latestD47Directory();
  if (!directory) return null;

  const runRoot = path.join(replicationRoot, directory);
  try {
    const checkpointPath = path.join(runRoot, "checkpoint.json");
    const [checkpointText, planText, checkpointStat, manifest] = await Promise.all([
      fs.readFile(checkpointPath, "utf8"),
      fs.readFile(path.join(runRoot, "resource-plan.json"), "utf8"),
      fs.stat(checkpointPath),
      fs.readFile(path.join(runRoot, "manifest.json"), "utf8").then((value) => JSON.parse(value) as { status?: string; final_decision?: string }).catch(() => null),
    ]);
    const checkpoint = JSON.parse(checkpointText) as CheckpointArtifact;
    const plan = JSON.parse(planText) as ResourcePlanArtifact;
    const completedEntries = Object.entries(checkpoint.completed_symbols ?? {});
    const failedEntries = Object.entries(checkpoint.failed_symbols ?? {});
    const total = plan.selected_symbol_count ?? plan.target_symbol_count ?? plan.symbols?.length ?? 0;
    const processed = completedEntries.length + failedEntries.length;
    const pending = Math.max(total - processed, 0);
    const allEntries = [...completedEntries, ...failedEntries];
    const cacheHits = allEntries.reduce((sum, [, result]) => sum + (result.cache_hits ?? 0), 0);
    const downloads = allEntries.reduce((sum, [, result]) => sum + (result.downloads ?? 0), 0);
    const latestWork = await latestWorkSymbol(runRoot);

    return {
      runId: plan.run_id ?? directory,
      status: manifest?.status === "COMPLETED" ? "COMPLETED" : pending === 0 ? "FINALIZING" : failedEntries.length > 0 ? "DEGRADED" : "RUNNING",
      finalDecision: manifest?.final_decision ?? null,
      completed: completedEntries.length,
      failed: failedEntries.length,
      pending,
      processed,
      total,
      progressPct: total > 0 ? Math.round(processed / total * 100) : 0,
      configuredWorkers: plan.worker_count ?? 0,
      lastUpdatedAt: checkpointStat.mtime.toISOString(),
      latestSymbol: latestWork,
      cacheHits,
      downloads,
      oosAccess: plan.oos_access ?? "OOS_NOT_ACCESSED",
      recentFailures: failedEntries.slice(-5).reverse().map(([symbol, result]) => ({
        symbol,
        status: result.status ?? "FAILED",
        detail: result.detail ?? "No failure detail recorded",
      })),
    };
  } catch {
    return null;
  }
}

async function latestWorkSymbol(runRoot: string): Promise<string | null> {
  try {
    const workRoot = path.join(runRoot, "work");
    const files = (await fs.readdir(workRoot)).filter((name) => name.endsWith(".quality.json"));
    const candidates = await Promise.all(files.map(async (name) => ({
      name: name.slice(0, -".quality.json".length),
      modifiedAt: (await fs.stat(path.join(workRoot, name))).mtimeMs,
    })));
    return candidates.sort((left, right) => right.modifiedAt - left.modifiedAt)[0]?.name ?? null;
  } catch {
    return null;
  }
}
