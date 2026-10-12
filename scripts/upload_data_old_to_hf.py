#!/usr/bin/env python3
"""Upload a local dataset dir's CSVs (Data-old, Data-coachai, …) to the HuggingFace dataset.

Why: `ingest.py --local-data data/Data-old` merges the archive on whatever machine holds
the extracted CSVs. Pushing those CSVs to the dataset makes the merged DB reproducible
from HF alone (`docker compose --profile ingest run --rm ingest`), the way the original
27 matches already are.

Only the CSVs are uploaded: `RallySeg.csv` + `label/set[1-4].csv`, plus the per-match
`homography.csv` / `qa_notes.csv` / `match_info.csv` that scripts/import_coachai_format.py
writes (~22 MB for Data-old). The rally videos are NOT uploaded by default — they live on the badminton-reels host (see scripts/extract_data_old.py
--videos-to). Consequence: a rebuild from HF alone leaves `has_video=0` for these matches
unless data/Data-old/rally_video_manifest.txt is also present; pass --local-data as well
to keep has_video truthful.

--rally-videos DIR additionally uploads every `DIR/<folder>/rally_video/*.mp4` that HF lacks,
for the folders in --src. Needed because the deployed reels server runs in Docker and reads
HF (+ its own download cache), NOT the host's data dir: a clip only on the host is listed by
the manifest (has_video=1) yet cannot be rendered. Done 2026-10-12 for the 13 archive
matches whose clips HF lacked (979 rallies).

Needs a WRITE-scoped token: HF_TOKEN (or HUGGING_FACE_HUB_TOKEN). The dataset reads fine
anonymously, so a read-only setup will fail here with 401/403.

Usage:
  scripts/upload_data_old_to_hf.py --dry-run     # list what would be uploaded
  scripts/upload_data_old_to_hf.py               # upload
  scripts/upload_data_old_to_hf.py --rally-videos /mnt/ssd1/howchien/badminton-reels/data/Data
  scripts/upload_data_old_to_hf.py --src data/Data-coachai \
      --message "Add 2025/2026 CoachAI-format games"   # the 2025gameN/2026gameN set
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "mcps" / "badminton-db"))

from ingest import norm_name  # noqa: E402
from ingest_lib import REPO_ID  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO / "data" / "Data-old"))
    ap.add_argument("--repo-id", default=REPO_ID)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--message", default="Add Data-old match annotations (labels + RallySeg)")
    ap.add_argument("--rally-videos", default=None, metavar="DIR",
                    help="also upload DIR/<folder>/rally_video/*.mp4 that HF lacks")
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

    # Skip punctuation near-duplicates (`SHI_Yu Qi_…` vs `SHI_Yu_Qi_…`): ingest dedupes on
    # norm_name, so pushing a thinner twin next to the real folder can shadow it. Keep, per
    # key, only the folder with the most label CSVs across HF + local (HF wins ties).
    def n_labels(names: set[str], folder: str) -> int:
        return sum(1 for f in names if f.startswith(f"Data/{folder}/label/") and f.endswith(".csv"))

    local_names = {f"Data/{p.relative_to(src).as_posix()}" for p in src.rglob("*.csv")}
    best: dict[str, tuple[int, int, str]] = {}   # key -> (labels, on_hf, folder)
    for name in existing | local_names:
        parts = name.split("/")
        if len(parts) < 3 or parts[0] != "Data":
            continue
        folder = parts[1]
        cand = (n_labels(existing | local_names, folder),
                int(any(f.startswith(f"Data/{folder}/") for f in existing)), folder)
        key = norm_name(folder)
        if key not in best or cand > best[key]:
            best[key] = cand
    skipped = sorted({p.relative_to(src).parts[0] for p in src.rglob("*.csv")
                      if best[norm_name(p.relative_to(src).parts[0])][2]
                      != p.relative_to(src).parts[0]})
    for folder in skipped:
        print(f"  skip near-duplicate {folder!r} (keeping "
              f"{best[norm_name(folder)][2]!r})")

    files = sorted(p for p in src.rglob("*.csv")
                   if p.relative_to(src).parts[0] not in skipped)
    new = [p for p in files
           if f"Data/{p.relative_to(src).as_posix()}" not in existing]
    size = sum(p.stat().st_size for p in new)
    print(f"{len(files)} CSVs locally; {len(new)} not yet on {args.repo_id} "
          f"({size / 1e6:.1f} MB)")
    for p in new[:5]:
        print(f"  + Data/{p.relative_to(src).as_posix()}")
    if len(new) > 5:
        print(f"  … and {len(new) - 5} more")
    clips: list[tuple[str, Path]] = []
    if args.rally_videos:
        vroot = Path(args.rally_videos)
        for folder in sorted({p.relative_to(src).parts[0] for p in files}):
            for c in sorted((vroot / folder / "rally_video").glob("*.mp4")):
                hf = f"Data/{folder}/rally_video/{c.name}"
                if hf not in existing:
                    clips.append((hf, c))
        csize = sum(c.stat().st_size for _, c in clips)
        print(f"{len(clips)} rally clips not yet on {args.repo_id} ({csize / 1e9:.2f} GB) in "
              f"{len({hf.split('/')[1] for hf, _ in clips})} folders")
        for hf, _ in clips[:3]:
            print(f"  + {hf}")
    if args.dry_run:
        return
    if clips:
        from huggingface_hub import CommitOperationAdd
        info = api.create_commit(
            repo_id=args.repo_id, repo_type="dataset",
            operations=[CommitOperationAdd(hf, str(c)) for hf, c in clips],
            commit_message=args.message)
        print(f"uploaded {len(clips)} clips: {info.commit_url}")
    if not new:
        return

    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="dataset",
        folder_path=str(src),
        path_in_repo="Data",
        allow_patterns=["*/RallySeg.csv", "*/label/set1.csv",
                        "*/label/set2.csv", "*/label/set3.csv", "*/label/set4.csv",
                        "*/homography.csv", "*/qa_notes.csv", "*/match_info.csv"],
        ignore_patterns=[f"{folder}/*" for folder in skipped],
        commit_message=args.message,
    )
    print("uploaded. Verify: python -c \"from huggingface_hub import HfApi;"
          " print(len(HfApi().list_repo_files('%s', repo_type='dataset')))\"" % args.repo_id)


if __name__ == "__main__":
    main()
