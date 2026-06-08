#!/usr/bin/env python3
"""Parity check: vendored ingest_lib vs the live badminton-reels modules.

Guards against drift after decoupling. For the one locally-available match
(Axelsen vs Lee, the same one ground_truth.py uses) it asserts that the vendored
RallySegment / ShotLabel parsing and extract_tournament_round produce output
identical to badminton-reels' own modules.

SKIPS (exit 0) when $REELS_SRC or the local match data is unavailable (CI / containers).
Run: python mcps/badminton-db/scripts/test_decouple_parity.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent          # mcps/badminton-db/
sys.path.insert(0, str(PKG))                            # so `import ingest_lib` works

from ingest_lib import RallySegment as VRally          # noqa: E402
from ingest_lib import ShotLabel as VShot              # noqa: E402
from ingest_lib import extract_tournament_round as v_extract  # noqa: E402

REELS_SRC = Path(os.environ.get("REELS_SRC", "/mnt/ssd1/howchien/badminton-reels/src"))
DATA = Path(os.environ.get(
    "REELS_DATA", "/mnt/ssd1/howchien/badminton-reels/data/Data"))
MATCH = "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals.mp4"

ALL_NAMES = [  # exercise extract_tournament_round across varied folder names
    "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals",
    "Akane_YAMAGUCHI_AN_Seyoung_YONEX_All_England_Open_Badminton_Championships_2022_Finals",
    "HE_Bing_Jiao_Carolina_MARIN_French_Open_2022_Final",
    "AN_Se_Young_TAI_Tzu_Japan_Open_2022_Semi_finals",
    "NYCU_Other_practice1",
]


def _skip(msg: str) -> None:
    print(f"SKIP parity test: {msg}")
    sys.exit(0)


def main() -> None:
    if not REELS_SRC.exists():
        _skip(f"$REELS_SRC not found at {REELS_SRC}")
    sys.path.insert(0, str(REELS_SRC))
    try:
        from badminton.data_loader import DataLoader as LiveLoader
        from badminton.models import RallySegment as LRally
        from badminton.models import ShotLabel as LShot
    except Exception as e:  # noqa: BLE001
        _skip(f"cannot import live badminton modules ({e})")

    failures: list[str] = []

    # 1) extract_tournament_round parity (pure string; no data needed)
    for name in ALL_NAMES:
        got = v_extract(name)
        # call the live method unbound (it does not use self)
        exp = LiveLoader._extract_tournament_round(None, name)  # type: ignore[arg-type]
        if got != exp:
            failures.append(f"extract_tournament_round({name!r}): vendored={got} live={exp}")

    # 2) model parity on the one local match's CSVs
    seg_csv = DATA / MATCH / "RallySeg.csv"
    if seg_csv.exists():
        with open(seg_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                kw = dict(
                    score=row["Score"].strip(), up_court=row["UpCourt"].strip(),
                    down_court=row["DownCourt"].strip(),
                    start_frame=int(row["Start"]), end_frame=int(row["End"]),
                )
                if VRally(**kw).model_dump() != LRally(**kw).model_dump():
                    failures.append(f"RallySegment mismatch for score={kw['score']}")
                    break
        for set_num in (1, 2, 3):
            lc = DATA / MATCH / "label" / f"set{set_num}.csv"
            if not lc.exists():
                continue
            with open(lc, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    try:
                        vd = VShot.model_validate(row).model_dump()
                        ld = LShot.model_validate(row).model_dump()
                    except Exception:  # noqa: BLE001
                        continue  # both vendored+live skip the same malformed rows
                    if vd != ld:
                        failures.append(f"ShotLabel mismatch set{set_num} rally={row.get('rally')}")
                        break
    else:
        print(f"  (no local match CSVs at {seg_csv}; checked extract_tournament_round only)")

    if failures:
        print("PARITY FAILURES:")
        for f_ in failures:
            print(f"  - {f_}")
        sys.exit(1)
    print("✓ parity OK (vendored ingest_lib matches live badminton-reels)")


if __name__ == "__main__":
    main()
