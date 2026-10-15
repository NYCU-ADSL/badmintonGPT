#!/usr/bin/env python3
"""Download the 50 CoachAI-format games' YouTube videos and cut them into rally clips.

Input: `BWF_2025_2026_50_matches.xlsx` (first sheet `總表_50場`: No., Year, ..., Video ID) +
the converted `data/Data-coachai/<id>.mp4/RallySeg.csv` (scripts/import_coachai_format.py).
Game ids are the per-year ordinal in that sheet: the Nth 2025 row is `2025gameN`, the Nth
2026 row is `2026gameN` (the export numbers them the same way; the year sheets
`2025_27場`/`2026_23場` list them in the same order).

Steps, each idempotent (an existing output is kept unless --force):
  1. download  yt-dlp -> <full-dir>/<id>.mp4 (720p H.264 + AAC; the clips are 720p anyway).
               Checked: 30 fps (the annotation's frame numbers are 30 fps frames) and long
               enough to hold the last rally.
  2. cut       one clip per RallySeg row -> <videos-to>/<id>.mp4/rally_video/<Score>.mp4,
               frames Start..End inclusive, in the SAME format as the 2023/2024 clips on the
               reels host: H.264 High (libx264 preset medium, crf 23), 1280x720, 30 fps,
               yuv420p, no audio, faststart. RallySeg.csv is copied next to rally_video/
               like the Data-old matches there.
  3. manifest  data/Data-coachai/rally_video_manifest.txt (`<id>.mp4/rally_video/<Score>.mp4`
               per clip) -> ingest.py's LocalSource sets has_video from it, so
               `ingest.py --local-data data/Data-old --local-data data/Data-coachai`.
  4. --upload  (opt-in) one HF commit with every game's RallySeg.csv + its rally_video/*.mp4
               (where cut), the way the 2023/2024 matches are on HF, so an HF-only rebuild
               gets the padded segments and has_video. Needs a WRITE HF_TOKEN; unchanged
               files are no-ops.

yt-dlp: YouTube breaks old releases, so it runs from a throwaway env with the latest
release by default (`uvx --from yt-dlp[default] yt-dlp`); override with --yt-dlp.

Usage:
  scripts/fetch_coachai_videos.py                       # all 50: download + cut + manifest
  scripts/fetch_coachai_videos.py --only 2025game1      # one game
  scripts/fetch_coachai_videos.py --download-only -j 3  # just the downloads, 3 at a time
  scripts/fetch_coachai_videos.py --manifest-only       # rewrite the manifest from disk
  scripts/fetch_coachai_videos.py --manifest-only --upload   # push RallySeg + clips to HF
"""
from __future__ import annotations

import argparse
import csv
import json
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_coachai_format import match_info_by_id  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FPS = 30
FORMAT = ("136+140/bv*[height=720][vcodec^=avc1]+ba[ext=m4a]"
          "/bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/b[height<=1080]")
# Games whose annotation does not line up with the YouTube video: no clips are cut for them
# (and none listed / uploaded), since every clip would show the wrong moment. Measured by
# sampling 40 annotated hit frames per game and checking they show the main court camera:
# every other game scores 88-100 %, these do not, and no constant time shift fixes them.
OUT_OF_SYNC = {
    "2025game26": "42 % of hit frames on court (best constant shift 59 %); scoreboard reads "
                  "7-10 where the labels say 9-3; only 48 rallies annotated",
}
ENCODE = ["-an", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
          "-pix_fmt", "yuv420p", "-vf", "scale=1280:720", "-r", str(FPS),
          "-movflags", "+faststart"]


def games(xlsx: Path) -> list[dict]:
    """[{id, video_id, event, round, p1, p2}] in sheet order, ids = per-year ordinal."""
    return [{"id": i["id"], "video_id": i["youtube_id"], "event": i["tournament"],
             "round": i["round"], "p1": i["player_a"], "p2": i["player_b"]}
            for i in match_info_by_id(xlsx).values()]


