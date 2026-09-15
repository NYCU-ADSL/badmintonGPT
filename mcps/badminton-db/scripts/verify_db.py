#!/usr/bin/env python3
"""Verify badminton.db against the ground truth in docs/TASK.md / ground_truth.py (same dir).

Run: python mcps/badminton-db/scripts/verify_db.py [--db PATH]
Exits non-zero if any assertion fails.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

def _default_db() -> str:
    # BADMINTON_DB env wins (containers set it); else walk up to the nearest data/
    # dir (repo-root on host). Walk-up avoids parents[N] IndexError at /app depth.
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "data").is_dir():
            return str(p / "data" / "badminton.db")
    return str(here.parent / "data" / "badminton.db")


DEFAULT_DB = os.environ.get("BADMINTON_DB") or _default_db()
LOCAL = "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals.mp4"
LOCAL_NAME = LOCAL.removesuffix(".mp4")  # join key in rallies/shots

results: list[tuple[bool, str]] = []


def check(label: str, got, expected) -> None:
    ok = got == expected
    results.append((ok, f"{label}: got={got!r} expected={expected!r}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    q = lambda sql, p=(): db.execute(sql, p).fetchall()
    one = lambda sql, p=(): db.execute(sql, p).fetchone()[0]

    # catalog — HF (32) + the merged Data-old archive (162 more; the archive's other 28
    # folders are the HF ones again, deduped on the normalized name)
    check("matches total", one("SELECT COUNT(*) FROM matches"), 194)
    check("matches official", one("SELECT COUNT(*) FROM matches WHERE is_practice=0"), 189)
    check("matches practice", one("SELECT COUNT(*) FROM matches WHERE is_practice=1"), 5)
    check("matches from hf", one("SELECT COUNT(*) FROM matches WHERE source='hf'"), 32)
    check("matches from Data-old",
          one("SELECT COUNT(*) FROM matches WHERE source='Data-old'"), 162)
    check("every match has a source",
          one("SELECT COUNT(*) FROM matches WHERE source IS NULL"), 0)
    check("years within 2022-2024",
          one("SELECT COUNT(*) FROM matches WHERE year NOT BETWEEN 2022 AND 2024"), 0)

    # Q1 Axelsen matches
    check("Q1 Axelsen matches",
          one("SELECT COUNT(*) FROM matches WHERE name LIKE '%AXELSEN%'"), 18)

    # analyze_match_id (badminton-analyze MCP). The local match is the one we verified by
    # hand against CoachAI (its per-set shot counts and B net shots=183 line up exactly).
    check("local analyze_match_id",
          one("SELECT analyze_match_id FROM matches WHERE folder=?", (LOCAL,)), 123)
    mapped = one("SELECT COUNT(*) FROM matches WHERE analyze_match_id IS NOT NULL")
    total_m = one("SELECT COUNT(*) FROM matches")
    results.append((mapped >= 180,
                    f"analyze_match_id mapped: {mapped} of {total_m} matches"))

    # A/B mapping for local match
    row = one_row = db.execute(
        "SELECT player_a, player_b FROM matches WHERE folder=?", (LOCAL,)).fetchone()
    check("local A name", row["player_a"], "Viktor AXELSEN")
    check("local B name", row["player_b"], "LEE Zii Jia")

    # ---- per-match checks: SCOPED to the Axelsen vs Lee match (DB now has 27 matches) ----
    M = (LOCAL_NAME,)

    # Q2 smash winners by A (the kill that won the rally)
    check("Q2 A smash winners",
          one("SELECT COUNT(*) FROM shots WHERE match_name=? AND type='殺球' "
              "AND player='A' AND win_reason IS NOT NULL", M), 10)
    check("Q2b A total smashes",
          one("SELECT COUNT(*) FROM shots WHERE match_name=? AND type='殺球' "
              "AND player='A'", M), 52)

    # Q3 lose_reason distribution (this match)
    lr = {r["lose_reason"]: r["n"] for r in q(
        "SELECT lose_reason, COUNT(*) n FROM shots WHERE match_name=? "
        "AND lose_reason IS NOT NULL GROUP BY lose_reason", M)}
    check("Q3 out of bounds", lr.get("出界"), 50)
    check("Q3 opponent winner landing in court", lr.get("對手落地致勝"), 34)
    check("Q3 did not clear the net", lr.get("未過網"), 21)
    check("Q3 into the net", lr.get("掛網"), 10)
    check("Q3 landing-point misjudgment", lr.get("落點判斷失誤"), 1)

    # Q4 Lifts by player (this match)
    lift = {r["player"]: r["n"] for r in q(
        "SELECT player, COUNT(*) n FROM shots WHERE match_name=? AND type='挑球' "
        "GROUP BY player", M)}
    check("Q4 lifts A", lift.get("A"), 116)
    check("Q4 lifts B", lift.get("B"), 86)

    # Q5 set finals (from rallies, this match)
    finals = {r["set_no"]: (r["a"], r["b"]) for r in q(
        "SELECT set_no, MAX(score_a) a, MAX(score_b) b FROM rallies WHERE match_name=? "
        "GROUP BY set_no ORDER BY set_no", M)}
    check("Q5 set1", finals.get(1), (19, 21))
    check("Q5 set2", finals.get(2), (21, 11))
    check("Q5 set3", finals.get(3), (23, 21))

    # Q6 B net shots (this match) + has_video sanity (count comes from HF listing)
    check("Q6 B net shots", one(
        "SELECT COUNT(*) FROM shots WHERE match_name=? AND type='放小球' "
        "AND player='B'", M), 183)
    has_video_db = one(
        "SELECT COUNT(*) FROM rallies WHERE match_name=? AND has_video=1", M)
    n_rallies = one("SELECT COUNT(*) FROM rallies WHERE match_name=?", M)
    results.append((0 < has_video_db <= n_rallies,
                    f"Q6 has_video sane: {has_video_db} of {n_rallies} rallies"))

    # this match's shot count is stable regardless of how many matches are loaded
    check("local match shots", one(
        "SELECT COUNT(*) FROM shots WHERE match_name=?", M), 1213)

    # full ingest: every folder that ships label CSVs has per-shot data, every folder that
    # ships RallySeg.csv has rallies (the rest are catalog-only: practice clips + folders
    # the archive carries with no annotation at all)
    check("matches with per-shot data", one(
        "SELECT COUNT(DISTINCT match_name) FROM shots"), 138)
    check("matches with rallies", one(
        "SELECT COUNT(DISTINCT match_name) FROM rallies"), 169)

    # shot types stay a closed Chinese enum: one Data-old label CSV is mojibake upstream
    # and ingest.clean_shot_type folds it into 未知球種 (see that helper's comment).
    check("no mojibake shot types",
          one("SELECT COUNT(*) FROM shots WHERE type LIKE '%?%'"), 0)

    db.close()

    print("\n=== verify_db ===")
    passed = 0
    for ok, msg in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
        passed += ok
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
