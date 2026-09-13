import type { BacktestUniverseProgress } from "@/domain/contracts";

export function backtestProgressPct({ processed, total }: BacktestUniverseProgress): number {
  return total > 0 ? Math.round((processed / total) * 100) : 0;
}
