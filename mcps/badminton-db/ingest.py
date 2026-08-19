#!/usr/bin/env python3
"""Build badminton.db (SQLite) from the HuggingFace dataset + any local dataset dirs.

- `matches` : every folder from every source (catalog).
- `rallies` / `shots` : per-shot data for every folder that has the CSVs.

Two sources, same on-disk layout (`<Match>.mp4/{RallySeg.csv,label/setN.csv,rally_video/}`):
  * HuggingFace `howard9199/Badminton` (default, always read).
  * `--local-data DIR` (repeatable) — e.g. `data/Data-old`, produced by
    `scripts/extract_data_old.py` from todo0819/Data-old.zip. A folder already ingested
    from an earlier source is skipped, so overlapping datasets do not double-count.

Self-contained: parsing/models live in this package's `ingest_lib/`, so the DB build needs
only HF_TOKEN (optional — the dataset is public). A/B identity is derived from folder-name
order (see derive_ab); we do not use a first-rally-court heuristic since players switch ends.

`matches.analyze_match_id` is the id the remote badminton-analyze MCP wants (see
skills/badminton-analyze/). It is fetched from the CoachAI match list and mapped by folder
name; the fetch fails soft (column stays NULL) so the build never depends on that host.

Usage:
  python ingest.py [--db PATH] [--local-data DIR] [--catalog-only] [--only FOLDER]
                   [--limit N] [--include-practice] [--no-analyze-ids]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path

from ingest_lib import REPO_ID, DataLoader, RallySegment, ShotLabel, parse_rally_seg

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
  is_practice  INTEGER DEFAULT 0,
  source       TEXT,               -- which dataset the folder came from ('hf' / dir name)
  analyze_match_id INTEGER         -- id for the badminton-analyze MCP (NULL = not analyzable)
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


def norm_name(s: str) -> str:
    """Case/space/underscore-insensitive folder key (dedupe + CoachAI name matching).

    The Data-old archive carries near-duplicates that differ only in punctuation
    (`SHI_Yu Qi_..._Final` vs `SHI_Yu_Qi_..._Final`), and CoachAI's own list spells a
    few names slightly differently again.
    """
    return re.sub(r"[^a-z0-9]", "", s.removesuffix(".mp4").lower())


# One Data-old label CSV (AN_Se_Young_CHEN_Yu_Fei_Malaysia_Open_2023_SF set2) was written
# through a broken encoding upstream: its `type` values arrive as irrecoverable mojibake
# ("?\ue56d?", "?曉???", …) — literal '?' means bytes were already lost, so no re-decode
# fixes it. Left alone they would add ~16 junk values to what the skill documents as a
# closed Chinese enum. Map them onto the enum's existing "unknown" member instead.
UNKNOWN_SHOT_TYPE = "未知球種"


def clean_shot_type(t: str | None) -> str | None:
    """Mojibake -> 未知球種. Genuine new labels (e.g. 死球) pass through untouched."""
    if not t:
        return t
    if "?" in t or any("\ue000" <= ch <= "\uf8ff" for ch in t):   # '?' + private-use area
        return UNKNOWN_SHOT_TYPE
    return t


class HFSource:
    """The HuggingFace dataset. CSVs are downloaded on demand; videos never are."""

    label = "hf"

    def __init__(self, dl: DataLoader) -> None:
        self._dl = dl
        try:
            self._files = dl._api.list_repo_files(REPO_ID, repo_type="dataset")
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] HF listing failed ({e}); using fallback folder list")
            self._files = []

    def folders(self) -> list[str]:
        folders = sorted({
            f.split("/")[1] for f in self._files
            if f.startswith("Data/") and "/" in f[5:]
        })
        return folders if len(folders) >= 30 else sorted(FALLBACK_FOLDERS)

    def csv_path(self, folder: str, rel: str) -> Path | None:
        hf_path = f"Data/{folder}/{rel}"
        if self._files and hf_path not in self._files:
            return None
        try:
            return self._dl._download_file(hf_path)
        except Exception:  # noqa: BLE001  (missing file / offline)
            return None

    def videos(self, folder: str) -> set[str]:
        prefix = f"Data/{folder}/rally_video/"
        return {Path(f).stem for f in self._files
                if f.startswith(prefix) and f.endswith(".mp4")}


class LocalSource:
    """A local dataset dir in the same layout (see scripts/extract_data_old.py).

    `rally_video_manifest.txt` (one `<folder>/<rally_id>.mp4` per line) stands in for the
    HF file listing, so `has_video` stays truthful even though the 39 GB of videos are not
    extracted here — they live on the badminton-reels host.
    """

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)
        self.label = self.root.name
        self._videos: dict[str, set[str]] = {}
        manifest = self.root / "rally_video_manifest.txt"
        if manifest.is_file():
            for line in manifest.read_text(encoding="utf-8").splitlines():
                if "/rally_video/" not in line:
                    continue
                folder, _, fname = line.partition("/rally_video/")
                self._videos.setdefault(folder, set()).add(Path(fname).stem)

    def folders(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir()
                      if p.is_dir() and p.name.endswith(".mp4"))

    def csv_path(self, folder: str, rel: str) -> Path | None:
        p = self.root / folder / rel
        return p if p.is_file() else None

    def videos(self, folder: str) -> set[str]:
        if self._videos:
            return self._videos.get(folder, set())
        d = self.root / folder / "rally_video"
        return {p.stem for p in d.glob("*.mp4")} if d.is_dir() else set()


# CoachAI publishes its match list here; the badminton-analyze MCP addresses a match by
# its position in that list + 4 (empirically verified: our Axelsen-Lee match == 123, and
# ids outside 4..len+3 error out).
COACHAI_MATCH_LIST = "https://coachai.cs.nycu.edu.tw:55000/api/db-api/match"
COACHAI_ID_OFFSET = 4


def fetch_analyze_ids() -> dict[str, int]:
    """{normalized folder name -> analyze_match_id}. Empty dict if CoachAI is unreachable."""
    try:
        with urllib.request.urlopen(COACHAI_MATCH_LIST, timeout=30) as r:
            rows = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] CoachAI match list unavailable ({e}); analyze_match_id stays NULL")
        return {}
    return {norm_name(row["video"]): i + COACHAI_ID_OFFSET
            for i, row in enumerate(rows) if row.get("video")}


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
                     player_a: str | None, player_b: str | None,
                     source: str, analyze_id: int | None) -> None:
    name = folder.removesuffix(".mp4")
    tournament, round_name = dl._extract_tournament_round(name)
    is_practice = 1 if name.startswith("NYCU_Other_practice") else 0
    ym = re.search(r"(20\d{2})", name)
    year = int(ym.group(1)) if ym else 2022
    cur.execute(
        "INSERT OR REPLACE INTO matches "
        "(folder, name, tournament, round, player_a, player_b, year, is_practice, "
        " source, analyze_match_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (folder, name, tournament, round_name, player_a, player_b, year, is_practice,
         source, analyze_id),
    )


def ingest_match(cur, folder: str, src) -> dict:
    """Write one folder's rallies + shots from `src`; return A/B + stats.

    Partial folders are tolerated (the Data-old archive is full of them): a folder with
    labels but no RallySeg still yields shots, one with RallySeg but no labels yields
    rallies, one with neither yields only its catalog row. Labels are parsed
    ROW-TOLERANTLY (skip malformed rows) — unlike an all-or-nothing CSV loader, where a
    couple of bad rows would drop a whole set.
    `has_video` comes from the source's rally_video listing (videos are never downloaded).
    """
    name = folder.removesuffix(".mp4")

    # rallies (RallySeg.csv) + has_video from the source's video listing
    segments: list[RallySegment] = []
    seg_csv = src.csv_path(folder, "RallySeg.csv")
    avail = src.videos(folder)
    if seg_csv is not None:
        segments = parse_rally_seg(seg_csv)
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

    # shots (label/setN.csv) — row-tolerant parse
    n_shots, skipped, mojibake = 0, 0, 0
    for set_num in (1, 2, 3):
        path = src.csv_path(folder, f"label/set{set_num}.csv")
        if path is None:
            continue
        with open(path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    s = ShotLabel.model_validate(row)
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue
                shot_type = clean_shot_type(s.shot_type)
                if shot_type != s.shot_type:
                    mojibake += 1
                cur.execute(
                    "INSERT INTO shots (match_name, set_no, rally, ball_round, player, "
                    " server, type, aroundhead, backhand, hit_area, landing_area, "
                    " lose_reason, win_reason, getpoint_player, roundscore_a, roundscore_b) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (name, set_num, s.rally, s.ball_round, s.player, s.server,
                     shot_type, int(s.is_aroundhead), int(s.is_backhand),
                     s.hit_area, s.landing_area, s.lose_reason, s.win_reason,
                     s.getpoint_player, s.score_a, s.score_b),
                )
                n_shots += 1

    if not segments and not n_shots:
        raise ValueError("no RallySeg.csv and no label/setN.csv")

    # A/B names need RallySeg (the label CSVs only ever say "A"/"B")
    player_a, player_b = derive_ab(folder, segments) if segments else (None, None)

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
        "mojibake": mojibake,
        "has_video_count": len(avail),
        "set_finals": finals, "winner_side": winner_side,
        "winner_name": player_a if winner_side == "A" else player_b,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--local-data", action="append", default=[], metavar="DIR",
                    help="extra dataset dir in HF layout (repeatable), e.g. data/Data-old")
    ap.add_argument("--catalog-only", action="store_true",
                    help="only build the matches catalog (skip rallies/shots)")
    ap.add_argument("--only", default=None, help="ingest per-shot only for this folder/name")
    ap.add_argument("--limit", type=int, default=None, help="cap number of matches (testing)")
    ap.add_argument("--include-practice", action="store_true",
                    help="also ingest per-shot for NYCU practice clips")
    ap.add_argument("--no-analyze-ids", action="store_true",
                    help="skip the CoachAI lookup (leaves analyze_match_id NULL)")
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

    sources: list = [HFSource(dl)]
    for d in args.local_data:
        sources.append(LocalSource(d))

    analyze_ids = {} if args.no_analyze_ids else fetch_analyze_ids()

    def is_practice(f: str) -> bool:
        return f.removesuffix(".mp4").startswith("NYCU_Other_practice")

    def wanted(f: str) -> bool:
        return ((args.include_practice or not is_practice(f))
                and (args.only is None or f == args.only
                     or f.removesuffix(".mp4") == args.only))

    # Plan first: an earlier source wins, so a folder present in both HF and a local dir is
    # ingested once. `seen` is keyed on the normalized name to also catch the archive's
    # punctuation near-duplicates (SHI_Yu Qi_... vs SHI_Yu_Qi_...).
    seen: set[str] = set()
    catalog: list[tuple[str, object]] = []      # (folder, source) in ingest order
    for src in sources:
        for folder in src.folders():
            key = norm_name(folder)
            if key in seen:
                continue
            seen.add(key)
            catalog.append((folder, src))
    print(f"[1/2] matches catalog: {len(catalog)} folders from "
          f"{', '.join(getattr(s, 'label', '?') for s in sources)}")

    targets = [] if args.catalog_only else [(f, s) for f, s in catalog if wanted(f)]
    if args.limit:
        targets = targets[:args.limit]

    ab_by_folder: dict[str, tuple[str, str]] = {}
    stats, failed = [], []
    print(f"[2/2] ingesting per-shot data for {len(targets)} match(es)…")
    for i, (folder, src) in enumerate(targets, 1):
        short = folder.removesuffix(".mp4")[:55]
        try:
            info = ingest_match(cur, folder, src)
            ab_by_folder[folder] = (info["player_a"], info["player_b"])
            stats.append(info)
            conn.commit()  # persist per match
            print(f"  [{i}/{len(targets)}] {short}  "
                  f"A={info['player_a']} B={info['player_b']} "
                  f"shots={info['n_shots']}(skip {info['skipped']}"
                  f"{', mojibake ' + str(info['mojibake']) if info['mojibake'] else ''}) "
                  f"rallies={info['n_rallies']} video={info['has_video_count']}")
        except Exception as e:  # noqa: BLE001
            failed.append((folder, str(e)))
            print(f"  [{i}/{len(targets)}] {short}  SKIP: {e}")

    for folder, src in catalog:
        pa, pb = ab_by_folder.get(folder, (None, None))
        insert_match_row(cur, folder, dl, pa, pb, getattr(src, "label", "?"),
                         analyze_ids.get(norm_name(folder)))
    conn.commit()

    m = cur.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    pr = cur.execute("SELECT COUNT(*) FROM matches WHERE is_practice=1").fetchone()[0]
    ws = cur.execute("SELECT COUNT(DISTINCT match_name) FROM shots").fetchone()[0]
    an = cur.execute("SELECT COUNT(*) FROM matches "
                     "WHERE analyze_match_id IS NOT NULL").fetchone()[0]
    print(f"\nDB: {db_path}")
    print(f"  matches={m} (official={m - pr}, practice={pr})")
    print(f"  matches with per-shot data={ws}  "
          f"shots={cur.execute('SELECT COUNT(*) FROM shots').fetchone()[0]}  "
          f"rallies={cur.execute('SELECT COUNT(*) FROM rallies').fetchone()[0]}")
    print(f"  matches with analyze_match_id={an}")
    for src in sources:
        lbl = getattr(src, "label", "?")
        n = cur.execute("SELECT COUNT(*) FROM matches WHERE source=?", (lbl,)).fetchone()[0]
        print(f"    source {lbl}: {n}")
    if failed:
        print(f"  no per-shot data ({len(failed)}):")
        for f, e in failed[:10]:
            print(f"    - {f.removesuffix('.mp4')[:50]}: {e}")
        if len(failed) > 10:
            print(f"    … and {len(failed) - 10} more")
    conn.close()


if __name__ == "__main__":
    main()
