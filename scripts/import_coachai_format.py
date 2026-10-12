#!/usr/bin/env python3
"""Convert the 2025/2026 CoachAI-format export into the dataset's on-disk layout.

Input: `2025_2026_coachai_format.zip` (`coachai_format/<id>/{set1..4,qa_notes}.csv`, 50
games, ids `2025game1`…`2026game23`) + `homography_matrices.xlsx` (one court homography per
game). Output: one `<id>.mp4/` folder per game in the SAME layout as the HF dataset /
Data-old, so `ingest.py --local-data` and the HF upload treat them like any other match:

  <id>.mp4/label/setN.csv   the old 31-column header, UTF-8 without BOM, CRLF. The export lacks
                            `end_frame_num`; it is filled the way the old data defines it
                            (= the next shot's frame_num in the rally), blank on a rally's
                            last shot (its end is not recorded). Every other cell verbatim.
  <id>.mp4/RallySeg.csv     derived — the export has none. One row per rally with a
                            resolved winner (getpoint_player): Score = set_AA_BB post-rally
                            (the old convention), Start/End = first/last hit frame_num
                            padded like the old hand-cut segments (measured on 1028
                            rallies of the 2023 Data-old matches: Start a median 19
                            frames before the serve, End 60 after the last hit, so the
                            clip shows the serve set-up and the shuttle landing), clamped
                            to not overlap the neighbouring rallies.
                            The export carries no player names, so UpCourt/DownCourt are
                            the side labels "A"/"B", placed per rally by mean hit_y (the
                            smaller image y is the far = up court). A rally where only one
                            side hit (e.g. a serve fault) is placed with the homography
                            instead: it maps the image onto a [-1,1]^2 court whose up half
                            is y > 0 (agrees with the hit_y rule on 4104/4106 two-sided
                            rallies; the per-set majority matches qa_notes' own top/bottom
                            vote in every voted set). Rallies with no winner
                            (unscored sets, unresolved end_reason) are left out, which the
                            old data also does for unsegmented rallies.
  <id>.mp4/homography.csv   new: the game's row from the xlsx (image -> court 3x3 + the 4
                            court corners), cells copied as their exact stored strings.
  <id>.mp4/qa_notes.csv     new: the export's own data-quality notes, kept as provenance.
  <id>.mp4/match_info.csv   new: who/where from BWF_2025_2026_50_matches.xlsx (the game list
                            the export was made from; game N of a year = its Nth row that
                            year): player_a/player_b, tournament, level, round, year, the
                            YouTube video id. With it, RallySeg's UpCourt/DownCourt carry the
                            real names instead of the side labels. A = the sheet's Player 1:
                            checked against the broadcast scoreboard in all 41 games where a
                            lopsided score was on screen (scripts/fetch_coachai_videos.py
                            downloads the videos). ingest.py reads this file for
                            matches.player_a/_b/tournament/round.

ingest.py reads only RallySeg.csv + label/set{1,2,3}.csv; set4.csv (stray post-match
fragments, never scored) and the two new files ride along untouched.

Usage:
  scripts/import_coachai_format.py                  # -> data/Data-coachai/
  scripts/import_coachai_format.py --zip Z --homography X --out DIR
Then: ingest.py --local-data data/Data-coachai  (local)  or
      scripts/upload_data_old_to_hf.py --src data/Data-coachai  (push to HF)

Idempotent: re-running overwrites in place.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOP = "coachai_format/"

# The dataset's label header (Data-old / HF) — the export only lacks end_frame_num.
OLD_HEADER = [
    "rally", "ball_round", "time", "frame_num", "end_frame_num", "roundscore_A",
    "roundscore_B", "player", "server", "type", "aroundhead", "backhand", "hit_height",
    "hit_area", "hit_x", "hit_y", "landing_height", "landing_area", "landing_x",
    "landing_y", "lose_reason", "win_reason", "getpoint_player", "flaw",
    "player_location_area", "player_location_x", "player_location_y",
    "opponent_location_area", "opponent_location_x", "opponent_location_y", "db",
]
RALLYSEG_HEADER = ["Score", "UpCourt", "DownCourt", "Start", "End", "Comment"]
MATCH_INFO_HEADER = ["id", "player_a", "player_b", "tournament", "level", "round", "year",
                     "youtube_id"]
SET_RE = re.compile(r"^set(\d+)\.csv$")
PAD_BEFORE, PAD_AFTER = 19, 60   # frames; medians of the 2023 Data-old RallySeg vs labels


def read_csv_bytes(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def write_csv(path: Path, header: list[str], rows: list[dict | list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        if rows and isinstance(rows[0], dict):
            w = csv.DictWriter(f, fieldnames=header, lineterminator="\r\n")
            w.writeheader()
            w.writerows(rows)
        else:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(header)
            w.writerows(rows)


def group_rallies(rows: list[dict[str, str]]) -> dict[int, list[dict[str, str]]]:
    by: dict[int, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by[int(r["rally"])].append(r)
    return dict(sorted(by.items()))


def convert_labels(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Export rows -> old-header rows, adding end_frame_num = next shot's frame_num."""
    extra = set(rows[0]) - set(OLD_HEADER) if rows else set()
    if extra:
        raise SystemExit(f"unexpected label columns: {sorted(extra)}")
    out = []
    for shots in group_rallies(rows).values():
        for i, r in enumerate(shots):
            nxt = shots[i + 1]["frame_num"] if i + 1 < len(shots) else ""
            out.append({**{k: r.get(k, "") for k in OLD_HEADER}, "end_frame_num": nxt})
    return out


