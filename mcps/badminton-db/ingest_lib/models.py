"""Pydantic models for the DB build — VENDORED from badminton-reels.

Copied verbatim from badminton-reels/src/badminton/models.py (RallySegment,
ShotLabel + the 3 coercion helpers) so badminton-db builds its DB with NO import
of the badminton-reels package. Only the two models ingest.py actually uses are
copied; the dataset CSV schema is fixed, so drift is unlikely (a parity test in
scripts/ guards it when $REELS_SRC is available). If badminton-reels changes its
CSV parsing, re-sync this file.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, model_validator


class RallySegment(BaseModel):
    score: str
    set_num: int = 0
    score_a: int = 0
    score_b: int = 0
    up_court: str
    down_court: str
    start_frame: int
    end_frame: int
    video_path: Path | None = None
    has_video: bool = False

    @model_validator(mode="after")
    def parse_score(self) -> RallySegment:
        parts = self.score.split("_")
        if len(parts) == 3:
            self.set_num = int(parts[0])
            self.score_a = int(parts[1])
            self.score_b = int(parts[2])
        return self


class ShotLabel(BaseModel):
    rally: int
    ball_round: int
    time: str = ""
    frame_num: int = 0
    end_frame_num: int = 0
    score_a: int = 0
    score_b: int = 0
    player: str = ""
    server: str | None = None
    shot_type: str = ""
    is_aroundhead: bool = False
    is_backhand: bool = False
    hit_height: float | None = None
    hit_area: int | None = None
    hit_x: float | None = None
    hit_y: float | None = None
    landing_height: float | None = None
    landing_area: int | None = None
    landing_x: float | None = None
    landing_y: float | None = None
    lose_reason: str | None = None
    win_reason: str | None = None
    getpoint_player: str | None = None

    @model_validator(mode="before")
    @classmethod
    def parse_csv_fields(cls, data: dict) -> dict:
        if isinstance(data, dict):
            data["score_a"] = _int_or(data.get("roundscore_A"), 0)
            data["score_b"] = _int_or(data.get("roundscore_B"), 0)
            data["shot_type"] = data.get("type", "")
            data["is_aroundhead"] = _is_truthy(data.get("aroundhead"))
            data["is_backhand"] = _is_truthy(data.get("backhand"))
            for field in (
                "hit_height", "hit_area", "hit_x", "hit_y",
                "landing_height", "landing_area", "landing_x", "landing_y",
                "frame_num", "end_frame_num",
            ):
                data[field] = _float_or_none(data.get(field))
            for field in ("lose_reason", "win_reason", "getpoint_player"):
                val = data.get(field, "")
                data[field] = val if val and str(val).strip() else None
        return data


def _int_or(val, default: int = 0) -> int:
    if val is None or str(val).strip() == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _float_or_none(val) -> float | None:
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _is_truthy(val) -> bool:
    if val is None or str(val).strip() == "":
        return False
    try:
        return float(val) >= 1.0
    except (ValueError, TypeError):
        return False
