#!/usr/bin/env python3
"""Upload the merged Data-old CSVs to the HuggingFace dataset.

Why: `ingest.py --local-data data/Data-old` merges the archive on whatever machine holds
the extracted CSVs. Pushing those CSVs to the dataset makes the merged DB reproducible
from HF alone (`docker compose --profile ingest run --rm ingest`), the way the original
27 matches already are.

Only `RallySeg.csv` + `label/set[123].csv` are uploaded (~22 MB). The rally videos are NOT
uploaded — they live on the badminton-reels host (see scripts/extract_data_old.py
--videos-to). Consequence: a rebuild from HF alone leaves `has_video=0` for these matches
unless data/Data-old/rally_video_manifest.txt is also present; pass --local-data as well
to keep has_video truthful.

Needs a WRITE-scoped token: HF_TOKEN (or HUGGING_FACE_HUB_TOKEN). The dataset reads fine
anonymously, so a read-only setup will fail here with 401/403.

Usage:
  scripts/upload_data_old_to_hf.py --dry-run     # list what would be uploaded
  scripts/upload_data_old_to_hf.py               # upload
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "mcps" / "badminton-db"))

from ingest_lib import REPO_ID  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO / "data" / "Data-old"))
    ap.add_argument("--repo-id", default=REPO_ID)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from huggingface_hub import HfApi

    src = Path(args.src)
    if not src.is_dir():
        raise SystemExit(f"not found: {src} (run scripts/extract_data_old.py first)")
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token and not args.dry_run:
        raise SystemExit("HF_TOKEN (write scope) is required — add it to .env")

    api = HfApi(token=token)
    try:
        existing = set(api.list_repo_files(args.repo_id, repo_type="dataset"))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] cannot list {args.repo_id}: {e}")
        existing = set()

    files = sorted(p for p in src.rglob("*.csv"))
    new = [p for p in files
           if f"Data/{p.relative_to(src).as_posix()}" not in existing]
    size = sum(p.stat().st_size for p in new)
    print(f"{len(files)} CSVs locally; {len(new)} not yet on {args.repo_id} "
          f"({size / 1e6:.1f} MB)")
    for p in new[:5]:
        print(f"  + Data/{p.relative_to(src).as_posix()}")
    if len(new) > 5:
        print(f"  … and {len(new) - 5} more")
    if args.dry_run or not new:
        return

    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="dataset",
        folder_path=str(src),
        path_in_repo="Data",
        allow_patterns=["*/RallySeg.csv", "*/label/set1.csv",
                        "*/label/set2.csv", "*/label/set3.csv"],
        commit_message="Add Data-old match annotations (labels + RallySeg)",
    )
    print("uploaded. Verify: python -c \"from huggingface_hub import HfApi;"
          " print(len(HfApi().list_repo_files('%s', repo_type='dataset')))\"" % args.repo_id)


if __name__ == "__main__":
    main()