def _mean_y(shots: list[dict[str, str]], side: str) -> float | None:
    ys = [float(s["hit_y"]) for s in shots if s["player"] == side and s["hit_y"]]
    return sum(ys) / len(ys) if ys else None


def _up_by_homography(shots: list[dict[str, str]], h: list[float] | None) -> str:
    """Side on the up court, voted from where each hit lands on the court plane ("" if unknown)."""
    if h is None:
        return ""
    votes = {"A": 0, "B": 0}
    for s in shots:
        if s["player"] not in votes or not s["hit_x"] or not s["hit_y"]:
            continue
        x, y = float(s["hit_x"]), float(s["hit_y"])
        cy = (h[3] * x + h[4] * y + h[5]) / (h[6] * x + h[7] * y + h[8])
        other = "B" if s["player"] == "A" else "A"
        votes[s["player"] if cy > 0 else other] += 1
    if votes["A"] == votes["B"]:
        return ""
    return "A" if votes["A"] > votes["B"] else "B"


def rally_segments(set_no: int, rows: list[dict[str, str]],
                   h: list[float] | None) -> list[list]:
    """RallySeg rows for one set: only rallies whose winner (hence post-score) is known."""
    segs = []
    rallies = list(group_rallies(rows).values())
    for i, shots in enumerate(rallies):
        last = shots[-1]
        if not last["getpoint_player"]:
            continue
        ya, yb = _mean_y(shots, "A"), _mean_y(shots, "B")
        if ya is not None and yb is not None:
            up, down = ("A", "B") if ya <= yb else ("B", "A")
        else:                                    # one side never hit -> homography
            up = _up_by_homography(shots, h)
            down = {"A": "B", "B": "A"}.get(up, "")
        score = f"{set_no}_{int(last['roundscore_A']):02d}_{int(last['roundscore_B']):02d}"
        first_hit, last_hit = int(shots[0]["frame_num"]), int(last["frame_num"])
        start, end = max(0, first_hit - PAD_BEFORE), last_hit + PAD_AFTER
        if i > 0:                                # never reach into the neighbours' hits
            start = max(start, int(rallies[i - 1][-1]["frame_num"]) + 1)
        if i + 1 < len(rallies):
            end = min(end, int(rallies[i + 1][0]["frame_num"]) - 1)
        segs.append([score, up, down, str(start), str(end), "0"])
    return segs


def read_xlsx(path: Path) -> list[list[str]]:
    """First sheet as rows of exact cell strings (stdlib only; numbers keep full precision)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))

    def col(ref: str) -> int:
        n = 0
        for ch in re.match(r"[A-Z]+", ref).group():
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows = []
    for row in sheet.find("m:sheetData", ns).findall("m:row", ns):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            val = "" if v is None else (v.text or "")
            t = c.get("t")
            if t == "s":
                val = shared[int(val)]
            elif t == "b":
                val = "True" if val == "1" else "False"
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            cells[col(c.get("r"))] = val
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    width = len(rows[0])
    return [r + [""] * (width - len(r)) for r in rows if any(r)]


def match_info_by_id(path: Path) -> dict[str, dict[str, str]]:
    """{game id -> MATCH_INFO_HEADER row} from the BWF game list's first sheet (`總表_50場`)."""
    rows = read_xlsx(path)
    hi = next(i for i, r in enumerate(rows) if r and r[0].startswith("序號"))
    col = {k: next(i for i, h in enumerate(rows[hi]) if h.startswith(k))
           for k in ("年度", "賽事", "等級", "輪次", "選手 1", "選手 2", "影片 ID")}
    out, per_year = {}, defaultdict(int)
    for r in rows[hi + 1:]:
        if not r[col["影片 ID"]]:
            continue
        year = str(int(float(r[col["年度"]])))
        per_year[year] += 1
        gid = f"{year}game{per_year[year]}"
        out[gid] = {"id": gid, "player_a": r[col["選手 1"]].strip(),
                    "player_b": r[col["選手 2"]].strip(), "tournament": r[col["賽事"]].strip(),
                    "level": r[col["等級"]].strip(), "round": r[col["輪次"]].strip(),
                    "year": year, "youtube_id": r[col["影片 ID"]].strip()}
    return out


