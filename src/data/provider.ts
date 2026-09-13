import type { BacktestJob, OverviewData, StrategyVersion, SystemHealth } from "@/domain/contracts";

export interface SentinelDataProvider {
  getOverview(): Promise<OverviewData>;
  getBacktestJobs(): Promise<readonly BacktestJob[]>;
  getBacktestRun(runId: string): Promise<BacktestJob | null>;
  getActiveBacktestRun(): Promise<BacktestJob | null>;
  getStrategies(): Promise<readonly StrategyVersion[]>;
  getSystemHealth(): Promise<SystemHealth>;
}
