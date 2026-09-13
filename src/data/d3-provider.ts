import { promises as fs } from "node:fs";
import path from "node:path";
import type { BacktestJob } from "@/domain/contracts";

const stateRoot = path.join(process.cwd(), "state", "backtests");

async function readJob(folder: string): Promise<BacktestJob | null> {
  try {
    return JSON.parse(await fs.readFile(path.join(stateRoot, folder, "dashboard-job.json"), "utf8")) as BacktestJob;
  } catch {
    return null;
  }
}

export async function getD3BacktestJobs(): Promise<readonly BacktestJob[]> {
  try {
    const folders = await fs.readdir(stateRoot);
    const jobs = await Promise.all(folders.map(readJob));
    return jobs.filter((job): job is BacktestJob => job !== null).sort((left, right) => (right.startedAt ?? "").localeCompare(left.startedAt ?? ""));
  } catch {
    return [];
  }
}

export async function getD3BacktestRun(runId: string): Promise<BacktestJob | null> {
  if (!/^[A-Za-z0-9_-]+$/.test(runId)) return null;
  return readJob(runId);
}
