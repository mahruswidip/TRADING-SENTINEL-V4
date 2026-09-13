from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .model import Candle, FundingEvent


DAY_MS = 86_400_000
INTERVAL_MS = {"1m": 60_000, "5m": 300_000}


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


class BridgeClient:
    def __init__(self, base_url: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, path: str, **params: object) -> dict[str, Any]:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}" if params else f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise RuntimeError(f"market-data bridge returned HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt == 2: raise RuntimeError(f"market-data bridge unavailable: {type(exc).__name__}") from exc
            time.sleep(.25 * 2 ** attempt)
        if not isinstance(payload, dict):
            raise RuntimeError("invalid market-data bridge response")
        return payload

    def universe(self) -> dict[str, Any]:
        return self.get("/api/v1/market/universe")

    def candles(self, symbol: str, interval: str, start: int, end: int, limit: int = 1500) -> list[list[object]]:
        payload = self.get("/api/v1/market/candles-window", symbol=symbol, interval=interval, startTime=start, endTime=end - 1, limit=limit)
        rows = payload.get("candles")
        if payload.get("symbol") != symbol or payload.get("interval") != interval or not isinstance(rows, list):
            raise RuntimeError("invalid candle-window contract")
        return rows

    def funding(self, symbol: str, start: int, end: int) -> list[dict[str, object]]:
        payload = self.get("/api/v1/market/funding-window", symbol=symbol, startTime=start, endTime=end - 1, limit=1000)
        rows = payload.get("funding")
        if payload.get("symbol") != symbol or not isinstance(rows, list):
            raise RuntimeError("invalid funding-window contract")
        return rows


def gap_count(candles: list[Candle], interval_ms: int) -> int:
    return sum(right.open_time - left.open_time != interval_ms for left, right in zip(candles, candles[1:]))


class HistoricalDataStore:
    schema_version = 1

    def __init__(self, root: Path, bridge: BridgeClient) -> None:
        self.root = root
        self.bridge = bridge
        self.cache_hits = 0
        self.downloads = 0

    def _partition(self, symbol: str, interval: str, day_start: int) -> tuple[Path, Path]:
        date = datetime.fromtimestamp(day_start / 1000, UTC).strftime("%Y-%m-%d")
        folder = self.root / "binance-usdm-v1" / symbol / interval
        return folder / f"{date}.jsonl.gz", folder / f"{date}.manifest.json"

    def _read(self, path: Path) -> list[Candle]:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return [Candle(**json.loads(line)) for line in source if line.strip()]

    def _download_day(self, symbol: str, interval: str, day_start: int) -> tuple[list[Candle], dict[str, object]]:
        day_end = day_start + DAY_MS
        rows: list[list[object]] = []
        cursor = day_start
        while cursor < day_end:
            batch = self.bridge.candles(symbol, interval, cursor, day_end)
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0]) + INTERVAL_MS[interval]
            if next_cursor <= cursor:
                raise RuntimeError("candle pagination did not advance")
            cursor = next_cursor
            if len(batch) < 1500:
                break
        candles_by_time: dict[int, Candle] = {}
        for row in rows:
            candle = Candle.from_row(row)
            if day_start <= candle.open_time < day_end:
                candles_by_time[candle.open_time] = candle
        candles = sorted(candles_by_time.values(), key=lambda item: item.open_time)
        downloaded_at = datetime.now(UTC).isoformat()
        content_digest = hashlib.sha256(json.dumps([item.as_dict() for item in candles], sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
        manifest = {
            "dataset_id": content_digest,
            "provider": "TRADING_SENTINEL_V2_MARKET_BRIDGE", "market": "BINANCE_USDS_M_FUTURES", "symbol": symbol,
            "timeframe": interval, "start": day_start, "end": day_end, "row_count": len(candles), "downloaded_at": downloaded_at,
            "first_timestamp": candles[0].open_time if candles else None, "last_timestamp": candles[-1].open_time if candles else None,
            "gap_count": gap_count(candles, INTERVAL_MS[interval]), "source": "BINANCE_PUBLIC_VIA_V2", "schema_version": self.schema_version,
        }
        return candles, manifest

    def candles(self, symbol: str, interval: str, start: int, end: int) -> tuple[list[Candle], list[dict[str, object]]]:
        if interval not in INTERVAL_MS or end <= start:
            raise ValueError("invalid cache request")
        candles: list[Candle] = []
        manifests: list[dict[str, object]] = []
        day = start - start % DAY_MS
        while day < end:
            data_path, manifest_path = self._partition(symbol, interval, day)
            if data_path.exists() and manifest_path.exists():
                part = self._read(data_path)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.cache_hits += 1
            else:
                part, manifest = self._download_day(symbol, interval, day)
                data_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = data_path.with_suffix(data_path.suffix + ".tmp")
                with gzip.open(temporary, "wt", encoding="utf-8") as target:
                    for candle in part:
                        target.write(json.dumps(candle.as_dict(), sort_keys=True) + "\n")
                os.replace(temporary, data_path)
                atomic_json(manifest_path, manifest)
                self.downloads += 1
            candles.extend(item for item in part if start <= item.open_time < end)
            manifests.append(manifest)
            day += DAY_MS
        return sorted({item.open_time: item for item in candles}.values(), key=lambda item: item.open_time), manifests

    def funding(self, symbol: str, start: int, end: int) -> list[FundingEvent]:
        folder = self.root / "binance-usdm-v1" / symbol / "funding"
        path = folder / f"{start}-{end}.json"
        if not path.exists():
            for candidate in sorted(folder.glob("*.json")) if folder.exists() else []:
                try:
                    cached_start, cached_end = (int(value) for value in candidate.stem.split("-", 1))
                except ValueError:
                    continue
                if cached_start <= start and cached_end >= end:
                    path = candidate
                    break
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            self.cache_hits += 1
        else:
            rows = self.bridge.funding(symbol, start, end)
            atomic_json(path, rows)
            self.downloads += 1
        events = []
        for row in rows:
            try:
                timestamp, rate = int(row["fundingTime"]), float(row["fundingRate"])
                if start <= timestamp < end:
                    events.append(FundingEvent(timestamp, rate))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(events, key=lambda item: item.timestamp)


def iso_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)
