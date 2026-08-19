#!/usr/bin/env python3
"""Extract todo0819/Data-old.zip into the layout `ingest.py --local-data` expects.

The archive is ~39 GB, but only ~22 MB of it is CSV — the rest is rally_video/*.mp4.
So by default we extract ONLY the CSVs plus a *manifest* of the video entries (read from
the zip's central directory, no video bytes touched). ingest.py uses that manifest to set
rallies.has_video, exactly like the HF path uses list_repo_files().

The videos belong to the badminton-reels deployment (that is what renders clips), so they
are extracted separately with --videos-to; see docs/DEPLOY.md.

Uses python's zipfile rather than `unzip`, which refuses this archive with
"invalid zip file with overlapped components (possible zip bomb)".

Usage:
  scripts/extract_data_old.py                       # CSVs + manifest -> data/Data-old/
  scripts/extract_data_old.py --videos-to DIR       # ...also rally_video/ for the matches
                                                    #    HF does NOT have (~26 GB)
  scripts/extract_data_old.py --zip PATH --out DIR  # non-default locations

Idempotent: re-running overwrites in place.
"""
from __future__ import annotations

import argparse
import re
import shutil
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOP = "Data-old/"          # the archive nests everything under this single dir
# Only the plain set{1,2,3}.csv: the *_v1/_v2/(1) variants are duplicate annotation passes
# that ingest.py does not read. tracknet/ is not in our schema.
CSV_RE = re.compile(r"^[^/]+\.mp4/(RallySeg\.csv|label/set[123]\.csv)$")
VIDEO_RE = re.compile(r"^[^/]+\.mp4/rally_video/[^/]+\.mp4$")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", default=str(REPO / "todo0819" / "Data-old.zip"))
    ap.add_argument("--out", default=str(REPO / "data" / "Data-old"))
    ap.add_argument("--videos-to", default=None,
                    help="also extract rally_video/*.mp4 here (tens of GB)")
    ap.add_argument("--hf-mirror", default=str(REPO / "data" / "Data"),
                    help="folders present here are skipped when extracting videos "
                         "(they are on HuggingFace already, so reels can fetch them)")
    args = ap.parse_args()

    zpath = Path(args.zip)
    out = Path(args.out)
    if not zpath.is_file():
        raise SystemExit(f"zip not found: {zpath}")
    out.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zpath) as zf:
        names = [n for n in zf.namelist() if n.startswith(TOP)]
        rel = [n[len(TOP):] for n in names]
        print(f"[1/3] {zpath.name}: {len(names)} entries under {TOP}")

        csvs = [r for r in rel if CSV_RE.match(r)]
        print(f"[2/3] extracting {len(csvs)} CSVs -> {out}")
        for r in csvs:
            dst = out / r
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(TOP + r) as src, open(dst, "wb") as fh:
                shutil.copyfileobj(src, fh)
        # Create a dir for EVERY match folder in the archive, including the handful that
        # carry neither RallySeg nor labels — ingest.py enumerates dirs, and those still
        # deserve a `matches` catalog row (they may have a coachai analyze_match_id).
        all_folders = sorted({r.split("/")[0] for r in rel if r.endswith("/") or "/" in r})
        all_folders = sorted({f for f in all_folders if f.endswith(".mp4")})
        for f in all_folders:
            (out / f).mkdir(parents=True, exist_ok=True)
        with_csv = {r.split("/")[0] for r in csvs}
        print(f"      match folders: {len(all_folders)} ({len(with_csv)} with CSVs, "
              f"{len(all_folders) - len(with_csv)} catalog-only)")

        # One "<folder>/<rally_id>.mp4" line per rally video present in the archive.
        videos = sorted(r for r in rel if VIDEO_RE.match(r))
        manifest = out / "rally_video_manifest.txt"
        manifest.write_text("\n".join(videos) + "\n", encoding="utf-8")
        print(f"[3/3] video manifest -> {manifest} ({len(videos)} rally videos)")

        if args.videos_to:
            vdst = Path(args.videos_to)
            mirror = Path(args.hf_mirror)
            skip = {p.name for p in mirror.iterdir() if p.is_dir()} if mirror.is_dir() else set()
            todo = [r for r in videos if r.split("/")[0] not in skip]
            total = sum(zf.getinfo(TOP + r).file_size for r in todo)
            print(f"[+] extracting {len(todo)} videos ({total / 1e9:.1f} GB) -> {vdst}"
                  f"  [skipping {len(skip)} folder(s) available from HuggingFace]")
            for i, r in enumerate(todo, 1):
                dst = vdst / r
                if dst.is_file() and dst.stat().st_size == zf.getinfo(TOP + r).file_size:
                    continue          # already extracted (resumable)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(TOP + r) as src, open(dst, "wb") as fh:
                    shutil.copyfileobj(src, fh, length=4 << 20)
                if i % 500 == 0:
                    print(f"      {i}/{len(todo)}")
            print(f"      done -> {vdst}")

    print(f"OK. Next: .venv/bin/python mcps/badminton-db/ingest.py --local-data {out}")


if __name__ == "__main__":
    main()
