from __future__ import annotations

import argparse
import json
import sys

from backtest_engine.data import iso_ms
from research_engine.research import run_research


def main() -> int:
    parser = argparse.ArgumentParser(prog="research", description="Trading Sentinel V4 D4 deterministic research pipeline")
    parser.add_argument("--dev-start", required=True); parser.add_argument("--dev-end", required=True)
    parser.add_argument("--oos-start", required=True); parser.add_argument("--oos-end", required=True)
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument("--symbols"); universe.add_argument("--verify-set", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--run-id"); parser.add_argument("--cache-root", default="data/market"); parser.add_argument("--state-root", default="state")
    args = parser.parse_args(); args.workers = max(1, min(8, args.workers)); args.parse_time = iso_ms
    try:
        print(json.dumps(run_research(args), sort_keys=True))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


raise SystemExit(main())
