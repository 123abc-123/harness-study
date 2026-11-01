"""Synthetic import smoke benchmark; not a real JEDEC workload or a peak-RAM measurement."""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kg_harness.runtime import Runtime

parser = argparse.ArgumentParser()
parser.add_argument("--mb", type=int, default=40)
parser.add_argument("--result", help="Optional JSON result path")
args = parser.parse_args()
if not 1 <= args.mb <= 500:
    parser.error("--mb must be 1..500")
root = Path(__file__).resolve().parent.parent / ".test-workspace" / ("benchmark-" + uuid.uuid4().hex[:8])
runtime = Runtime(root)
source = root / "inputs/synthetic.json"
count = args.mb * 1024 * 1024 // 16000
with source.open("w", encoding="utf-8") as stream:
    stream.write('{"schema_version":1,"standard":"SYNTHETIC-BENCHMARK","version":"bench","provenance":{"synthetic":true},"sections":[')
    for index in range(count):
        if index:
            stream.write(",")
        json.dump({"stable_key": f"section_{index}", "number": str(index),
                   "title": f"Section {index}", "text": "synthetic data. " * 1000}, stream)
    stream.write("]}")
start = time.perf_counter()
result = runtime.kg.import_file(source)
elapsed = time.perf_counter() - start
metrics = {"input_bytes": source.stat().st_size, "records": result["records"],
           "seconds": round(elapsed, 3), "query_hits": len(runtime.kg.search_kg("bench", "Section")["hits"]),
           "workspace": str(root), "synthetic": True}
if args.result:
    Path(args.result).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
print(json.dumps(metrics, indent=2))
