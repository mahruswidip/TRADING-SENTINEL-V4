import type { ReplayScenario } from "@/domain/replay";
import { btcusdtTrendContinuationV7Replay } from "@/data/fixtures/replay/btcusdt-trend-continuation-v7";
import { promises as fs } from "node:fs";
import path from "node:path";

export interface ReplayDataProvider {
  getScenarios(): Promise<readonly ReplayScenario[]>;
  getScenarioByRunId(runId: string): Promise<ReplayScenario | null>;
}

const fixtures: readonly ReplayScenario[] = [btcusdtTrendContinuationV7Replay];
const fixturesByRunId = new Map(fixtures.map((scenario) => [scenario.runId, scenario]));

async function readRealScenario(root: string, folder: string): Promise<ReplayScenario | null> {
  try {
    const [replay, manifest] = await Promise.all([
      fs.readFile(path.join(root, folder, "replay.json"), "utf8"),
      fs.readFile(path.join(root, folder, "manifest.json"), "utf8"),
    ]);
    const scenario = JSON.parse(replay) as ReplayScenario;
    const run = JSON.parse(manifest) as { start_time?: number; splits?: { development?: { start?: number } } };
    const evaluationStart = run.start_time ?? run.splits?.development?.start;
    return { ...scenario, evaluationStartTimestamp: typeof evaluationStart === "number" ? evaluationStart / 1000 : scenario.evaluationStartTimestamp ?? scenario.startTimestamp };
  } catch { return null; }
}

async function researchScenarios(): Promise<readonly ReplayScenario[]> {
  try {
    const root = path.join(process.cwd(), "state", "research");
    const families = await fs.readdir(root);
    const values = await Promise.all(families.map(async (family) => {
      const familyRoot = path.join(root, family);
      const runs = await fs.readdir(familyRoot);
      return Promise.all(runs.map((run) => readRealScenario(familyRoot, run)));
    }));
    return values.flat().filter((value): value is ReplayScenario => value !== null);
  } catch { return []; }
}

async function realScenarios(): Promise<readonly ReplayScenario[]> {
  try {
    const root = path.join(process.cwd(), "state", "backtests");
    const folders = await fs.readdir(root);
    const values = await Promise.all(folders.map((folder) => readRealScenario(root, folder)));
    return values.filter((value): value is ReplayScenario => value !== null);
  } catch { return []; }
}

export const replayData: ReplayDataProvider = {
  async getScenarios() {
    return [...await researchScenarios(), ...await realScenarios(), ...fixtures];
  },
  async getScenarioByRunId(runId) {
    if (/^[A-Za-z0-9_-]+$/.test(runId)) {
      const scenario = await readRealScenario(path.join(process.cwd(), "state", "backtests"), runId);
      if (scenario) return scenario;
      const research = await researchScenarios();
      const researchScenario = research.find((value) => value.runId === runId);
      if (researchScenario) return researchScenario;
    }
    return fixturesByRunId.get(runId) ?? null;
  },
};
