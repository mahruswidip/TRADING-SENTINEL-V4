from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from backtest_engine.data import DAY_MS, BridgeClient, HistoricalDataStore, atomic_json


SOURCE = "BINANCE_USDS_M_FUTURES_OFFICIAL_PUBLIC_VIA_V2_BRIDGE"
BUFFER_MS = DAY_MS
MAX_WORKERS = 3


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract_status(item: dict[str, Any] | None, start: int, end: int) -> str:
    if not item:
        return "ERROR"
    if item.get("contractType") != "PERPETUAL" or item.get("quoteAsset") != "USDT" or item.get("marginAsset") != "USDT":
        return "NOT_PERPETUAL"
    if int(item.get("onboardDate") or 0) > start or int(item.get("deliveryDate") or 0) < end:
        return "NOT_LISTED_DURING_PERIOD"
    return "VALID_PERPETUAL"


def validate_rows(symbol: str, rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    valid: dict[int, dict[str, Any]] = {}
    duplicate_timestamps = null_rates = invalid_rates = 0
    for source in rows:
        try:
            timestamp = int(source["fundingTime"])
        except (KeyError, TypeError, ValueError):
            continue
        rate = source.get("fundingRate")
        if rate is None:
            null_rates += 1
            continue
        try:
            number = Decimal(str(rate))
            if not number.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            invalid_rates += 1
            continue
        if timestamp in valid:
            duplicate_timestamps += 1
            continue
        valid[timestamp] = {
            "symbol": symbol,
            "fundingTime": timestamp,
            "fundingRate": str(rate),
            **({"markPrice": source["markPrice"]} if source.get("markPrice") is not None else {}),
            **({"rateType": source["rateType"]} if source.get("rateType") is not None else {}),
            "source": SOURCE,
        }
    normalized = [valid[key] for key in sorted(valid)]
    timestamps = [int(row["fundingTime"]) for row in normalized]
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    rounded_hours = [max(1, round(delta / 3_600_000)) for delta in deltas]
    interval_changes = sum(left != right for left, right in zip(rounded_hours, rounded_hours[1:]))
    missing_intervals = sum(max(0, math.ceil(delta / (12 * 3_600_000)) - 1) for delta in deltas if delta > 12 * 3_600_000)
    boundary = max(deltas, default=8 * 3_600_000)
    covered = bool(timestamps) and timestamps[0] <= start + boundary and timestamps[-1] >= end - boundary
    complete = covered and not duplicate_timestamps and not null_rates and not invalid_rates and not missing_intervals
    return {
        "rows": normalized,
        "record_count": len(normalized),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "duplicate_timestamps": duplicate_timestamps,
        "missing_intervals": missing_intervals,
        "unexpected_interval_changes": interval_changes,
        "observed_interval_hours": sorted(set(rounded_hours)),
        "null_rates": null_rates,
        "invalid_numeric_rates": invalid_rates,
        "coverage_complete": complete,
    }


def fetch_pages(client: BridgeClient, symbol: str, start: int, end: int) -> list[dict[str, Any]]:
    cursor, rows = start, []
    while cursor < end:
        batch = client.funding(symbol, cursor, end)
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"funding pagination did not advance for {symbol}")
        cursor = next_cursor
        if len(batch) < 1000:
            break
    return rows


def missing_for_plan(plan: dict[str, Any], cache_root: Path) -> list[str]:
    start, end = int(plan["history"]["start"]), int(plan["history"]["end"])
    store = HistoricalDataStore(cache_root, BridgeClient("http://127.0.0.1:0", timeout_seconds=1))
    missing = []
    for item in plan["universe"]:
        symbol = str(item["symbol"])
        folder = cache_root / "binance-usdm-v1" / symbol / "funding"
        covering = False
        for path in folder.glob("*.json") if folder.exists() else ():
            try:
                cached_start, cached_end = map(int, path.stem.split("-", 1))
            except ValueError:
                continue
            if cached_start <= start and cached_end >= end:
                covering = True
                try:
                    if not store.funding(symbol, start, end):
                        covering = False
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    covering = False
                break
        if not covering:
            missing.append(symbol)
    return missing


def _report_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# D4.8A Historical Funding Cache Backfill", "",
        f"- D4.8 run: `{manifest['d4_8_run_id']}`",
        f"- Source: `{manifest['data_source']}`",
        f"- Requested: {manifest['requested_start']} through {manifest['requested_end']}",
        f"- Symbols: {len(manifest['symbols_succeeded'])}/{len(manifest['symbols_requested'])} complete",
        f"- Records: {manifest['total_records']}",
        f"- Verdict: **{manifest['completeness_verdict']}**", "",
        "| Symbol | Contract | Records | First | Last | Missing | Complete |", "|---|---|---:|---:|---:|---:|---|",
    ]
    for symbol in manifest["symbols_requested"]:
        row = manifest["symbols"][symbol]
        lines.append(f"| {symbol} | {row['contract_status']} | {row.get('record_count', 0)} | {row.get('first_timestamp')} | {row.get('last_timestamp')} | {row.get('missing_intervals', 0)} | {row.get('coverage_complete', False)} |")
    return "\n".join(lines) + "\n"


