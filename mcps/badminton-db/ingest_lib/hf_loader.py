"""Self-contained HuggingFace loader for the DB build.

Re-implements the *only* DataLoader members ingest.py uses, directly against
`huggingface_hub`, so badminton-db no longer imports badminton-reels'
`data_loader` (which eagerly pulls in `badminton.config` and would require
OPENAI_API_KEY + FISH_API_KEY just to build the DB). This loader needs only an
optional HF_TOKEN and a writable cache dir.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from .models import RallySegment
from .parse import extract_tournament_round

REPO_ID = "howard9199/Badminton"


class DataLoader:
    """Minimal HF dataset reader for ingest.py (badminton-reels-free).

    Exposes the same member surface ingest.py relied on: `_api`,
    `_download_file`, `_parse_rally_seg`, `_extract_tournament_round`.
    """

    def __init__(self, repo_id: str = REPO_ID, data_dir: str | os.PathLike | None = None) -> None:
        self._repo = repo_id
        self._token = (
            os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or None
        )
        self._local_dir = Path(
            data_dir
            or os.environ.get("BADMINTON_HF_DIR")
            or "/tmp/badminton-hf"
        )
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._api = HfApi(token=self._token)

    def _download_file(self, hf_path: str) -> Path:
        return Path(
            hf_hub_download(
                self._repo,
                hf_path,
                repo_type="dataset",
                local_dir=str(self._local_dir),
                token=self._token,
            )
        )

    def _parse_rally_seg(self, path: Path) -> list[RallySegment]:
        segments: list[RallySegment] = []
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                segments.append(
                    RallySegment(
                        score=row["Score"].strip(),
                        up_court=row["UpCourt"].strip(),
                        down_court=row["DownCourt"].strip(),
                        start_frame=int(row["Start"]),
                        end_frame=int(row["End"]),
                    )
                )
        return segments

    def _extract_tournament_round(self, match_name: str) -> tuple[str, str]:
        return extract_tournament_round(match_name)
