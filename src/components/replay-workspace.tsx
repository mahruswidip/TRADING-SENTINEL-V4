"use client";

import { useMemo, useState } from "react";
import type { ReplayScenario, ReplaySpeed, ReplayTimeframe } from "@/domain/replay";
import { useReplayController } from "@/hooks/use-replay-controller";
import { deriveReplayView, firstReplayEventTimestamp, firstReplayTradeTimestamp, getReplayPeriod } from "@/lib/replay";
import { Panel } from "@/components/panel";
import { Progress } from "@/components/progress";
import { ReplayChart } from "@/components/replay-chart";
import { StateMachine } from "@/components/state-machine";
import { StatusPill, statusTone } from "@/components/status-pill";
import { DataSourceBadge } from "@/components/data-source-badge";

const speeds = [1, 5, 20] as const;
const time = (timestamp: number) => new Date(timestamp * 1000).toISOString().slice(11, 16);
const dateTime = (timestamp: number) => new Date(timestamp * 1000).toISOString().replace("T", " ").slice(0, 16);

export function ReplayWorkspace({ scenario }: { scenario: ReplayScenario }) {
  const timeframes = scenario.series.map((series) => series.timeframe);
  const [timeframe, setTimeframe] = useState<ReplayTimeframe>("5M");
  const replay = useReplayController(scenario);
  const view = useMemo(() => deriveReplayView(scenario, timeframe, replay.clock.currentTimestamp), [replay.clock.currentTimestamp, scenario, timeframe]);
  const progress = replay.clock.totalSteps > 1 ? Math.round((replay.clock.currentIndex / (replay.clock.totalSteps - 1)) * 100) : 100;
  const tradePlan = view.events.find((event) => event.type === "ENTRY_PLAN");
  const stopLoss = view.events.find((event) => event.type === "STOP_LOSS");
  const targets = view.events.filter((event) => event.type === "TAKE_PROFIT");
  const period = getReplayPeriod(scenario, replay.clock.currentTimestamp);
  const firstEvent = firstReplayEventTimestamp(scenario);
  const firstTrade = firstReplayTradeTimestamp(scenario);

  return <>
    <div className="replay-summary">
      <div><small>SCENARIO</small><strong>{scenario.symbol} · {scenario.strategyId}_{scenario.strategyVersion}</strong></div>
      <div><small>FRAMEWORK</small><strong>{scenario.profile.timeframes.map((item) => item.timeframe).join(" → ")}</strong></div>
      <div><small>REPLAY CLOCK · UTC</small><strong>{dateTime(replay.clock.currentTimestamp)}</strong></div>
      <div className="replay-source"><DataSourceBadge source={scenario.source} /><StatusPill label={replay.clock.status} tone={statusTone(replay.clock.status)} /></div>
    </div>
    {scenario.source === "BACKTEST" && <div className={`replay-period ${period.startsWith("WARMUP") ? "replay-period--warmup" : "replay-period--evaluation"}`}><strong>{period}</strong><span>{period.startsWith("WARMUP") ? `Context candles only · evaluation starts ${dateTime(scenario.evaluationStartTimestamp ?? scenario.startTimestamp)} UTC` : `Strategy events are eligible from ${dateTime(scenario.evaluationStartTimestamp ?? scenario.startTimestamp)} UTC`}</span></div>}

    <div className="replay-layout">
      <Panel title={`${scenario.symbol} · ${timeframe}`} eyebrow="Deterministic historical candles" className="replay-chart-panel" action={<div className="timeframe-tabs" role="group" aria-label="Chart timeframe">{timeframes.map((value) => <button key={value} className={timeframe === value ? "is-active" : ""} aria-pressed={timeframe === value} onClick={() => setTimeframe(value)}>{value}</button>)}</div>}>
        <ReplayChart timeframe={timeframe} candles={view.candles} annotations={view.annotations} currentTimestamp={view.currentTimestamp} />
        {tradePlan && <div className="replay-trade-plan" aria-label="Structured trade plan">
          <span>ENTRY <strong>{"price" in tradePlan ? tradePlan.price?.toLocaleString() : "—"}</strong></span>
          <span>SL <strong>{stopLoss && "price" in stopLoss && typeof stopLoss.price === "number" ? stopLoss.price.toLocaleString() : "—"}</strong></span>
          {targets.map((target, index) => "price" in target && typeof target.price === "number" ? <span key={target.id}>TP{index + 1} <strong>{target.price.toLocaleString()}</strong></span> : null)}
          <span>RISK DISTANCE <strong>{"riskDistance" in tradePlan ? tradePlan.riskDistance?.toLocaleString() ?? "—" : "—"}</strong></span>
          <span>EXPECTED R:R <strong>{"expectedRiskReward" in tradePlan ? tradePlan.expectedRiskReward?.toFixed(1) ?? "—" : "—"}</strong></span>
        </div>}
      </Panel>
      <div className="replay-side">
        <Panel title="Trading state" eyebrow="Replay synchronized"><StatusPill label={view.currentState} tone={statusTone(view.currentState)} /><StateMachine current={view.currentState} /></Panel>
        <Panel title="Timeframe status" eyebrow="Known at current time"><div className="replay-tf-status">{view.timeframeStatuses.map((item) => <article key={item.timeframe}><strong>{item.timeframe}</strong><div><StatusPill label={item.label} tone={item.tone} /><p>{item.detail}</p></div></article>)}</div></Panel>
      </div>
    </div>

    <Panel title="Replay controls" eyebrow="ReplayClock is authoritative">
      <div className="replay-controls">
        <button onClick={replay.jumpToStart} disabled={replay.clock.currentIndex === 0} title="Jump to start">|&lt;</button>
        {firstEvent !== null && <button onClick={() => replay.jumpToTimestamp(firstEvent)}>Jump to first event</button>}
        {firstTrade !== null && <button onClick={() => replay.jumpToTimestamp(firstTrade)}>Jump to first trade</button>}
        <button onClick={replay.stepBackward} disabled={replay.clock.currentIndex === 0}>Step backward</button>
        {replay.clock.isPlaying ? <button className="replay-primary" onClick={replay.pause}>Pause</button> : <button className="replay-primary" onClick={replay.play}>Play</button>}
        <button onClick={replay.stepForward} disabled={replay.clock.currentIndex >= replay.clock.totalSteps - 1}>Step forward</button>
        <button onClick={replay.restart}>Restart</button>
        <label className="replay-speed"><span>Speed</span><select value={replay.clock.speed} onChange={(event) => replay.setSpeed(Number(event.target.value) as ReplaySpeed)}>{speeds.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}</select></label>
      </div>
      <Progress value={progress} label={`Step ${replay.clock.currentIndex + 1} / ${replay.clock.totalSteps}`} />
      {replay.clock.status === "COMPLETE" && <p className="replay-complete">Replay complete · deterministic lifecycle closed.</p>}
    </Panel>

    <div className="replay-audit-grid">
      <Panel title="What Sentinel knows" eyebrow="Why this state?"><div className="replay-event-list">{view.events.length ? view.events.slice(-8).map((event) => <article key={event.id}><time>{time(event.availableAt)}</time><div><strong>{event.label}</strong><p>{event.reason}</p></div></article>) : <p className="inline-empty">No structured events are known yet.</p>}</div></Panel>
      <Panel title="Event timeline" eyebrow="No future events"><div className="replay-timeline">{view.events.length ? view.events.slice(-12).map((event) => <article key={event.id}><time>{time(event.availableAt)}</time><StatusPill label={event.category} tone={statusTone(event.category)} /><div><strong>{event.timeframe} · {event.type.replaceAll("_", " ")}</strong>{event.type === "STATE_TRANSITION" && <small>{event.fromState} → {event.toState}</small>}</div></article>) : <p className="inline-empty">Timeline begins when the first event becomes available.</p>}</div></Panel>
    </div>
  </>;
}
