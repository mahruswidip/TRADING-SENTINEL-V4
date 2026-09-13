import { mockSentinelProvider } from "@/data/mock-provider";
import { getD3BacktestJobs, getD3BacktestRun } from "@/data/d3-provider";
import type { SentinelDataProvider } from "@/data/provider";
import { getD4Strategies } from "@/data/d4-provider";

// D3 supplements frozen deterministic fixtures with immutable worker artifacts.
export const sentinelData: SentinelDataProvider = {
  ...mockSentinelProvider,
  async getOverview() {
    const [overview, realJobs] = await Promise.all([mockSentinelProvider.getOverview(), getD3BacktestJobs()]);
    const activeRealJob = realJobs.find((job) => ["QUEUED", "PREPARING_DATA", "RUNNING", "RUNNING_FAST", "VALIDATING"].includes(job.status));
    return { ...overview, activeJob: activeRealJob ?? overview.activeJob, jobs: [...realJobs, ...overview.jobs] };
  },
  async getBacktestJobs() {
    return [...await getD3BacktestJobs(), ...await mockSentinelProvider.getBacktestJobs()];
  },
  async getBacktestRun(runId) {
    return await getD3BacktestRun(runId) ?? mockSentinelProvider.getBacktestRun(runId);
  },
  async getActiveBacktestRun() {
    const realJobs = await getD3BacktestJobs();
    return realJobs.find((job) => ["QUEUED", "PREPARING_DATA", "RUNNING", "RUNNING_FAST", "VALIDATING"].includes(job.status)) ?? mockSentinelProvider.getActiveBacktestRun();
  },
  async getStrategies() {
    return [...await getD4Strategies(), ...await mockSentinelProvider.getStrategies()];
  },
};
