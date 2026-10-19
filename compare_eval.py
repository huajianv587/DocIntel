from __future__ import annotations

import argparse
import json

from docintel.evaluation import compare_reports
from docintel.io import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two DocIntel evaluation reports")
    parser.add_argument("current")
    parser.add_argument("baseline")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.current, "r", encoding="utf-8") as handle:
        current = json.load(handle)
    with open(args.baseline, "r", encoding="utf-8") as handle:
        baseline = json.load(handle)
    write_json(args.output, compare_reports(current, baseline))
    print(json.dumps(compare_reports(current, baseline), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
