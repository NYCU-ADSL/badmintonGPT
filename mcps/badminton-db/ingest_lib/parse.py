"""Folder-name parsing — VENDORED from badminton-reels.

`extract_tournament_round` is copied verbatim from
badminton-reels/src/badminton/data_loader.py (DataLoader._extract_tournament_round)
so the matches.tournament / matches.round columns are derived identically to reels,
without importing the badminton-reels package.
"""
from __future__ import annotations

import re


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
