from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import ENGINE_VERSION, STRATEGY_ID, STRATEGY_LABEL, STRATEGY_VERSION
from .data import BridgeClient, HistoricalDataStore, atomic_json, gap_count, iso_ms
from .engine import ReferenceIntradayStrategy, metrics, resample_closed, resolve_ambiguous, run_symbol, stable_digest, trade_events
from .model import Candle, CostModel, Trade


PROFILE = {
    "id": "INTRADAY",
    "label": "Intraday",
    "timeframes": [
        {"timeframe": "1D", "responsibility": "Bias / Market Context"},
        {"timeframe": "1H", "responsibility": "Structure / Setup"},
        {"timeframe": "5M", "responsibility": "Entry / Execution"},
    ],
}


def jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(temporary, path)


def trade_from_dict(value: dict[str, Any]) -> Trade:
    value = dict(value)
    value["take_profits"] = tuple(value["take_profits"])
    value["funding_events"] = tuple(value["funding_events"])
    return Trade(**{field.name: value[field.name] for field in fields(Trade)})


def eligible_symbols(universe: dict[str, Any], start: int, end: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    eligible, excluded = [], []
    tickers = {str(item.get("symbol", "")): item for item in universe.get("tickers", [])}
    books = {str(item.get("symbol", "")): item for item in universe.get("books", [])}
    for source in universe.get("symbols", []):
        item = dict(source)
        ticker, book = tickers.get(str(item.get("symbol", "")), {}), books.get(str(item.get("symbol", "")), {})
        item["quoteVolume24h"] = ticker.get("quoteVolume")
        item["bidPrice"], item["askPrice"] = book.get("bidPrice"), book.get("askPrice")
        symbol = str(item.get("symbol", "")).upper()
        reason = None
        if item.get("contractType") != "PERPETUAL": reason = "NOT_PERPETUAL"
        elif item.get("quoteAsset") not in {"USDT", "USDC"} or item.get("marginAsset") not in {"USDT", "USDC"}: reason = "INVALID_METADATA"
        elif int(item.get("onboardDate") or 0) >= end: reason = "NOT_LISTED_YET"
        elif item.get("status") != "TRADING" and int(item.get("deliveryDate") or 0) <= start: reason = "NOT_TRADING_IN_WINDOW"
        if reason: excluded.append({"symbol": symbol or "UNKNOWN", "reason": reason})
        elif symbol: eligible.append(item)
    return eligible, excluded


def choose_symbols(eligible: list[dict[str, Any]], requested: str | None, universe_all: bool, verify_set: bool) -> list[str]:
    known = {str(item["symbol"]): item for item in eligible}
    if requested:
        symbols = [value.strip().upper() for value in requested.split(",") if value.strip()]
        missing = sorted(set(symbols) - known.keys())
        if missing: raise ValueError(f"ineligible or unknown symbols: {', '.join(missing)}")
        return sorted(set(symbols))
    if universe_all:
        return sorted(known)
    if verify_set:
        ranked = sorted(eligible, key=lambda item: float(item.get("quoteVolume24h") or item.get("quoteVolume") or 0), reverse=True)
        if len(ranked) < 3: raise ValueError("dynamic universe has fewer than three eligible symbols")
        return sorted({str(ranked[0]["symbol"]), str(ranked[len(ranked) // 2]["symbol"]), str(ranked[-1]["symbol"])})
    raise ValueError("choose --symbols, --universe all, or --verify-set")


def quality(candles: list[Candle], manifests: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    expected = max(0, (end - start) // 300_000)
    gaps = gap_count(candles, 300_000)
    return {
        "row_count": len(candles), "expected_rows": expected, "gap_count": gaps,
        "first_timestamp": candles[0].open_time if candles else None,
        "last_timestamp": candles[-1].open_time if candles else None,
        "dataset_ids": [item["dataset_id"] for item in manifests],
    }


def process_symbol(symbol: str, run_id: str, start: int, end: int, cache_root: Path, bridge_url: str, cost: CostModel) -> dict[str, Any]:
    store = HistoricalDataStore(cache_root, BridgeClient(bridge_url))
    warmup = start - 3 * 86_400_000
    candles, manifests = store.candles(symbol, "5m", warmup, end)
    in_window = [bar for bar in candles if start <= bar.open_time < end]
    data_quality = quality(in_window, manifests, start, end)
    if not in_window:
        return {"symbol": symbol, "failure": "INSUFFICIENT_HISTORY", "quality": data_quality, "trades": [], "events": [], "funnel": {}}
    if data_quality["gap_count"]:
        return {"symbol": symbol, "failure": "DATA_GAP", "quality": data_quality, "trades": [], "events": [], "funnel": {}}
    dataset_version = stable_digest(data_quality["dataset_ids"])
    funding = store.funding(symbol, start, end)
    result = run_symbol(run_id, symbol, candles, funding, dataset_version, cost, start, end)
    resolved = []
    validation_failures = []
    for value in result["trades"]:
        trade = trade_from_dict(value)
        if trade.exit_reason == "INTRABAR_AMBIGUOUS":
            try:
                minute, _ = store.candles(symbol, "1m", trade.exit_time - 299_999, trade.exit_time + 1)
                trade = resolve_ambiguous(trade, minute, cost, funding)
            except RuntimeError:
                validation_failures.append(trade.trade_id)
        resolved.append(trade.as_dict())
    result["trades"] = resolved
    result["events"] = [event for trade in resolved for event in trade_events(trade_from_dict(trade))]
    result["quality"] = data_quality
    result["quality"]["funding_event_count"] = len(funding)
    result["quality"]["validation_failures"] = validation_failures
    result["dataset_version"] = dataset_version
    result["cache_hits"] = store.cache_hits
    result["downloads"] = store.downloads
    result["hourly"] = [bar.as_dict() for bar in result["hourly"]]
    result["daily"] = [bar.as_dict() for bar in result["daily"]]
    result["candles"] = [bar.as_dict() for bar in result["candles"]]
    return result


def replay_artifact(run_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if not result["trades"]: return None
    trade = result["trades"][0]
    start = trade["signal_time"] - 6 * 3_600_000
    end = trade["exit_time"] + 3_600_000
    as_candle = lambda row: row if isinstance(row, Candle) else Candle(**row)
    five = [bar for row in result["candles"] if start <= (bar := as_candle(row)).open_time <= end]
    hour = [bar for row in result["hourly"] if (bar := as_candle(row)).close_time <= end][-48:]
    day = [bar for row in result["daily"] if (bar := as_candle(row)).close_time <= end][-14:]
    def series(timeframe: str, rows: list[Candle]) -> dict[str, Any]:
        return {"symbol": result["symbol"], "timeframe": timeframe, "candles": [{"timestamp": row.close_time // 1000, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume} for row in rows]}
    available = [rows for rows in (day, hour, five) if rows]
    if len(available) != 3: return None
    scenario_start = min(rows[0].close_time for rows in available) // 1000
    scenario_end = max(rows[-1].close_time for rows in available) // 1000
    return {
        "id": f"replay-{trade['trade_id']}", "runId": run_id, "symbol": result["symbol"],
        "strategyId": trade["strategy_id"], "strategyVersion": trade["strategy_version"], "profile": PROFILE,
        "source": "BACKTEST", "startTimestamp": scenario_start, "endTimestamp": scenario_end,
        "series": [series("1D", day), series("1H", hour), series("5M", five)], "events": result["events"],
    }


def dashboard_job(run_id: str, symbols: list[str], summary: dict[str, Any], started: datetime, ended: datetime, workers: int, dataset_version: str) -> dict[str, Any]:
    item = lambda name: summary[name]
    trades = max(1, int(item("trade_count")))
    notional = trades * 1_000
    return {
        "id": run_id, "source": "REAL_BACKTEST", "status": "COMPLETED",
        "universeProgress": {"universe": "Dynamic Binance USDⓈ-M Perpetual Universe(t)", "processed": len(symbols), "total": len(symbols)},
        "currentEvaluation": None, "strategyVariant": {"strategyId": STRATEGY_ID, "strategyVersion": STRATEGY_VERSION, "current": 1, "total": 1},
        "tradingState": "TRADE_CLOSED" if item("trade_count") else "WAIT", "completedEvaluations": [],
        "startedAt": started.isoformat(), "elapsed": str(ended - started).split(".")[0], "eta": "00:00:00", "workerCount": workers,
        "metrics": {
            "grossReturnPct": item("gross_return"), "netReturnPct": item("net_return"), "winRatePct": item("win_rate"),
            "expectancyR": item("expectancy_R"), "profitFactor": item("profit_factor"), "maxDrawdownPct": item("max_drawdown"), "tradeCount": item("trade_count"),
            "feesUsd": item("fees_total"), "feesBps": item("fees_total") / notional * 10_000,
            "fundingUsd": item("funding_total"), "fundingBps": item("funding_total") / notional * 10_000,
            "spreadUsd": item("spread_total"), "spreadBps": item("spread_total") / notional * 10_000,
            "slippageUsd": item("slippage_total"), "slippageBps": item("slippage_total") / notional * 10_000,
            "long": {"trades": item("LONG")["trade_count"], "netReturnPct": item("LONG")["net_return"], "profitFactor": item("LONG")["profit_factor"]},
            "short": {"trades": item("SHORT")["trade_count"], "netReturnPct": item("SHORT")["net_return"], "profitFactor": item("SHORT")["profit_factor"]},
        },
        "errorMessage": None, "datasetVersion": dataset_version, "engineVersion": ENGINE_VERSION,
    }


def running_dashboard_job(run_id: str, symbols: list[str], completed: dict[str, Any], failed: dict[str, Any], current_symbol: str | None, started: datetime, workers: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    processed = len(completed) + len(failed)
    partial_trades = [trade for symbol in sorted(completed) for trade in completed[symbol].get("trades", [])]
    partial = metrics(partial_trades)
    job = dashboard_job(run_id, symbols, partial, started, now, workers, "PENDING")
    elapsed_seconds = max(0, int((now - started).total_seconds()))
    eta_seconds = int(elapsed_seconds / processed * (len(symbols) - processed)) if processed else 0
    job.update({
        "status": "RUNNING_FAST",
        "universeProgress": {**job["universeProgress"], "processed": processed},
        "tradingState": "SCANNING",
        "elapsed": str(timedelta(seconds=elapsed_seconds)),
        "eta": str(timedelta(seconds=eta_seconds)) if processed else None,
        "metrics": job["metrics"] if partial_trades else None,
        "currentEvaluation": None if current_symbol is None else {
            "symbol": current_symbol, "strategyId": STRATEGY_ID, "strategyVersion": STRATEGY_VERSION,
            "profile": PROFILE, "timeframeFramework": PROFILE["timeframes"], "currentState": "SCANNING", "currentVariant": 1,
            "biasStatus": "ANALYZING", "structureStatus": "PENDING", "entryStatus": "PENDING",
            "marketContext": None, "structure": None, "entry": None,
        },
    })
    return job


def run(args: argparse.Namespace) -> int:
    if args.strategy != f"{STRATEGY_ID}_{STRATEGY_VERSION}": raise ValueError("only the engineering reference strategy exists in D3")
    start, end = iso_ms(args.start), iso_ms(args.end)
    if end <= start: raise ValueError("--end must be after --start")
    workers = max(1, min(8, args.workers))
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    bridge = BridgeClient(bridge_url)
    universe = bridge.universe()
    eligible, universe_exclusions = eligible_symbols(universe, start, end)
    symbols = choose_symbols(eligible, args.symbols, args.universe == "all", args.verify_set)
    config = {"strategy": args.strategy, "start": start, "end": end, "symbols": symbols, "workers": workers, "cost": CostModel().__dict__, "engine_version": ENGINE_VERSION}
    run_id = args.run_id or f"d3_{stable_digest({key: value for key, value in config.items() if key != 'workers'})[:16]}"
    artifact = Path(args.state_root) / run_id
    manifest_path, checkpoint_path = artifact / "manifest.json", artifact / "checkpoint.json"
    if manifest_path.exists() and (artifact / "summary.json").exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        identity = (existing.get("strategy_id"), existing.get("strategy_version"), existing.get("engine_version"), existing.get("start_time"), existing.get("end_time"), existing.get("universe_snapshot"))
        expected = (STRATEGY_ID, STRATEGY_VERSION, ENGINE_VERSION, start, end, symbols)
        if identity != expected: raise ValueError(f"run ID {run_id} already belongs to a different immutable run")
        print(json.dumps({"run_id": run_id, "status": "ALREADY_COMPLETED", "artifact": str(artifact.resolve())}))
        return 0
    artifact.mkdir(parents=True, exist_ok=True)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"completed": {}, "failed": {}}
    started = datetime.now(UTC)
    cost = CostModel()
    pending = [symbol for symbol in symbols if symbol not in checkpoint["completed"] and symbol not in checkpoint["failed"]]
    atomic_json(artifact / "dashboard-job.json", running_dashboard_job(run_id, symbols, checkpoint["completed"], checkpoint["failed"], pending[0] if pending else None, started, workers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_symbol, symbol, run_id, start, end, Path(args.cache_root), bridge_url, cost): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                value = future.result()
                target = "failed" if value.get("failure") else "completed"
                checkpoint[target][symbol] = value
            except Exception as exc:
                checkpoint["failed"][symbol] = {"symbol": symbol, "failure": "DOWNLOAD_FAILED", "detail": type(exc).__name__}
            atomic_json(checkpoint_path, checkpoint)
            remaining = [item for item in symbols if item not in checkpoint["completed"] and item not in checkpoint["failed"]]
            atomic_json(artifact / "dashboard-job.json", running_dashboard_job(run_id, symbols, checkpoint["completed"], checkpoint["failed"], remaining[0] if remaining else None, started, workers))
            print(json.dumps({"run_id": run_id, "processed": len(checkpoint["completed"]) + len(checkpoint["failed"]), "total": len(symbols), "current_symbol": symbol}))
    ordered = [checkpoint["completed"][symbol] for symbol in sorted(checkpoint["completed"])]
    trades = [trade for result in ordered for trade in result["trades"]]
    events = [event for result in ordered for event in result["events"]]
    summary = metrics(trades)
    dataset_version = stable_digest(sorted(result["dataset_version"] for result in ordered))
    ended = datetime.now(UTC)
    manifest = {
        "run_id": run_id, "status": "COMPLETED", "strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION,
        "strategy_label": STRATEGY_LABEL, "strategy_config_hash": stable_digest({"implementation": inspect.getsource(ReferenceIntradayStrategy)}),
        "engine_version": ENGINE_VERSION, "dataset_version": dataset_version, "cost_model_version": cost.version,
        "fee_model": {"source": cost.fee_source, "taker_bps": cost.taker_bps},
        "spread_model": {"source": cost.spread_source, "bps": cost.spread_bps}, "slippage_model": {"source": cost.slippage_source, "bps": cost.slippage_bps},
        "execution_model_version": "next-open-market-v1", "universe_selector": "all" if args.universe == "all" else "verification" if args.verify_set else "symbols",
        "universe_snapshot": symbols, "universe_exclusions": universe_exclusions, "start_time": start, "end_time": end,
        "worker_count": workers, "created_at": ended.isoformat(), "bridge_source": "TRADING_SENTINEL_V2_MARKET_BRIDGE",
    }
    symbol_metrics = [{"symbol": result["symbol"], **metrics(result["trades"])} for result in ordered]
    decisions = [{"symbol": result["symbol"], "final_decision": "WAIT" if not result["trades"] else "LONG_SHORT_EVALUATED", "rejection_reasons": [], **result["funnel"]} for result in ordered]
    decisions.extend({"symbol": symbol, "final_decision": "REJECTED", "rejection_reasons": [value["failure"]]} for symbol, value in sorted(checkpoint["failed"].items()))
    data_quality = [result["quality"] | {"symbol": result["symbol"]} for result in ordered] + list(checkpoint["failed"].values())
    replay = next((candidate for result in ordered if (candidate := replay_artifact(run_id, result))), None)
    atomic_json(artifact / "manifest.json", manifest)
    atomic_json(artifact / "summary.json", summary)
    atomic_json(artifact / "symbol-metrics.json", symbol_metrics)
    jsonl(artifact / "trades.jsonl", trades)
    jsonl(artifact / "decisions.jsonl", decisions)
    jsonl(artifact / "events.jsonl", events)
    atomic_json(artifact / "data-quality.json", data_quality)
    if replay: atomic_json(artifact / "replay.json", replay)
    atomic_json(artifact / "dashboard-job.json", dashboard_job(run_id, symbols, summary, started, ended, workers, dataset_version))
    atomic_json(checkpoint_path, {"completed_symbols": sorted(checkpoint["completed"]), "failed_symbols": checkpoint["failed"], "trade_count": len(trades), "status": "COMPLETED"})
    print(json.dumps({"run_id": run_id, "status": "COMPLETED", "symbols": symbols, "summary": summary, "replay": bool(replay), "artifact": str(artifact.resolve())}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="backtest", description="Trading Sentinel V4 deterministic research backtester")
    commands = root.add_subparsers(dest="command", required=True)
    command = commands.add_parser("run")
    command.add_argument("--strategy", default=f"{STRATEGY_ID}_{STRATEGY_VERSION}")
    command.add_argument("--start", required=True); command.add_argument("--end", required=True)
    command.add_argument("--symbols"); command.add_argument("--universe", choices=["all"]); command.add_argument("--verify-set", action="store_true")
    command.add_argument("--workers", type=int, default=3); command.add_argument("--run-id")
    command.add_argument("--cache-root", default="data/market"); command.add_argument("--state-root", default="state/backtests")
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return run(args)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