def backfill(run_root: Path, cache_root: Path, bridge_url: str, workers: int) -> dict[str, Any]:
    plan_path, universe_path = run_root / "execution_plan.json", run_root / "stage_a_universe.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    frozen = json.loads(universe_path.read_text(encoding="utf-8"))
    symbols = [str(item["symbol"]) for item in frozen["symbols"]]
    if symbols != [str(item["symbol"]) for item in plan["universe"]] or len(symbols) != 24:
        raise ValueError("frozen Stage-A universe disagreement")
    start, end = int(plan["history"]["start"]), int(plan["history"]["end"])
    requested_start, requested_end = start - BUFFER_MS, end + BUFFER_MS
    client = BridgeClient(bridge_url)
    universe = client.universe()
    metadata = {str(item.get("symbol")): item for item in universe.get("symbols", [])}
    statuses = {symbol: contract_status(metadata.get(symbol), start, end) for symbol in symbols}
    results: dict[str, dict[str, Any]] = {}

    def one(symbol: str) -> tuple[str, dict[str, Any]]:
        if statuses[symbol] != "VALID_PERPETUAL":
            return symbol, {"contract_status": statuses[symbol], "coverage_complete": False, "error": statuses[symbol]}
        try:
            checked = validate_rows(symbol, fetch_pages(BridgeClient(bridge_url), symbol, requested_start, requested_end), start, end)
            if not checked["rows"]:
                checked.update({"contract_status": "API_NO_DATA", "coverage_complete": False})
                return symbol, checked
            path = cache_root / "binance-usdm-v1" / symbol / "funding" / f"{requested_start}-{requested_end}.json"
            atomic_json(path, checked.pop("rows"))
            checked.update({"contract_status": statuses[symbol], "cache_path": str(path.resolve()), "cache_hash": file_hash(path)})
            return symbol, checked
        except Exception as error:  # Trust boundary: preserve per-symbol failure and stop after the cohort.
            return symbol, {"contract_status": "ERROR", "coverage_complete": False, "error": f"{type(error).__name__}: {error}"}

    with ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, workers))) as pool:
        futures = {pool.submit(one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, value = future.result()
            results[symbol] = value

    succeeded = [symbol for symbol in symbols if results[symbol].get("coverage_complete")]
    failed = [symbol for symbol in symbols if symbol not in succeeded]
    cache_hash = hashlib.sha256("".join(results[symbol].get("cache_hash", "") for symbol in symbols).encode()).hexdigest()
    manifest = {
        "milestone": "D4.8A", "d4_8_run_id": plan["run_id"], "stage_a_universe_hash": file_hash(universe_path),
        "requested_start": requested_start, "requested_end": requested_end, "evaluation_start": start, "evaluation_end": end,
        "boundary_buffer_ms": BUFFER_MS, "data_source": SOURCE, "source_endpoint": "GET /fapi/v1/fundingRate",
        "bridge_url": bridge_url, "symbols_requested": symbols, "symbols_succeeded": succeeded, "symbols_failed": failed,
        "record_counts": {symbol: results[symbol].get("record_count", 0) for symbol in symbols},
        "total_records": sum(int(results[symbol].get("record_count", 0)) for symbol in symbols), "symbols": results,
        "cache_hash": cache_hash, "completeness_verdict": "PASS" if not failed else "FAIL",
        "d4_8_missing_after_backfill": missing_for_plan(plan, cache_root),
        "stage_a_universe_changed": False, "strategy_logic_changed": False, "execution_semantics_changed": False,
        "stage_a_executed": False, "real_touched": False, "generated_at": datetime.now(UTC).isoformat(),
    }
    atomic_json(run_root / "funding_backfill_manifest.json", manifest)
    report_path = run_root / "funding_backfill_report.md"
    temporary = report_path.with_suffix(".md.tmp")
    temporary.write_text(_report_markdown(manifest), encoding="utf-8")
    temporary.replace(report_path)
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="D4.8A official historical funding cache backfill")
    result.add_argument("--run-id", required=True)
    result.add_argument("--state-root", default="state")
    result.add_argument("--cache-root", default="data/market")
    result.add_argument("--bridge-url", default="http://127.0.0.1:8766")
    result.add_argument("--workers", type=int, default=3)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        manifest = backfill(Path(args.state_root) / "transferability" / args.run_id, Path(args.cache_root), args.bridge_url, args.workers)
        print(json.dumps({"run_id": args.run_id, "status": manifest["completeness_verdict"], "symbols_succeeded": len(manifest["symbols_succeeded"]), "symbols_failed": len(manifest["symbols_failed"]), "records": manifest["total_records"], "data_ready_for_d4_8": not manifest["d4_8_missing_after_backfill"]}, sort_keys=True))
        return 0 if manifest["completeness_verdict"] == "PASS" else 2
    except (FileNotFoundError, json.JSONDecodeError, KeyError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
