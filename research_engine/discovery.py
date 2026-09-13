from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Iterable

from backtest_engine.cli import eligible_symbols
from backtest_engine.data import HistoricalDataStore, atomic_json, iso_ms
from backtest_engine.engine import stable_digest
from backtest_engine.model import Candle, CostModel, FundingEvent
from forensics_engine.analysis import DAY_MS
from research_engine.fvg import PacedBridgeClient


ENGINE_VERSION = "d4.5-signal-discovery-v3"
INTERVAL_MS = 300_000
HORIZONS = {"5m": 1, "15m": 3, "30m": 6, "1h": 12, "4h": 48}
SEGMENTS = ("DEV_A", "DEV_B", "DEV_C")
MINIMUM_ROUND_TRIP_COST_BPS = 2 * CostModel().taker_bps + CostModel().spread_bps + CostModel().slippage_bps
UNAVAILABLE = "HISTORICAL_FEATURE_NOT_AVAILABLE"


def oos_guard() -> None:
    raise PermissionError("locked OOS is outside D4.5")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def past_percentile(history: Iterable[float], current: float) -> float | None:
    known = list(history)
    if not known:
        return None
    return sum(value <= current for value in known) / len(known)


def rolling_percentile(values: list[float], index: int, window: int) -> float | None:
    if index <= 0:
        return None
    return past_percentile(values[max(0, index - window):index], values[index])


def align_past_value(events: list[tuple[int, float]], timestamp: int) -> tuple[int, float] | None:
    result = None
    for event in events:
        if event[0] > timestamp:
            break
        result = event
    return result


def universe_eligible(metadata: dict[str, Any], timestamp: int) -> bool:
    onboard = int(metadata.get("onboardDate") or metadata.get("onboard_date") or 0)
    delivery = int(metadata.get("deliveryDate") or metadata.get("delivery_date") or 0)
    return onboard <= timestamp and (not delivery or timestamp < delivery)


