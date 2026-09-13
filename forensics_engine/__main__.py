from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forensics_engine.analysis import run_forensics
from forensics_engine.validation import run_development_validation

parser = argparse.ArgumentParser(description="Trading Sentinel V4 D4.1 development-only strategy forensics")
parser.add_argument("--research-run", required=True)
parser.add_argument("--state-root", default="state")
parser.add_argument("--cache-root", default="data/market")
parser.add_argument("--validate-development", action="store_true")
args = parser.parse_args()
try:
    result = run_forensics(args.research_run, Path(args.state_root), Path(args.cache_root))
    if args.validate_development: result["development_validation"] = run_development_validation(args.research_run, Path(args.state_root), Path(args.cache_root))
    print(json.dumps(result, sort_keys=True))
except (FileNotFoundError, KeyError, RuntimeError, ValueError) as error:
    print(f"error: {error}", file=sys.stderr)
    raise SystemExit(2)
