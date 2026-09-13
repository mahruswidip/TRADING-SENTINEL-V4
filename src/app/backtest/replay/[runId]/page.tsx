import Link from "next/link";
import { notFound } from "next/navigation";
import { DataStateBoundary } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { ReplayWorkspace } from "@/components/replay-workspace";
import { replayData } from "@/data/replay-provider";
import { validateReplayScenario } from "@/lib/replay";

export const dynamicParams = true;
export const dynamic = "force-dynamic";

export async function generateStaticParams() {
  const scenarios = await replayData.getScenarios();
  return scenarios.map((scenario) => ({ runId: scenario.runId }));
}

export default async function ReplayPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  const scenario = await replayData.getScenarioByRunId(runId);
  if (!scenario) notFound();
  const validationError = validateReplayScenario(scenario);

  return <>
    <PageHeading eyebrow="D2 deterministic replay" title="Chart Replay" description="One replay clock controls candles, structured annotations, trading state, and the audit timeline." />
    <Link className="back-link" href="/backtest">← Back to Backtest Monitor</Link>
    {validationError ? <DataStateBoundary state="error" message={validationError}>Replay unavailable.</DataStateBoundary> : <ReplayWorkspace scenario={scenario} />}
  </>;
}
