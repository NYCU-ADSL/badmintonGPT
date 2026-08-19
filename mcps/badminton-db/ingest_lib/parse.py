"""Folder-name parsing — VENDORED from badminton-reels.

`extract_tournament_round` started as a verbatim copy of
badminton-reels/src/badminton/data_loader.py (DataLoader._extract_tournament_round)
so the matches.tournament / matches.round columns are derived identically to reels,
without importing the badminton-reels package.

DELIBERATE DIVERGENCE (Data-old merge): the 2023/2024 folders name their round with a
trailing abbreviation (`..._2024_SF`, `..._Malasia_Open_2024_F`, `..._Olympics_R16`)
that the upstream word-list never matched — those matches would land with an empty
`round` and a `tournament` swallowing the whole folder name. ROUND_SUFFIXES below is
applied only when the upstream word list does not match, and only as a whole trailing
`_TOKEN`, so every pre-existing folder name still parses byte-identically (that is what
scripts/test_decouple_parity.py pins).
"""
from __future__ import annotations

import re


# Trailing round abbreviations used by the 2023/2024 folders -> readable round names.
# Matched ONLY as a whole `_TOKEN` suffix: bare "F"/"SF" as substrings would fire on
# almost every folder name.
ROUND_SUFFIXES = {
    "R64": "Round of 64", "R32": "Round of 32", "R16": "Round of 16",
    "QF": "Quarter finals", "SF": "Semi finals", "F": "Finals",
    "GS": "Group stage", "Quarterfinals": "Quarter finals",
    "Round_of_32": "Round of 32", "Round_of_16": "Round of 16",
}


def extract_tournament_round(match_name: str) -> tuple[str, str]:
    round_patterns = [
        "Finals", "Final", "Semi_finals", "SemiFinals",
        "Semifinals", "Semi_Finals",
    ]
    round_name = ""
    remaining = match_name
    for pattern in round_patterns:
        if pattern in match_name:
            round_name = pattern.replace("_", " ")
            idx = match_name.rfind(pattern)
            remaining = match_name[:idx].rstrip("_")
            break

    if not round_name:
        m = re.search(r"_(" + "|".join(ROUND_SUFFIXES) + r")$", remaining)
        if m:
            round_name = ROUND_SUFFIXES[m.group(1)]
            remaining = remaining[: m.start()].rstrip("_")

    year_match = re.search(r"_(\d{4})$", remaining)
    tournament = ""
    if year_match:
        year_pos = year_match.start()
        parts = remaining[:year_pos].split("_")
        name_end = 0
        for i, part in enumerate(parts):
            if part and part[0].isupper() and len(part) > 1:
                continue
            else:
                name_end = i
                break
        tournament = " ".join(parts[name_end:]) if name_end > 0 else remaining
    else:
        tournament = remaining

    return (tournament, round_name)