def temporal_segment(timestamp: int, start: int, end: int) -> str:
    width = max(1, (end - start) // 3)
    return SEGMENTS[min(2, max(0, (timestamp - start) // width))]


def cross_sectional_rank(values: dict[str, float], eligible: set[str]) -> dict[str, float]:
    ordered = sorted((value, symbol) for symbol, value in values.items() if symbol in eligible)
    if not ordered:
        return {}
    if len(ordered) == 1:
        return {ordered[0][1]: 0.5}
    return {symbol: index / (len(ordered) - 1) for index, (_, symbol) in enumerate(ordered)}


def forward_return_labels(candles: list[Candle], index: int) -> dict[str, float | None]:
    reference = candles[index].close
    return {
        horizon: candles[index + bars].close / reference - 1 if index + bars < len(candles) else None
        for horizon, bars in HORIZONS.items()
    }


def effective_sample(rows: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    stride = HORIZONS[horizon]
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)
    return [row for symbol in sorted(by_symbol) for index, row in enumerate(sorted(by_symbol[symbol], key=lambda item: item["timestamp"])) if index % stride == 0]


def feature_catalog() -> list[dict[str, Any]]:
    active = [
        ("return_5m", "PRICE_MOMENTUM", "5m closed return", "MOMENTUM_5M"),
        ("return_15m", "PRICE_MOMENTUM", "15m closed return", "MOMENTUM_15M"),
        ("return_1h", "PRICE_MOMENTUM", "1h closed return", "MOMENTUM_1H"),
        ("return_4h", "PRICE_MOMENTUM", "4h closed return", "MOMENTUM_4H"),
        ("distance_recent_high", "PRICE_LOCATION", "distance from trailing 4h high", "DISTANCE_HIGH"),
        ("distance_recent_low", "PRICE_LOCATION", "distance from trailing 4h low", "DISTANCE_LOW"),
        ("range_position", "PRICE_LOCATION", "position in trailing 4h range", "TERCILE"),
        ("volume_ratio", "VOLUME", "5m volume / prior 4h mean", "VOLUME_RATIO"),
        ("volume_zscore", "VOLUME", "5m volume z-score vs prior 4h", "ZSCORE"),
        ("quote_volume_ratio", "VOLUME", "5m quote-volume / prior 4h mean", "VOLUME_RATIO"),
        ("normalized_atr", "VOLATILITY", "12-bar ATR / close", "PAST_PERCENTILE"),
        ("realized_volatility", "VOLATILITY", "past-only 4h realized volatility", "PAST_PERCENTILE"),
        ("range_expansion", "VOLATILITY", "current range / prior 4h median range", "RANGE_RATIO"),
        ("funding_level", "FUNDING", "latest funding known at T", "FUNDING_LEVEL"),
        ("funding_percentile", "FUNDING", "funding percentile from earlier funding observations", "PERCENTILE_EXTREMES"),
        ("listing_age_days", "LISTING", "days since onboard date", "LISTING_AGE"),
        ("btc_return_regime", "MARKET_CONTEXT", "BTC 1h return known at T", "BTC_REGIME"),
        ("market_breadth", "MARKET_CONTEXT", "share of Universe(T) with positive 1h return", "TERCILE"),
        ("cross_sectional_median_return", "MARKET_CONTEXT", "Universe(T) median 1h return", "MOMENTUM_1H"),
        ("relative_strength_15m", "RELATIVE_STRENGTH", "15m return rank in Universe(T)", "TERCILE"),
        ("relative_strength_1h", "RELATIVE_STRENGTH", "1h return rank in Universe(T)", "TERCILE"),
        ("relative_strength_4h", "RELATIVE_STRENGTH", "4h return rank in Universe(T)", "TERCILE"),
    ]
    unavailable = [
        ("oi_change", "OPEN_INTEREST"), ("oi_percent_change", "OPEN_INTEREST"),
        ("premium_basis", "PREMIUM_BASIS"), ("historical_spread", "BBO_SPREAD"),
        ("historical_depth", "ORDER_BOOK_DEPTH"),
    ]
    return [
        {"id": feature_id, "family": family, "definition": definition, "bucket_rule": bucket, "availability": "AVAILABLE", "uses_future": False}
        for feature_id, family, definition, bucket in active
    ] + [
        {"id": feature_id, "family": family, "definition": UNAVAILABLE, "bucket_rule": None, "availability": UNAVAILABLE, "uses_future": False}
        for feature_id, family in unavailable
    ]


def bucket_value(rule: str, value: float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if rule.startswith("MOMENTUM_"):
        threshold = {"MOMENTUM_5M": .001, "MOMENTUM_15M": .002, "MOMENTUM_1H": .004, "MOMENTUM_4H": .008}[rule]
        return "DOWN" if value < -threshold else "UP" if value > threshold else "FLAT"
    if rule == "DISTANCE_HIGH":
        return "FAR_BELOW" if value < -.02 else "NEAR_HIGH" if value > -.005 else "MIDDLE"
    if rule == "DISTANCE_LOW":
        return "NEAR_LOW" if value < .005 else "FAR_ABOVE" if value > .02 else "MIDDLE"
    if rule == "TERCILE":
        return "LOW" if value < 1 / 3 else "HIGH" if value >= 2 / 3 else "NORMAL"
    if rule == "VOLUME_RATIO":
        return "LOW" if value < .75 else "HIGH" if value > 1.5 else "NORMAL"
    if rule == "ZSCORE":
        return "LOW" if value < -1 else "HIGH" if value > 1 else "NORMAL"
    if rule == "PAST_PERCENTILE":
        return "LOW" if value < .25 else "HIGH" if value >= .75 else "NORMAL"
    if rule == "RANGE_RATIO":
        return "COMPRESSION" if value < .75 else "EXPANSION" if value > 1.5 else "NORMAL"
    if rule == "FUNDING_LEVEL":
        return "NEGATIVE" if value < 0 else "POSITIVE" if value > 0 else "ZERO"
    if rule == "PERCENTILE_EXTREMES":
        return "EXTREME_NEGATIVE" if value <= .10 else "EXTREME_POSITIVE" if value >= .90 else "NORMAL"
    if rule == "LISTING_AGE":
        return "VERY_NEW" if value < 30 else "YOUNG" if value < 365 else "ESTABLISHED"
    if rule == "BTC_REGIME":
        return "BTC_BEARISH" if value < -.004 else "BTC_BULLISH" if value > .004 else "BTC_NEUTRAL"
    raise ValueError(f"unknown bucket rule: {rule}")


def data_capabilities(paths: set[str]) -> dict[str, Any]:
    available = lambda path: "AVAILABLE" if path in paths else UNAVAILABLE
    return {
        "price_ohlcv": {"5m": available("/api/v1/market/candles-window"), "15m": "DERIVED_CLOSED_ONLY", "1h": "DERIVED_CLOSED_ONLY", "4h": "DERIVED_CLOSED_ONLY"},
        "open_interest": {"historical": UNAVAILABLE, "sampling_interval": None, "current_snapshot": available("/api/v1/market/open-interest")},
        "funding": {"historical": available("/api/v1/market/funding-window"), "timestamps": "EXCHANGE_FUNDING_TIME"},
        "premium_basis": {"historical": UNAVAILABLE},
        "bbo_spread": {"historical": UNAVAILABLE, "current_snapshot": available("/api/v1/market/book")},
        "order_book_depth": {"historical": UNAVAILABLE, "current_snapshot": available("/api/v1/market/book")},
        "listing_metadata": {"onboard_date": available("/api/v1/market/universe"), "delivery_date": available("/api/v1/market/universe"), "contract_type": available("/api/v1/market/universe")},
        "market_universe": {"Universe(t)": "ONBOARD_DELIVERY_FILTERED_FROM_VERSIONED_PLAN_SNAPSHOT"},
        "historical_snapshot_prohibition": "CURRENT BBO, depth, ticker volume, and liquidity are excluded from feature rows",
    }


def _returns(closes: list[float], index: int, bars: int) -> float | None:
    return closes[index] / closes[index - bars] - 1 if index >= bars else None


def _std(values: list[float]) -> float:
    return pstdev(values) if len(values) > 1 else 0.0


def build_symbol_rows(symbol: str, candles: list[Candle], funding: list[FundingEvent], metadata: dict[str, Any], start: int, end: int) -> list[dict[str, Any]]:
    candles = sorted(candles, key=lambda item: item.open_time)
    closes, volumes = [item.close for item in candles], [item.volume for item in candles]
    quote_volumes = [item.volume * item.close for item in candles]
    returns_5m = [0.0] + [closes[index] / closes[index - 1] - 1 for index in range(1, len(candles))]
    true_ranges = [item.high - item.low for item in candles]
    normalized_atr = [mean(true_ranges[max(0, index - 11):index + 1]) / max(candles[index].close, 1e-12) for index in range(len(candles))]
    realized = [_std(returns_5m[max(1, index - 47):index + 1]) for index in range(len(candles))]
    funding_pairs = [(item.timestamp, item.rate) for item in sorted(funding, key=lambda item: item.timestamp)]
    prior_funding_rates: list[float] = []
    prior_funding_timestamp = -1
    rows = []
    for index, candle in enumerate(candles):
        timestamp = candle.close_time
        if timestamp < start or timestamp >= end or index < 48 or index + max(HORIZONS.values()) >= len(candles) or not universe_eligible(metadata, timestamp):
            continue
        trailing = candles[index - 47:index + 1]
        previous_volumes, previous_quotes = volumes[index - 48:index], quote_volumes[index - 48:index]
        previous_ranges = true_ranges[index - 48:index]
        high, low = max(item.high for item in trailing), min(item.low for item in trailing)
        known_funding = align_past_value(funding_pairs, timestamp)
        if known_funding and known_funding[0] != prior_funding_timestamp:
            if prior_funding_timestamp >= 0:
                prior_funding_rates.append(next(value for ts, value in funding_pairs if ts == prior_funding_timestamp))
            prior_funding_timestamp = known_funding[0]
        funding_level = known_funding[1] if known_funding else None
        funding_pct = past_percentile(prior_funding_rates, funding_level) if funding_level is not None else None
        features: dict[str, float | str | None] = {
            "return_5m": _returns(closes, index, 1), "return_15m": _returns(closes, index, 3),
            "return_1h": _returns(closes, index, 12), "return_4h": _returns(closes, index, 48),
            "distance_recent_high": candle.close / high - 1, "distance_recent_low": candle.close / low - 1,
            "range_position": (candle.close - low) / max(high - low, 1e-12),
            "volume_ratio": candle.volume / max(mean(previous_volumes), 1e-12),
            "volume_zscore": (candle.volume - mean(previous_volumes)) / max(_std(previous_volumes), 1e-12),
            "quote_volume_ratio": quote_volumes[index] / max(mean(previous_quotes), 1e-12),
            "normalized_atr": rolling_percentile(normalized_atr, index, 576),
            "realized_volatility": rolling_percentile(realized, index, 576),
            "range_expansion": true_ranges[index] / max(median(previous_ranges), 1e-12),
            "funding_level": funding_level, "funding_percentile": funding_pct,
            "listing_age_days": (timestamp - int(metadata.get("onboardDate") or 0)) / DAY_MS,
        }
        rows.append({
            "symbol": symbol, "timestamp": timestamp, "date": datetime.fromtimestamp(timestamp / 1000, UTC).strftime("%Y-%m-%d"),
            "segment": temporal_segment(timestamp, start, end), "reference_price": candle.close,
            "feature_observed_through": timestamp, "features": features, "labels": forward_return_labels(candles, index),
        })
    return rows


def add_cross_sectional_features(rows: list[dict[str, Any]], metadata: dict[str, dict[str, Any]], btc_rows: list[dict[str, Any]]) -> None:
    btc_by_time = {row["timestamp"]: row["features"].get("return_1h") for row in btc_rows}
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_time[row["timestamp"]].append(row)
    for timestamp, group in by_time.items():
        eligible = {symbol for symbol, item in metadata.items() if universe_eligible(item, timestamp)}
        returns = {window: {row["symbol"]: float(row["features"][f"return_{window}"]) for row in group if row["features"].get(f"return_{window}") is not None} for window in ("15m", "1h", "4h")}
        ranks = {window: cross_sectional_rank(values, eligible) for window, values in returns.items()}
        hourly = list(returns["1h"].values())
        market_median = median(hourly) if hourly else None
        breadth = sum(value > 0 for value in hourly) / len(hourly) if hourly else None
        for row in group:
            feature = row["features"]
            feature["btc_return_regime"] = btc_by_time.get(timestamp)
            feature["market_breadth"] = breadth
            feature["cross_sectional_median_return"] = market_median
            for window in ("15m", "1h", "4h"):
                feature[f"relative_strength_{window}"] = ranks[window].get(row["symbol"])


def block_confidence_interval(rows: list[dict[str, Any]], horizon: str, seed_key: str, iterations: int = 200) -> list[float]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row["labels"].get(horizon)
        if value is not None:
            by_date[row["date"]].append(float(value))
    blocks = [mean(values) for _, values in sorted(by_date.items()) if values]
    if not blocks:
        return [0.0, 0.0]
    rng = random.Random(int(hashlib.sha256(seed_key.encode()).hexdigest()[:16], 16))
    samples = [mean(rng.choice(blocks) for _ in blocks) for _ in range(iterations)]
    return [percentile(samples, .025), percentile(samples, .975)]


def temporal_classification(segment_means: dict[str, float]) -> str:
    values = [segment_means.get(segment, 0.0) for segment in SEGMENTS]
    nonzero = [value for value in values if value]
    if any(value > 0 for value in nonzero) and any(value < 0 for value in nonzero):
        return "SIGN_FLIP"
    magnitudes = [abs(value) for value in values]
    if sum(magnitudes) and max(magnitudes) / sum(magnitudes) > .60:
        return "TEMPORALLY_CONCENTRATED"
    if nonzero and len(nonzero) == 3:
        return "TEMPORALLY_STABLE"
    return "TEMPORALLY_WEAK"


def symbol_breadth(rows: list[dict[str, Any]], horizon: str, direction: int) -> dict[str, Any]:
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row["labels"].get(horizon)
        if value is not None:
            by_symbol[row["symbol"]].append(float(value))
    effects = {symbol: mean(values) for symbol, values in by_symbol.items() if values}
    aligned = {symbol: effect for symbol, effect in effects.items() if direction * effect > 0}
    opposite = {symbol: effect for symbol, effect in effects.items() if direction * effect < 0}
    contributions = sorted((abs(effect) * len(by_symbol[symbol]), symbol) for symbol, effect in aligned.items())
    contributions.reverse()
    total = sum(value for value, _ in contributions)
    share = lambda count: sum(value for value, _ in contributions[:count]) / total if total else 0.0
    return {
        "active_symbol_count": len(effects), "profitable_direction_symbol_count": len(aligned),
        "opposite_direction_symbol_count": len(opposite), "median_per_symbol_effect": median(effects.values()) if effects else 0.0,
        "top_symbol": contributions[0][1] if contributions else None, "top_symbol_contribution": share(1),
        "top_3_contribution": share(3), "top_5_contribution": share(5),
    }


def summarize_slice(rows: list[dict[str, Any]], feature_id: str, bucket: str, horizon: str) -> dict[str, Any]:
    values = [float(row["labels"][horizon]) for row in rows if row["labels"].get(horizon) is not None]
    effective = effective_sample(rows, horizon)
    effective_values = [float(row["labels"][horizon]) for row in effective if row["labels"].get(horizon) is not None]
    average = mean(values) if values else 0.0
    deviation = _std(values)
    direction = 1 if average >= 0 else -1
    segments = {segment: mean(segment_values) if segment_values else 0.0 for segment in SEGMENTS for segment_values in [[float(row["labels"][horizon]) for row in rows if row["segment"] == segment and row["labels"].get(horizon) is not None]]}
    breadth = symbol_breadth(rows, horizon, direction)
    confidence = block_confidence_interval(effective, horizon, f"{feature_id}:{bucket}:{horizon}")
    temporal = temporal_classification(segments)
    cost_state = "ABOVE_COST_HURDLE" if abs(average) * 10_000 > MINIMUM_ROUND_TRIP_COST_BPS * 1.5 else "MARGINAL_VS_COST" if abs(average) * 10_000 >= MINIMUM_ROUND_TRIP_COST_BPS else "BELOW_COST_HURDLE"
    score = min(abs(average) / .002, 1) * 30 + min(len(effective_values) / 1000, 1) * 15
    score += 15 if confidence[0] > 0 or confidence[1] < 0 else 0
    score += 20 if temporal == "TEMPORALLY_STABLE" else 8 if temporal == "TEMPORALLY_WEAK" else 0
    score += min(breadth["active_symbol_count"] / 10, 1) * 10
    score += (breadth["profitable_direction_symbol_count"] / max(1, breadth["active_symbol_count"])) * 10
    if len(effective_values) < 100 or breadth["active_symbol_count"] < 3:
        status = "INSUFFICIENT_DATA"
    elif abs(average) < .0005:
        status = "NO_EDGE"
    elif temporal in {"SIGN_FLIP", "TEMPORALLY_CONCENTRATED"} or breadth["top_symbol_contribution"] > .50:
        status = "UNSTABLE"
    elif cost_state != "ABOVE_COST_HURDLE" or not (confidence[0] > 0 or confidence[1] < 0) or breadth["profitable_direction_symbol_count"] / max(1, breadth["active_symbol_count"]) < .60:
        status = "WEAK_EVIDENCE"
    else:
        status = "PROMISING_SIGNAL"
    return {
        "finding_id": f"{feature_id}:{bucket}:{horizon}", "feature": feature_id, "bucket": bucket, "horizon": horizon,
        "direction": "POSITIVE" if direction > 0 else "NEGATIVE", "observation_count": len(values),
        "effective_observation_count": len(effective_values), "symbol_count": breadth["active_symbol_count"],
        "date_count": len({row["date"] for row in effective}), "mean_forward_return": average,
        "median_forward_return": median(values) if values else 0.0, "hit_rate_positive": sum(value > 0 for value in values) / len(values) if values else 0.0,
        "direction_hit_rate": sum(direction * value > 0 for value in values) / len(values) if values else 0.0,
        "standard_deviation": deviation, "negative_tail_p05": percentile(values, .05), "positive_tail_p95": percentile(values, .95),
        "block_bootstrap_95_ci": confidence, "effect_size": average / deviation if deviation else 0.0,
        "temporal_means": segments, "temporal_classification": temporal, "breadth": breadth,
        "minimum_round_trip_cost_hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS, "cost_hurdle_state": cost_state,
        "discovery_score": round(score, 6), "discovery_status": status,
    }


def analyze_features(rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for feature in catalog:
        if feature["availability"] != "AVAILABLE":
            results.append({"feature": feature["id"], "discovery_status": "FEATURE_UNAVAILABLE", "reason": UNAVAILABLE})
            continue
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bucket = bucket_value(feature["bucket_rule"], row["features"].get(feature["id"]))
            if bucket is not None:
                groups[bucket].append(row)
        for bucket, group in sorted(groups.items()):
            for horizon in HORIZONS:
                results.append(summarize_slice(group, feature["id"], bucket, horizon))
    return results


INTERACTIONS = (
    ("return_1h", "volume_ratio", "MOMENTUM_1H_X_VOLUME_EXPANSION"),
    ("funding_percentile", "return_1h", "FUNDING_EXTREME_X_PRICE_EXTENSION"),
    ("relative_strength_1h", "btc_return_regime", "RELATIVE_STRENGTH_X_BTC_REGIME"),
    ("return_1h", "range_expansion", "MOMENTUM_X_VOLATILITY_REGIME"),
)


def analyze_interactions(rows: list[dict[str, Any]], catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = {item["id"]: item for item in catalog}
    results = []
    for left, right, interaction_id in INTERACTIONS:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            left_bucket = bucket_value(definitions[left]["bucket_rule"], row["features"].get(left))
            right_bucket = bucket_value(definitions[right]["bucket_rule"], row["features"].get(right))
            if left_bucket is not None and right_bucket is not None:
                groups[f"{left_bucket} × {right_bucket}"].append(row)
        for bucket, group in sorted(groups.items()):
            for horizon in HORIZONS:
                results.append(summarize_slice(group, interaction_id, bucket, horizon))
    return results


def rank_findings(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [item for item in results if "finding_id" in item]
    return sorted(ranked, key=lambda item: (-float(item["discovery_score"]), item["finding_id"]))


def _cache_partition(cache_root: Path, symbol: str, day: int) -> Path:
    date = datetime.fromtimestamp(day / 1000, UTC).strftime("%Y-%m-%d")
    return cache_root / "binance-usdm-v1" / symbol / "5m" / f"{date}.jsonl.gz"


def _funding_cache_covers(cache_root: Path, symbol: str, start: int, end: int) -> bool:
    folder = cache_root / "binance-usdm-v1" / symbol / "funding"
    for candidate in folder.glob("*.json") if folder.exists() else []:
        try:
            cached_start, cached_end = (int(value) for value in candidate.stem.split("-", 1))
        except ValueError:
            continue
        if cached_start <= start and cached_end >= end:
            return True
    return False


def resource_plan(start: int, end: int, workers: int, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    bridge = PacedBridgeClient(bridge_url)
    universe = bridge.universe()
    openapi = bridge.get("/openapi.json")
    paths = set(openapi.get("paths", {}))
    capabilities = data_capabilities(paths)
    eligible, base_exclusions = eligible_symbols(universe, start, end)
    days = list(range((start - 3 * DAY_MS) // DAY_MS * DAY_MS, math.ceil(end / DAY_MS) * DAY_MS, DAY_MS))
    candidates = [item for item in eligible if item.get("quoteAsset") == "USDT" and int(item.get("onboardDate") or 0) <= start - 3 * DAY_MS]
    coverage = {str(item["symbol"]): sum(_cache_partition(cache_root, str(item["symbol"]), day).exists() for day in days) / len(days) for item in candidates}
    selected = sorted((item for item in candidates if coverage[str(item["symbol"])] >= .90), key=lambda item: str(item["symbol"]))
    if len(selected) < 6:
        raise ValueError("fewer than six dynamic Universe(t) symbols have sufficient Development cache coverage")
    snapshot = [{
        "symbol": str(item["symbol"]), "onboardDate": int(item.get("onboardDate") or 0),
        "deliveryDate": int(item.get("deliveryDate") or 0), "contractType": item.get("contractType"),
        "quoteAsset": item.get("quoteAsset"), "marginAsset": item.get("marginAsset"),
        "cache_coverage": coverage[str(item["symbol"])],
        "current_snapshot_metadata": {"quote_volume_24h": item.get("quoteVolume24h"), "predictive_feature": False},
    } for item in selected]
    symbols = [item["symbol"] for item in snapshot]
    context_symbols = ["BTCUSDT"]
    all_load_symbols = sorted(set(symbols + context_symbols))
    candle_parts = [(symbol, day) for symbol in all_load_symbols for day in days]
    cached_candles = sum(_cache_partition(cache_root, symbol, day).exists() for symbol, day in candle_parts)
    funding_start = start - 3 * DAY_MS
    funding_cached = sum(_funding_cache_covers(cache_root, symbol, funding_start, end) for symbol in symbols)
    expected_candles = len(symbols) * ((end - start) // INTERVAL_MS)
    catalog = feature_catalog()
    identity = {"engine": ENGINE_VERSION, "development": {"start": start, "end": end}, "symbols": snapshot, "feature_catalog": catalog, "horizons": HORIZONS}
    run_id = f"d4_5_{stable_digest(identity)[:16]}"
    exclusions = list(base_exclusions) + [{"symbol": str(item["symbol"]), "reason": "INSUFFICIENT_LOCAL_DEVELOPMENT_CACHE"} for item in candidates if item not in selected]
    return {
        "run_id": run_id, "identity_hash": stable_digest(identity), "engine_version": ENGINE_VERSION,
        "phase": "SIGNAL_DISCOVERY_DEVELOPMENT_ONLY", "development_window": {"start": start, "end": end},
        "warmup_start": start - 3 * DAY_MS, "label_lookahead_end": end + 4 * 3_600_000,
        "symbol_count": len(symbols), "symbols": symbols, "context_symbols": context_symbols,
        "universe_snapshot": snapshot, "universe_method": "DYNAMIC_BRIDGE_REGISTRY_UNIVERSE_T_ONBOARD_DELIVERY_PLUS_SUFFICIENT_LOCAL_HISTORY",
        "universe_eligible_count": len(candidates), "exclusions": exclusions,
        "feature_catalog": catalog, "feature_catalog_count": len(catalog), "available_feature_count": sum(item["availability"] == "AVAILABLE" for item in catalog),
        "horizons": list(HORIZONS), "expected_5m_candle_count": expected_candles,
        "data_capabilities": capabilities,
        "oi_coverage": {"status": UNAVAILABLE, "symbols": 0},
        "funding_coverage": {"status": "AVAILABLE", "cached_symbols": funding_cached, "total_symbols": len(symbols)},
        "cache": {"cached_partitions": cached_candles + funding_cached, "total_partitions": len(candle_parts) + len(symbols), "hit_rate": (cached_candles + funding_cached) / max(1, len(candle_parts) + len(symbols))},
        "estimated_bridge_requests": len(candle_parts) + len(symbols) - cached_candles - funding_cached,
        "worker_count": max(1, min(4, workers)), "expected_disk_bytes": int(expected_candles * 165),
        "cost_model": "NOT_APPLICABLE_RAW_FORWARD_RETURN_RESEARCH", "minimum_round_trip_cost_hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS,
        "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    }


def save_plan(plan: dict[str, Any], state_root: Path) -> Path:
    root = state_root / "signal-discovery" / plan["run_id"]
    plan_path = root / "resource-plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8"))["identity_hash"] != plan["identity_hash"]:
        raise ValueError("immutable D4.5 plan collision")
    if not plan_path.exists():
        atomic_json(plan_path, plan)
        atomic_json(root / "data-capabilities.json", plan["data_capabilities"])
        atomic_json(root / "universe.json", {key: plan[key] for key in ("universe_method", "universe_eligible_count", "universe_snapshot", "exclusions")})
        atomic_json(root / "feature-catalog.json", {"frozen_before_evaluation": True, "catalog": plan["feature_catalog"], "interactions": [list(item) for item in INTERACTIONS]})
    return root


def _atomic_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as target:
        json.dump(value, target, sort_keys=True, separators=(",", ":"))
    os.replace(temporary, path)


def _read_gzip_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def _load_symbol(symbol: str, plan: dict[str, Any], cache_root: Path, bridge_url: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start, end = plan["development_window"]["start"], plan["development_window"]["end"]
    load_end = end + 4 * 3_600_000
    store = HistoricalDataStore(cache_root, PacedBridgeClient(bridge_url))
    candles, manifests = store.candles(symbol, "5m", plan["warmup_start"], load_end)
    funding = store.funding(symbol, plan["warmup_start"], end)
    metadata = next(item for item in plan["universe_snapshot"] if item["symbol"] == symbol)
    rows = build_symbol_rows(symbol, candles, funding, metadata, start, end)
    quality = {"symbol": symbol, "candles": len(candles), "rows": len(rows), "funding_events": len(funding), "cache_hits": store.cache_hits, "downloads": store.downloads, "dataset_ids": [item["dataset_id"] for item in manifests]}
    return rows, quality


def _listing_analysis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        bucket = bucket_value("LISTING_AGE", row["features"].get("listing_age_days"))
        if bucket:
            groups[bucket].append(row)
    result = []
    for bucket, group in sorted(groups.items()):
        volatility = [float(row["features"]["realized_volatility"]) for row in group if row["features"].get("realized_volatility") is not None]
        result.append({"age_bucket": bucket, "observation_count": len(group), "symbol_count": len({row["symbol"] for row in group}), "realized_volatility_percentile_mean": mean(volatility) if volatility else None, "forward_returns": {horizon: {"mean": mean(values) if values else 0.0, "median": median(values) if values else 0.0, "positive_hit_rate": sum(value > 0 for value in values) / len(values) if values else 0.0} for horizon in HORIZONS for values in [[float(row["labels"][horizon]) for row in group if row["labels"].get(horizon) is not None]]}, "oi_behavior": UNAVAILABLE})
    return result


def _report(plan: dict[str, Any], ranking: list[dict[str, Any]], quality: list[dict[str, Any]]) -> str:
    promising = [item for item in ranking if item["discovery_status"] == "PROMISING_SIGNAL"]
    lines = [
        "# D4.5 Signal Discovery Report", "", "**NOT A TRADING STRATEGY.** No entries, stops, targets, or OOS evaluation were produced.", "",
        f"- Run: `{plan['run_id']}`", f"- Development: {datetime.fromtimestamp(plan['development_window']['start'] / 1000, UTC).isoformat()} to {datetime.fromtimestamp(plan['development_window']['end'] / 1000, UTC).isoformat()}",
        f"- Universe(t): {plan['symbol_count']} usable symbols from {plan['universe_eligible_count']} eligible contracts", f"- Feature catalog: {plan['available_feature_count']} available / {plan['feature_catalog_count']} registered", f"- Horizons: {', '.join(plan['horizons'])}",
        f"- OI: {UNAVAILABLE}", "- Historical BBO/depth/premium: HISTORICAL_FEATURE_NOT_AVAILABLE", f"- OOS: {plan['oos_access']}", "",
        "## Promising signals", "",
    ]
    if not promising:
        lines.append("No finding passed the predeclared effect, confidence, breadth, concentration, temporal, and cost-hurdle gates.")
    for item in promising[:20]:
        lines.append(f"- `{item['feature']} / {item['bucket']} / {item['horizon']}`: {item['direction']} mean {item['mean_forward_return'] * 10_000:.2f} bps, n={item['effective_observation_count']}, symbols={item['symbol_count']}, {item['temporal_classification']}, {item['cost_hurdle_state']}")
    lines += ["", "## Data quality", "", f"- Feature rows: {sum(item['rows'] for item in quality):,}", f"- Funding events: {sum(item['funding_events'] for item in quality):,}", f"- Downloads during execution: {sum(item['downloads'] for item in quality):,}", "- Current ticker volume, BBO, and depth were not placed in historical feature rows.", ""]
    return "\n".join(lines)


def execute(run_id: str, state_root: Path, cache_root: Path, bridge_url: str) -> dict[str, Any]:
    root = state_root / "signal-discovery" / run_id
    plan = json.loads((root / "resource-plan.json").read_text(encoding="utf-8"))
    ranking_path = root / "discovery-ranking.json"
    if ranking_path.exists():
        ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
        return {"run_id": run_id, "status": "ALREADY_COMPLETED", "promising_signal_count": ranking["status_counts"].get("PROMISING_SIGNAL", 0), "artifact": str(root.resolve())}
    checkpoint_path = root / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"identity_hash": plan["identity_hash"], "completed_symbols": []}
    if checkpoint["identity_hash"] != plan["identity_hash"]:
        raise ValueError("immutable D4.5 checkpoint collision")
    completed = set(checkpoint["completed_symbols"])
    work = root / "work"
    pending = [symbol for symbol in plan["symbols"] if symbol not in completed]
    with ThreadPoolExecutor(max_workers=plan["worker_count"]) as pool:
        futures = {pool.submit(_load_symbol, symbol, plan, cache_root, bridge_url): symbol for symbol in pending}
        for future in as_completed(futures):
            symbol = futures[future]
            rows, quality = future.result()
            _atomic_gzip_json(work / f"{symbol}.rows.json.gz", rows)
            atomic_json(work / f"{symbol}.quality.json", quality)
            completed.add(symbol)
            atomic_json(checkpoint_path, {"identity_hash": plan["identity_hash"], "completed_symbols": sorted(completed)})
            print(json.dumps({"run_id": run_id, "completed": len(completed), "total": len(plan["symbols"]), "symbol": symbol}))
    start, end = plan["development_window"]["start"], plan["development_window"]["end"]
    btc_store = HistoricalDataStore(cache_root, PacedBridgeClient(bridge_url))
    btc_candles, btc_manifests = btc_store.candles("BTCUSDT", "5m", plan["warmup_start"], end + 4 * 3_600_000)
    btc_meta = next((item for item in plan["universe_snapshot"] if item["symbol"] == "BTCUSDT"), {"symbol": "BTCUSDT", "onboardDate": 1567965300000, "deliveryDate": 4133404800000})
    btc_rows = build_symbol_rows("BTCUSDT", btc_candles, [], btc_meta, start, end)
    rows = [row for symbol in sorted(plan["symbols"]) for row in _read_gzip_json(work / f"{symbol}.rows.json.gz")]
    metadata = {item["symbol"]: item for item in plan["universe_snapshot"]}
    add_cross_sectional_features(rows, metadata, btc_rows)
    catalog = plan["feature_catalog"]
    single = analyze_features(rows, catalog)
    interactions = analyze_interactions(rows, catalog)
    ranking = rank_findings(single + interactions)
    status_counts = Counter(item["discovery_status"] for item in single + interactions)
    horizons = {horizon: summarize_slice(rows, "UNCONDITIONAL", "ALL", horizon) for horizon in HORIZONS}
    quality = [json.loads((work / f"{symbol}.quality.json").read_text(encoding="utf-8")) for symbol in sorted(plan["symbols"])]
    dataset_version = stable_digest(sorted(dataset_id for item in quality for dataset_id in item["dataset_ids"]) + [item["dataset_id"] for item in btc_manifests])
    atomic_json(root / "single-feature-results.json", single)
    atomic_json(root / "interaction-results.json", interactions)
    atomic_json(root / "horizon-results.json", horizons)
    atomic_json(root / "long-short-asymmetry.json", [{key: item[key] for key in ("finding_id", "direction", "mean_forward_return", "direction_hit_rate", "horizon", "discovery_status")} for item in ranking])
    atomic_json(root / "temporal-stability.json", [{"finding_id": item["finding_id"], "segments": item["temporal_means"], "classification": item["temporal_classification"]} for item in ranking])
    atomic_json(root / "symbol-breadth.json", [{"finding_id": item["finding_id"], **item["breadth"]} for item in ranking])
    atomic_json(root / "new-listing-analysis.json", _listing_analysis(rows))
    atomic_json(root / "discovery-ranking.json", {"formula": "30 magnitude + 15 effective sample + 15 block-CI + 20 temporal + 10 symbol count + 10 direction breadth", "status_counts": dict(status_counts), "ranked_findings": ranking})
    manifest = {
        "run_id": run_id, "identity_hash": plan["identity_hash"], "status": "COMPLETED", "phase": "SIGNAL_DISCOVERY_DEVELOPMENT_ONLY",
        "engine_version": ENGINE_VERSION, "dataset_version": dataset_version, "development_window": plan["development_window"],
        "universe_method": plan["universe_method"], "symbols": plan["universe_snapshot"], "feature_catalog_hash": stable_digest(catalog),
        "horizons": plan["horizons"], "observation_count": len(rows), "effective_observation_counts": {horizon: len(effective_sample(rows, horizon)) for horizon in HORIZONS},
        "cost_model": "NOT_APPLICABLE_RAW_FORWARD_RETURN_RESEARCH", "minimum_round_trip_cost_hurdle_bps": MINIMUM_ROUND_TRIP_COST_BPS,
        "current_snapshot_features_used": False, "lookahead_validation": "FEATURE_OBSERVED_THROUGH_LE_T_AND_LABELS_STRICTLY_AFTER_T",
        "oos_access": "OOS_NOT_ACCESSED", "locked_oos_resolved_or_read": False,
    }
    atomic_json(root / "manifest.json", manifest)
    (root / "discovery-report.md").write_text(_report(plan, ranking, quality), encoding="utf-8")
    return {"run_id": run_id, "status": "COMPLETED", "symbols": len(plan["symbols"]), "observations": len(rows), "promising_signal_count": status_counts.get("PROMISING_SIGNAL", 0), "artifact": str(root.resolve())}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Trading Sentinel V4 D4.5 Development-only signal discovery")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--dev-start", required=True); plan.add_argument("--dev-end", required=True)
    plan.add_argument("--workers", type=int, default=3); plan.add_argument("--state-root", default="state"); plan.add_argument("--cache-root", default="data/market")
    run = commands.add_parser("execute")
    run.add_argument("--run-id", required=True); run.add_argument("--state-root", default="state"); run.add_argument("--cache-root", default="data/market")
    return root


def main() -> int:
    args = parser().parse_args()
    state_root, cache_root = Path(args.state_root), Path(args.cache_root)
    bridge_url = os.getenv("MARKET_DATA_BASE_URL", "http://127.0.0.1:8766")
    try:
        if args.command == "plan":
            start, end = iso_ms(args.dev_start), iso_ms(args.dev_end)
            if end <= start:
                raise ValueError("--dev-end must be after --dev-start")
            plan = resource_plan(start, end, args.workers, state_root, cache_root, bridge_url)
            save_plan(plan, state_root)
            print(json.dumps(plan, sort_keys=True))
        else:
            print(json.dumps(execute(args.run_id, state_root, cache_root, bridge_url), sort_keys=True))
        return 0
    except (FileNotFoundError, KeyError, PermissionError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
