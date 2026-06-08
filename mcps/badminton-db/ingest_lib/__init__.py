"""Self-contained DB-build support for badminton-db (no badminton-reels import).

Vendors the small, stable surface ingest.py needs:
  - RallySegment, ShotLabel  (models.py — verbatim from badminton-reels)
  - DataLoader               (hf_loader.py — minimal HF reader, HF_TOKEN-only)
  - extract_tournament_round (parse.py — verbatim from badminton-reels)
"""
from .hf_loader import REPO_ID, DataLoader
from .models import RallySegment, ShotLabel
from .parse import extract_tournament_round

__all__ = [
    "DataLoader",
    "RallySegment",
    "ShotLabel",
    "extract_tournament_round",
    "REPO_ID",
]
