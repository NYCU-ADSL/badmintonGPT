#!/usr/bin/env python3
"""Local-only export of saved ratings; no public administrator endpoint."""
import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "data/ratings.sqlite3")
parser.add_argument("--format", choices=["json", "csv"], default="csv")
parser.add_argument("--dataset")
args = parser.parse_args()
db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
sql = "SELECT * FROM ratings"
rows = [dict(r) for r in db.execute(sql + (" WHERE dataset_id=?" if args.dataset else "") +
                                    " ORDER BY dataset_id,evaluator_code,item_id", (args.dataset,) if args.dataset else ())]
if args.format == "json":
    print(json.dumps(rows, ensure_ascii=False, indent=2))
else:
    writer = csv.DictWriter(sys.stdout, fieldnames=["dataset_id", "evaluator_code", "item_id", "q1", "q2", "updated_at"])
    writer.writeheader()
    writer.writerows(rows)
