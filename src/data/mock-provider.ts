import type { SentinelDataProvider } from "@/data/provider";
import { activities, backtestJobs, decisions, getActiveBacktestRunFixture, getBacktestRunFixture, positions, riskState, strategies, systemHealth } from "@/data/fixtures";

export const mockSentinelProvider: SentinelDataProvider = {
  async getOverview() {
    return { system: systemHealth, risk: riskState, activeJob: getActiveBacktestRunFixture(), jobs: backtestJobs, strategies, positions, decisions, activities };
  },
  async getBacktestJobs() {
    return backtestJobs;
  },
  async getBacktestRun(runId) {
    return getBacktestRunFixture(runId);
  },
  async getActiveBacktestRun() {
    return getActiveBacktestRunFixture();
  },
  async getStrategies() {
    return strategies;
  },
  async getSystemHealth() {
    return systemHealth;
  },
};
