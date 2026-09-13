import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { btcusdtTrendContinuationV7Replay as scenario } from "../src/data/fixtures/replay/btcusdt-trend-continuation-v7.ts";
import { deriveReplayView, getReplayCheckpoints, getReplayPeriod, isVisibleAt, validateReplayScenario } from "../src/lib/replay.ts";

const at = (iso) => Date.parse(iso) / 1000;

test("reference replay fixture is valid and has all required timeframes", () => {
  assert.equal(validateReplayScenario(scenario), null);
  assert.deepEqual(scenario.series.map((series) => series.timeframe), ["1D", "1H", "5M"]);
});

test("future candles and unavailable annotations never leak", () => {
  const timestamp = at("2026-09-10T13:00:00Z");
  for (const timeframe of ["1D", "1H", "5M"]) {
    const view = deriveReplayView(scenario, timeframe, timestamp);
    assert.ok(view.candles.every((candle) => candle.timestamp <= timestamp));
    assert.ok(view.events.every((event) => event.timestamp <= timestamp && event.availableAt <= timestamp));
    assert.ok(view.annotations.every((event) => isVisibleAt(event, timestamp)));
  }
  assert.equal(deriveReplayView(scenario, "5M", at("2026-09-10T13:24:00Z")).events.some((event) => event.type === "ENTRY_PLAN"), false);
});

test("state machine is derived from the replay timestamp", () => {
  const states = [
    ["2026-09-10T11:55:00Z", "SCANNING"],
    ["2026-09-10T12:00:00Z", "HTF_CONTEXT_FOUND"],
    ["2026-09-10T12:05:00Z", "BIAS_LOCKED"],
    ["2026-09-10T12:10:00Z", "WAITING_MTF_STRUCTURE"],
    ["2026-09-10T13:00:00Z", "MTF_CONFIRMED"],
    ["2026-09-10T13:05:00Z", "WAITING_LTF_ENTRY"],
    ["2026-09-10T13:25:00Z", "ENTRY_TRIGGERED"],
    ["2026-09-10T13:26:00Z", "RISK_VALIDATION"],
    ["2026-09-10T13:30:00Z", "TRADE_OPEN"],
    ["2026-09-10T14:45:00Z", "TRADE_CLOSED"],
  ];
  for (const [timestamp, state] of states) assert.equal(deriveReplayView(scenario, "5M", at(timestamp)).currentState, state);
});

test("rewind reconstructs state and removes future information", () => {
  const future = deriveReplayView(scenario, "5M", at("2026-09-10T14:45:00Z"));
  const past = deriveReplayView(scenario, "5M", at("2026-09-10T13:20:00Z"));
  assert.equal(future.currentState, "TRADE_CLOSED");
  assert.equal(past.currentState, "WAITING_LTF_ENTRY");
  assert.ok(future.candles.length > past.candles.length);
  assert.equal(past.events.some((event) => ["ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT", "TRADE_OPEN", "TRADE_CLOSED"].includes(event.type)), false);
  assert.equal(past.decisions.some((decision) => decision.toState === "TRADE_OPEN"), false);
});

test("same scenario and timestamp always produce the same view", () => {
  const timestamp = at("2026-09-10T13:30:00Z");
  assert.deepEqual(deriveReplayView(scenario, "5M", timestamp), deriveReplayView(scenario, "5M", timestamp));
  assert.deepEqual(getReplayCheckpoints(scenario), getReplayCheckpoints(scenario));
});

test("timeframe switching preserves the authoritative replay clock", () => {
  const timestamp = at("2026-09-10T13:30:00Z");
  const views = ["1D", "1H", "5M"].map((timeframe) => deriveReplayView(scenario, timeframe, timestamp));
  assert.ok(views.every((view) => view.currentTimestamp === timestamp));
  assert.deepEqual(views.map((view) => view.timeframe), ["1D", "1H", "5M"]);
  assert.ok(views.every((view) => view.candles.every((candle) => candle.timestamp <= timestamp)));
});

