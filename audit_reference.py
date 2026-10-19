from __future__ import annotations

import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config_path = ROOT / "config" / "data_sources.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = config["reference_only"]
    root = Path(os.getenv(source["root_env"], source["default_root"])).expanduser()
    manifest = root / source["manifest"]
    page_index = root / source["page_index"]
    result = {
        "reference_root": str(root),
        "reference_root_exists": root.exists(),
        "manifest": str(manifest),
        "manifest_exists": manifest.exists(),
        "page_index": str(page_index),
        "page_index_exists": page_index.exists(),
        "manifest_rows": None,
        "project_index_files": sorted(str(path.relative_to(ROOT)) for path in (ROOT / "artifacts").glob("*.jsonl")),
        "policy": source["policy"],
    }
    if manifest.exists():
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            result["manifest_rows"] = sum(1 for _row in csv.DictReader(handle))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["reference_root_exists"] and result["manifest_exists"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