def probe(path: Path) -> tuple[float, float, int, int]:
    """(fps, duration_s, width, height) of the first video stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return int(num) / int(den), float(j["format"]["duration"]), s["width"], s["height"]


def rally_seg(src_dir: Path, gid: str) -> list[dict[str, str]]:
    p = src_dir / f"{gid}.mp4" / "RallySeg.csv"
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def download(g: dict, full_dir: Path, ytdlp: list[str], force: bool) -> Path:
    dst = full_dir / f"{g['id']}.mp4"
    if dst.is_file() and not force:
        return dst
    full_dir.mkdir(parents=True, exist_ok=True)
    tmp = full_dir / f"{g['id']}.part.mp4"
    cmd = [*ytdlp, "-f", FORMAT, "--merge-output-format", "mp4", "-N", "4",
           "--no-playlist", "--no-progress", "-o", str(tmp),
           f"https://www.youtube.com/watch?v={g['video_id']}"]
    subprocess.run(cmd, check=True)
    tmp.rename(dst)
    return dst


def check(g: dict, full: Path, segs: list[dict[str, str]]) -> str | None:
    """None if usable, else why not."""
    fps, dur, w, h = probe(full)
    if abs(fps - FPS) > 0.01:
        return f"{fps:.3f} fps, annotation frames are {FPS} fps"
    last = max((int(s["End"]) for s in segs), default=0)
    if last / FPS > dur:
        return f"video is {dur / 60:.1f} min but the last rally ends at {last / FPS / 60:.1f} min"
    return None


def cut_one(full: Path, start: int, end: int, out: Path) -> None:
    tmp = out.with_suffix(".tmp.mp4")
    # -ss before -i + re-encode is frame-accurate; aim half a frame early so float
    # rounding can never skip frame `start` (frame k is shown at pts k/FPS).
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{(start - 0.5) / FPS:.6f}",
         "-i", str(full), "-frames:v", str(end - start + 1), *ENCODE, str(tmp)],
        check=True)
    tmp.rename(out)


def cut(g: dict, full: Path, segs: list[dict[str, str]], src_dir: Path, videos_to: Path,
        jobs: int, force: bool) -> int:
    folder = videos_to / f"{g['id']}.mp4"
    (folder / "rally_video").mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_dir / f"{g['id']}.mp4" / "RallySeg.csv", folder / "RallySeg.csv")
    todo = [s for s in segs
            if force or not (folder / "rally_video" / f"{s['Score']}.mp4").is_file()]
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(lambda s: cut_one(full, int(s["Start"]), int(s["End"]),
                                      folder / "rally_video" / f"{s['Score']}.mp4"), todo))
    return len(todo)


def write_manifest(src_dir: Path, videos_to: Path) -> int:
    lines = sorted(
        f"{p.parent.parent.name}/rally_video/{p.name}"
        for d in src_dir.glob("*.mp4") if d.is_dir() and d.stem not in OUT_OF_SYNC
        for p in (videos_to / d.name / "rally_video").glob("*.mp4")
        if not p.name.endswith(".tmp.mp4"))
    (src_dir / "rally_video_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def upload(src_dir: Path, videos_to: Path, only: list[str], message: str) -> None:
    import os

    from huggingface_hub import CommitOperationAdd, HfApi
    sys.path.insert(0, str(REPO / "mcps" / "badminton-db"))
    from ingest_lib import REPO_ID

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN (write scope) is required — add it to .env")
    ops = []
    for d in sorted(src_dir.glob("*.mp4")):
        if not d.is_dir() or (only and d.name.removesuffix(".mp4") not in only):
            continue
        # RallySeg for every game (one padding convention on HF, clips or not) ...
        if (d / "RallySeg.csv").is_file():
            ops.append(CommitOperationAdd(f"Data/{d.name}/RallySeg.csv", str(d / "RallySeg.csv")))
        if d.stem in OUT_OF_SYNC:
            continue
        # ... clips only where they were cut (and are in sync)
        ops += [CommitOperationAdd(f"Data/{d.name}/rally_video/{c.name}", str(c))
                for c in sorted((videos_to / d.name / "rally_video").glob("*.mp4"))
                if not c.name.endswith(".tmp.mp4")]
    size = sum(Path(o.path_or_fileobj).stat().st_size for o in ops)
    print(f"upload: {len(ops)} files ({size / 1e9:.2f} GB) -> {REPO_ID}", flush=True)
    info = HfApi(token=token).create_commit(
        repo_id=REPO_ID, repo_type="dataset", operations=ops, commit_message=message)
    print(f"uploaded: {info.commit_url}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xlsx", default=str(REPO / "BWF_2025_2026_50_matches.xlsx"))
    ap.add_argument("--src", default=str(REPO / "data" / "Data-coachai"),
                    help="converted games (RallySeg.csv source; the manifest is written here)")
    ap.add_argument("--full-dir", default=str(REPO / "data" / "coachai_full_video"),
                    help="where the full-match downloads go")
    ap.add_argument("--videos-to", default="/mnt/ssd1/howchien/badminton-reels/data/Data",
                    help="reels host data dir (gets <id>.mp4/rally_video/*.mp4)")
    ap.add_argument("--yt-dlp", default="uvx --from yt-dlp[default] yt-dlp")
    ap.add_argument("--only", action="append", default=[], metavar="ID")
    ap.add_argument("-j", "--jobs", type=int, default=1, help="games downloaded in parallel")
    ap.add_argument("--cut-jobs", type=int, default=6, help="ffmpeg processes per game")
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--manifest-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="redo existing downloads/clips")
    ap.add_argument("--upload", action="store_true", help="push RallySeg + clips to HF")
    ap.add_argument("--message", default="Add 2025/2026 rally clips + padded RallySeg")
    args = ap.parse_args()

    src_dir, full_dir, videos_to = Path(args.src), Path(args.full_dir), Path(args.videos_to)
    if not args.manifest_only:
        todo = [g for g in games(Path(args.xlsx)) if not args.only or g["id"] in args.only]
        ytdlp = shlex.split(args.yt_dlp)
        failed: list[tuple[str, str]] = []

        def run(g: dict) -> None:
            label = f"{g['id']} ({g['video_id']}: {g['p1']} vs {g['p2']}, {g['event']} {g['round']})"
            try:
                full = download(g, full_dir, ytdlp, args.force)
                segs = rally_seg(src_dir, g["id"])
                why = check(g, full, segs)
                if why:
                    raise RuntimeError(why)
                if g["id"] in OUT_OF_SYNC:
                    print(f"[skip] {label}: out of sync — {OUT_OF_SYNC[g['id']]}", flush=True)
                    return
                if args.download_only:
                    print(f"[ok] {label}: downloaded", flush=True)
                    return
                n = cut(g, full, segs, src_dir, videos_to, args.cut_jobs, args.force)
                print(f"[ok] {label}: {len(segs)} rallies, {n} clips cut", flush=True)
            except Exception as e:  # noqa: BLE001  (report all, keep going)
                failed.append((g["id"], str(e)))
                print(f"[FAIL] {label}: {e}", flush=True)

        with ThreadPoolExecutor(max(1, args.jobs)) as ex:
            list(ex.map(run, todo))
        if failed:
            print(f"\n{len(failed)} failed:")
            for gid, e in failed:
                print(f"  {gid}: {e}")
    if not args.download_only:
        n = write_manifest(src_dir, videos_to)
        print(f"manifest -> {src_dir / 'rally_video_manifest.txt'} ({n} clips)")
    if args.upload:
        upload(src_dir, videos_to, args.only, args.message)


if __name__ == "__main__":
    main()