test("entry, stop, and targets become visible only with the entry plan", () => {
  const before = deriveReplayView(scenario, "5M", at("2026-09-10T13:24:59Z"));
  const after = deriveReplayView(scenario, "5M", at("2026-09-10T13:25:00Z"));
  for (const type of ["ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT"]) {
    assert.equal(before.annotations.some((event) => event.type === type), false);
    assert.equal(after.annotations.some((event) => event.type === type), true);
  }
});

test("chart renders structured annotations instead of inferring structure from candles", () => {
  const chart = readFileSync("src/components/replay-chart.tsx", "utf8");
  assert.match(chart, /annotations: readonly TradingEvent\[\]/);
  assert.doesNotMatch(chart, /candle\.(high|low|open|close)\s*[+\-*/]/);
  assert.doesNotMatch(chart, /infer(BOS|MSS|CHOCH|FVG)/i);
});

test("real D3 artifact separates warmup and exposes a complete trade lifecycle", () => {
  const runId = "d3_56bdea67f9c14033";
  const replay = JSON.parse(readFileSync(`state/backtests/${runId}/replay.json`, "utf8"));
  const manifest = JSON.parse(readFileSync(`state/backtests/${runId}/manifest.json`, "utf8"));
  const realScenario = { ...replay, evaluationStartTimestamp: manifest.start_time / 1000 };
  assert.equal(validateReplayScenario(realScenario), null);
  assert.equal(getReplayPeriod(realScenario, realScenario.evaluationStartTimestamp - 1), "WARMUP / CONTEXT PERIOD");
  assert.equal(getReplayPeriod(realScenario, realScenario.evaluationStartTimestamp), "BACKTEST EVALUATION PERIOD");
  assert.ok(realScenario.events.every((event) => event.availableAt >= realScenario.evaluationStartTimestamp));

  const entry = realScenario.events.find((event) => event.type === "ENTRY_TRIGGERED");
  assert.ok(entry);
  const tradeId = entry.id.replace(/-trigger$/, "");
  const opened = realScenario.events.find((event) => event.id === `${tradeId}-open`);
  const closed = realScenario.events.find((event) => event.id === `${tradeId}-close`);
  assert.ok(opened && closed);
  const visible = deriveReplayView(realScenario, "5M", closed.availableAt);
  for (const event of [entry, opened, closed]) assert.ok(visible.events.some((item) => item.id === event.id));
  for (const state of ["ENTRY_TRIGGERED", "TRADE_OPEN", "TRADE_CLOSED"]) assert.ok(realScenario.events.some((event) => event.type === "STATE_TRANSITION" && event.toState === state));
  assert.equal(visible.currentState, "TRADE_CLOSED");
});

test("D4.4 FVG replay uses the 1H/15M/5M profile and structured lifecycle", () => {
  const runId = "d4_4_7c26a8a6736abaf2";
  const scenario = JSON.parse(readFileSync(`state/research/FVG_PULLBACK_V1/${runId}/replay.json`, "utf8"));
  assert.equal(validateReplayScenario(scenario), null);
  assert.equal(scenario.profile.id, "INTRADAY_FVG");
  assert.deepEqual(scenario.series.map((item) => item.timeframe), ["1H", "15M", "5M"]);
  for (const type of ["BIAS_LOCKED", "FVG", "POI", "LIQUIDITY_SWEEP", "MSS", "ENTRY_TRIGGERED", "STOP_LOSS", "TAKE_PROFIT", "TRADE_OPEN", "TRADE_CLOSED"]) assert.ok(scenario.events.some((event) => event.type === type), type);
  assert.ok(scenario.events.every((event) => event.timestamp <= event.availableAt));
  const closed = scenario.events.find((event) => event.type === "TRADE_CLOSED");
  assert.ok(closed);
  assert.equal(deriveReplayView(scenario, "5M", closed.availableAt).currentState, "TRADE_CLOSED");
});
