#!/usr/bin/env python3
"""Build badminton.db (SQLite) from the HuggingFace dataset.

- `matches` : all 32 HF folders (catalog; 27 official + 5 NYCU practice).
- `rallies` / `shots` : downloaded per-shot data for all 27 OFFICIAL matches
  (downloads CSVs only, NOT videos; `has_video` is taken from the HF rally_video/
  listing).

Self-contained: parsing/models live in this package's `ingest_lib/` (vendored from
badminton-reels), so the DB build needs only HF_TOKEN — no badminton-reels import,
no OPENAI/FISH secrets. A/B identity is derived from folder-name order (see
derive_ab); we do not use a first-rally-court heuristic since players switch ends.

Usage:
  python ingest.py [--db PATH] [--catalog-only] [--only FOLDER] [--limit N] [--include-practice]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
from pathlib import Path

from ingest_lib import REPO_ID, DataLoader, RallySegment, ShotLabel

# DB path: BADMINTON_DB env wins (containers set it); else walk up to the nearest
# data/ dir (repo-root on host). Walk-up avoids parents[N] IndexError at /app depth.
def _default_db() -> str:
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "data").is_dir():
            return str(p / "data" / "badminton.db")
    return str(here.parent / "data" / "badminton.db")


DEFAULT_DB = os.environ.get("BADMINTON_DB") or _default_db()

# Offline fallback if HF listing is unavailable (the full 32 folders).
FALLBACK_FOLDERS = [
    "AN_Se_Young_Gregoria_Mariska_TUNJUNG_Malaysia_Masters_2022_SemiFinals.mp4",
    "AN_Se_Young_TAI_Tzu_Japan_Open_2022_Semi_finals.mp4",
    "Akane_YAMAGUCHI_AN_Se_Young_BWF_World_Championships_2022_Semi_finals.mp4",
    "Akane_YAMAGUCHI_AN_Se_Young_DAIHATSU_YONEX_Japan_Open_2022_Finals.mp4",
    "Akane_YAMAGUCHI_AN_Seyoung_YONEX_All_England_Open_Badminton_Championships_2022_Finals.mp4",
    "CHEN_Yu_Fei_Ratchanok_INTANON_Denmark_Open_2022_SemiFinals.mp4",
    "CHEN_Yu_Fei_TAI_Tzu_Ying_BWF_World_Championships_2022_Semi_finals.mp4",
    "CHEN_Yu_Fei_TAI_Tzu_Ying_Malaysia_Masters_2022 _Semi_finals.mp4",
    "Carolina_MARIN_Akane_YAMAGUCHI_French_Open_2022_SemiFinals.mp4",
    "Chen_Yu_Fei_Tai_Tzu_Ying_Malaysia_Open_2022_Semi_finals.mp4",
    "HE_Bing_Jiao_CHEN_Yu_Fei_Denmark_Open_2022_Final.mp4",
    "HE_Bing_Jiao_Carolina_MARIN_French_Open_2022_Final.mp4",
    "He_Bing_Jiao_Han_Yue_Denmark_Open_2022_Semifinals.mp4",
    "Kenta_NISHIMOTO_Anders_ANTONSEN_Japan_Open_2022_SemiFinals.mp4",
    "Kento_MOMOTA_Kunlavut_VITIDSARN_Malaysia_Open_2022_ Semi_finals.mp4",
    "Lee_Zii_Jia_Loh_Kean_Yew_Denmark_Open_2022_Semifinals.mp4",
    "NYCU_Other_practice1.mp4", "NYCU_Other_practice2.mp4", "NYCU_Other_practice3.mp4",
    "NYCU_Other_practice4.mp4", "NYCU_Other_practice5.mp4",
    "Ratchanok_INTANON_CHEN_Yu_Fei_PETRONAS_Malaysia_Open_2022_Finals.mp4",
    "SHI_Yu_Qi_Kodai_NARAOKA_Denmark_Open_2022_SemiFinals.mp4",
    "SHI_Yu_Qi_LEE_Zii_Jia_Denmark_Open_2022_Final.mp4",
    "TAI_Tzu_Ying_WANG_Zhi_Yi_Indonesia_Open_2022_Final.mp4",
    "Viktor_AXELSEN_Anthony_Sinisuka_GINTING_BWF_World_Tour_Finals_2022_Finals.mp4",
    "Viktor_AXELSEN_Anthony_Sinisuka_GINTING_DAIHATSU_INDONESIA_MASTERS_2022_Semifinals.mp4",
    "Viktor_AXELSEN_CHOU_Tien_Chen_Indonesia_Masters_2022_Finals.mp4",
    "Viktor_AXELSEN_Kento_MOMOTA_PETRONAS_Malaysia_Open_2022_Finals.mp4",
    "Viktor_AXELSEN_Kodai_NARAOKA_HSBC_BWF_World_Tour_Finals_2022_Semifinals.mp4",
    "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals.mp4",
    "Wang_Zhi_Yi_He_Bing_Jiao_Indonesia_Open_2022_Semi_finals.mp4",
]

DDL = """
CREATE TABLE matches (
  folder       TEXT PRIMARY KEY,
  name         TEXT,
  tournament   TEXT,
  round        TEXT,
  player_a     TEXT,
  player_b     TEXT,
  year         INTEGER,
  is_practice  INTEGER DEFAULT 0
);
CREATE TABLE rallies (
  match_name     TEXT REFERENCES matches(name),
  rally_id       TEXT,
  set_no         INTEGER,
  score_a        INTEGER,
  score_b        INTEGER,
  start_frame    INTEGER,
  end_frame      INTEGER,
  has_video      INTEGER DEFAULT 0,
  video_filename TEXT,
  PRIMARY KEY (match_name, rally_id)
);
CREATE TABLE shots (
  match_name      TEXT REFERENCES matches(name),
  set_no          INTEGER,
  rally           INTEGER,
  ball_round      INTEGER,
  player          TEXT,
  server          TEXT,
  type            TEXT,
  aroundhead      INTEGER,
  backhand        INTEGER,
  hit_area        INTEGER,
  landing_area    INTEGER,
  lose_reason     TEXT,
  win_reason      TEXT,
  getpoint_player TEXT,
  roundscore_a    INTEGER,
  roundscore_b    INTEGER
);
CREATE INDEX idx_shots_match_type    ON shots(match_name, type);
CREATE INDEX idx_shots_match_player  ON shots(match_name, player);
CREATE INDEX idx_rallies_match_video ON rallies(match_name, has_video);
"""


def list_all_folders(dl: DataLoader) -> list[str]:
    """All 32 folders incl. NYCU (do NOT use dl.list_matches() — it filters NYCU)."""
    try:
        files = dl._api.list_repo_files(REPO_ID, repo_type="dataset")
        folders = sorted({
            f.split("/")[1] for f in files
            if f.startswith("Data/") and "/" in f[5:]
        })
        if len(folders) >= 30:
            return folders
    except Exception as e:
        print(f"  [warn] HF listing failed ({e}); using fallback list")
    return sorted(FALLBACK_FOLDERS)


def derive_ab(folder: str, segments: list[RallySegment]) -> tuple[str, str]:
    """A/B -> names. A = the player whose name appears FIRST in the folder string.

    Names come from RallySeg up/down court. We bind A to whichever appears earlier in
    the folder (the dataset's first-named convention), matching labels' roundscore_A /
    getpoint='A'. We avoid _extract_players() (first-rally court) — players switch ends.
    """
    names = list({segments[0].up_court, segments[0].down_court})
    if len(names) != 2:
        return (segments[0].up_court, segments[0].down_court)

    def _norm(s: str) -> str:
        return s.replace(" ", "").replace("_", "").lower()

    fn = _norm(folder)

    def idx(name: str) -> int:
        i = fn.find(_norm(name))   # case/underscore-insensitive position in folder
        return i if i >= 0 else 10**9

    a, b = sorted(names, key=idx)
    return a, b


def insert_match_row(cur, folder: str, dl: DataLoader,
                     player_a: str | None, player_b: str | None) -> None:
    name = folder.removesuffix(".mp4")
    tournament, round_name = dl._extract_tournament_round(name)
    is_practice = 1 if name.startswith("NYCU_Other_practice") else 0
    ym = re.search(r"(20\d{2})", name)
    year = int(ym.group(1)) if ym else 2022
    cur.execute(
        "INSERT OR REPLACE INTO matches "
        "(folder, name, tournament, round, player_a, player_b, year, is_practice) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (folder, name, tournament, round_name, player_a, player_b, year, is_practice),
    )


def ingest_match_hf(cur, dl: DataLoader, folder: str, hf_files: list[str]) -> dict:
    """Download one match's CSVs from HF, write rallies + shots; return A/B + stats.

    Labels are parsed ROW-TOLERANTLY (skip malformed rows) — unlike DataLoader's
    all-or-nothing _parse_label_csv, where a couple bad rows would drop the whole set.
    `has_video` comes from the HF rally_video/ listing (videos are NOT downloaded).
    """
    name = folder.removesuffix(".mp4")

    # rallies (RallySeg.csv) + has_video from HF listing
    segments = dl._parse_rally_seg(dl._download_file(f"Data/{folder}/RallySeg.csv"))
    vprefix = f"Data/{folder}/rally_video/"
    avail = {Path(f).stem for f in hf_files
             if f.startswith(vprefix) and f.endswith(".mp4")}
    for seg in segments:
        hv = seg.score in avail
        cur.execute(
            "INSERT OR REPLACE INTO rallies "
            "(match_name, rally_id, set_no, score_a, score_b, start_frame, "
            " end_frame, has_video, video_filename) VALUES (?,?,?,?,?,?,?,?,?)",
            (name, seg.score, seg.set_num, seg.score_a, seg.score_b,
             seg.start_frame, seg.end_frame, int(hv),
             f"{seg.score}.mp4" if hv else None),
        )

    # shots (label/set*.csv) — row-tolerant parse
    n_shots, skipped = 0, 0
    for set_num in (1, 2, 3):
        hf_path = f"Data/{folder}/label/set{set_num}.csv"
        if hf_path not in hf_files:
            continue
        path = dl._download_file(hf_path)
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    s = ShotLabel.model_validate(row)
                except Exception:
                    skipped += 1
                    continue
                cur.execute(
                    "INSERT INTO shots (match_name, set_no, rally, ball_round, player, "
                    " server, type, aroundhead, backhand, hit_area, landing_area, "
                    " lose_reason, win_reason, getpoint_player, roundscore_a, roundscore_b) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, set_num, s.rally, s.ball_round, s.player, s.server,
                     s.shot_type, int(s.is_aroundhead), int(s.is_backhand),
                     s.hit_area, s.landing_area, s.lose_reason, s.win_reason,
                     s.getpoint_player, s.score_a, s.score_b),
                )
                n_shots += 1

    player_a, player_b = derive_ab(folder, segments)

    finals: dict[int, list[int]] = {}
    for seg in segments:
        f = finals.setdefault(seg.set_num, [0, 0])
        f[0], f[1] = max(f[0], seg.score_a), max(f[1], seg.score_b)
    a_sets = sum(1 for ab in finals.values() if ab[0] > ab[1])
    b_sets = sum(1 for ab in finals.values() if ab[1] > ab[0])
    winner_side = "A" if a_sets > b_sets else "B"
    return {
        "folder": folder, "player_a": player_a, "player_b": player_b,
        "n_rallies": len(segments), "n_shots": n_shots, "skipped": skipped,
        "has_video_count": len(avail),
        "set_finals": finals, "winner_side": winner_side,
        "winner_name": player_a if winner_side == "A" else player_b,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--catalog-only", action="store_true",
                    help="only build the matches catalog (skip rallies/shots)")
    ap.add_argument("--only", default=None, help="ingest per-shot only for this folder/name")
    ap.add_argument("--limit", type=int, default=None, help="cap number of matches (testing)")
    ap.add_argument("--include-practice", action="store_true",
                    help="also ingest per-shot for NYCU practice clips")
    args = ap.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    dl = DataLoader()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        "DROP TABLE IF EXISTS shots; DROP TABLE IF EXISTS rallies; "
        "DROP TABLE IF EXISTS matches;")
    cur.executescript(DDL)

    folders = list_all_folders(dl)
    try:
        hf_files = dl._api.list_repo_files(REPO_ID, repo_type="dataset")
    except Exception:
        hf_files = []
    print(f"[1/2] matches catalog: {len(folders)} folders")

    def is_practice(f: str) -> bool:
        return f.removesuffix(".mp4").startswith("NYCU_Other_practice")

    targets = [] if args.catalog_only else [
        f for f in folders
        if (args.include_practice or not is_practice(f))
        and (args.only is None or f == args.only or f.removesuffix(".mp4") == args.only)
    ]

    if args.limit:
        targets = targets[:args.limit]

    ab_by_folder: dict[str, tuple[str, str]] = {}
    stats, failed = [], []
    print(f"[2/2] downloading + ingesting per-shot for {len(targets)} match(es)…")
    for i, folder in enumerate(targets, 1):
        short = folder.removesuffix(".mp4")[:55]
        try:
            info = ingest_match_hf(cur, dl, folder, hf_files)
            ab_by_folder[folder] = (info["player_a"], info["player_b"])
            stats.append(info)
            conn.commit()  # persist per match
            print(f"  [{i}/{len(targets)}] {short}  "
                  f"A={info['player_a']} B={info['player_b']} "
                  f"shots={info['n_shots']}(skip {info['skipped']}) "
                  f"rallies={info['n_rallies']} video={info['has_video_count']}")
        except Exception as e:
            failed.append((folder, str(e)))
            print(f"  [{i}/{len(targets)}] {short}  SKIP: {e}")

    for folder in folders:
        pa, pb = ab_by_folder.get(folder, (None, None))
        insert_match_row(cur, folder, dl, pa, pb)
    conn.commit()

    m = cur.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    pr = cur.execute("SELECT COUNT(*) FROM matches WHERE is_practice=1").fetchone()[0]
    ws = cur.execute("SELECT COUNT(DISTINCT match_name) FROM shots").fetchone()[0]
    print(f"\nDB: {db_path}")
    print(f"  matches={m} (official={m - pr}, practice={pr})")
    print(f"  matches with per-shot data={ws}  "
          f"shots={cur.execute('SELECT COUNT(*) FROM shots').fetchone()[0]}  "
          f"rallies={cur.execute('SELECT COUNT(*) FROM rallies').fetchone()[0]}")
    if failed:
        print(f"  FAILED ({len(failed)}):")
        for f, e in failed:
            print(f"    - {f.removesuffix('.mp4')[:50]}: {e}")
    conn.close()


if __name__ == "__main__":
    main()