def homography_by_id(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    """{game id -> row}. 2025 rows name the game `gameN`, 2026 rows `2026gameN` -> unify."""
    header, *rows = read_xlsx(path)
    yi, gi = header.index("year"), header.index("game")
    out = {}
    for r in rows:
        year = str(int(float(r[yi])))
        gid = r[gi] if r[gi].startswith(year) else f"{year}{r[gi]}"
        r = list(r)
        r[yi] = year
        out[gid] = r
    return ["id", *header], out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", default=str(REPO / "2025_2026_coachai_format.zip"))
    ap.add_argument("--homography", default=str(REPO / "homography_matrices.xlsx"))
    ap.add_argument("--matches", default=str(REPO / "BWF_2025_2026_50_matches.xlsx"))
    ap.add_argument("--out", default=str(REPO / "data" / "Data-coachai"))
    args = ap.parse_args()

    out = Path(args.out)
    h_header, homs = homography_by_id(Path(args.homography))
    infos = match_info_by_id(Path(args.matches)) if Path(args.matches).is_file() else {}

    games: dict[str, dict[str, bytes]] = defaultdict(dict)
    with zipfile.ZipFile(args.zip) as zf:
        for n in zf.namelist():
            if n.startswith(TOP) and not n.endswith("/") and n.count("/") == 2:
                _, gid, fname = n.split("/")
                games[gid][fname] = zf.read(n)
    print(f"[1/2] {Path(args.zip).name}: {len(games)} games; "
          f"{Path(args.homography).name}: {len(homs)} homographies")
    if set(games) != set(homs):
        print(f"  [warn] games without homography: {sorted(set(games) - set(homs))}; "
              f"homography without game: {sorted(set(homs) - set(games))}")

    print(f"[2/2] writing {out}/")
    for gid in sorted(games, key=lambda g: (g[:4], int(g[8:]))):
        files = games[gid]
        folder = out / f"{gid}.mp4"
        if folder.exists():
            shutil.rmtree(folder)
        h = None
        if gid in homs:
            row = dict(zip(h_header[1:], homs[gid]))
            h = [float(row[f"h{i}{j}"]) for i in (1, 2, 3) for j in (1, 2, 3)]
        segs, n_shots, sets = [], 0, []
        for fname in sorted(files, key=lambda f: (not SET_RE.match(f), f)):
            m = SET_RE.match(fname)
            if not m:
                continue
            set_no = int(m.group(1))
            rows = read_csv_bytes(files[fname])
            write_csv(folder / "label" / fname, OLD_HEADER, convert_labels(rows))
            segs += rally_segments(set_no, rows, h)
            n_shots += len(rows)
            sets.append(set_no)
        info = infos.get(gid)
        if info:
            names = {"A": info["player_a"], "B": info["player_b"]}
            segs = [[sc, names.get(up, up), names.get(down, down), *rest]
                    for sc, up, down, *rest in segs]
            write_csv(folder / "match_info.csv", MATCH_INFO_HEADER, [info])
        if segs:
            write_csv(folder / "RallySeg.csv", RALLYSEG_HEADER, segs)
        if "qa_notes.csv" in files:
            qa = list(csv.reader(io.StringIO(files["qa_notes.csv"].decode("utf-8-sig"))))
            write_csv(folder / "qa_notes.csv", qa[0], qa[1:])
        if gid in homs:
            write_csv(folder / "homography.csv", h_header, [[gid, *homs[gid]]])
        print(f"  {gid:<11} sets={sets} shots={n_shots} rallyseg={len(segs)}"
              f"{'' if gid in homs else ' NO-HOMOGRAPHY'}"
              f"{'  A=' + info['player_a'] + ' B=' + info['player_b'] if info else ' NO-MATCH-INFO'}")


if __name__ == "__main__":
    main()
