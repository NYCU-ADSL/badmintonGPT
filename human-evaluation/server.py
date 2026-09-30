"""Small evaluation API. Only published questions, media and per-code ratings are public."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, model_validator

HERE = Path(__file__).resolve().parent


class RatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q1: Literal["realistic", "somewhat_realistic", "unrealistic"] | None = None
    q2: Literal["fully_addresses", "partially_addresses", "does_not_address"] | None = None

    @model_validator(mode="after")
    def conditional_answer(self):
        if self.q1 not in {"realistic", "somewhat_realistic"} and self.q2 is not None:
            raise ValueError("Q2 must be empty unless Q1 is realistic or somewhat realistic")
        return self


def completed(q1, q2):
    return q1 == "unrealistic" or (q1 in {"realistic", "somewhat_realistic"} and q2 is not None)


def create_app(dataset_path=None, ratings_path=None, dist_path=None):
    dataset_path = Path(dataset_path or os.environ.get("EVAL_DATASET", HERE / "data/preview-10-blackbox/dataset.json"))
    ratings_path = Path(ratings_path or os.environ.get("EVAL_RATINGS", HERE / "data/ratings.sqlite3"))
    dist_path = Path(dist_path or HERE / "web/dist")
    ratings_path.parent.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="BadmintonGPT Human Evaluation", docs_url=None, redoc_url=None, openapi_url=None)

    def connect():
        db = sqlite3.connect(ratings_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS ratings (
            dataset_id TEXT NOT NULL, evaluator_code TEXT NOT NULL, item_id TEXT NOT NULL,
            q1 TEXT, q2 TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY (dataset_id, evaluator_code, item_id)
        )""")

    def dataset():
        try:
            value = json.loads(dataset_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            raise HTTPException(503, "題庫尚在準備，請稍後重新整理。 / The questions are being prepared. Please refresh later.")
        return value

    def check_code(code):
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", code):
            raise HTTPException(422, "評測代碼需為 3–64 個英文字母、數字、底線或連字號。 / Evaluator codes must contain 3–64 letters (A–Z), numbers, underscores, or hyphens.")
        return code

    @app.middleware("http")
    async def cache_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "dataset_ready": dataset_path.exists()}

    def playback_sources(row):
        # Local display-only copies; never replace the recorded reply or remote URL.
        manifest_path = dataset_path.parent / "playback-media.json"
        if not manifest_path.exists():
            return {}
        entry = json.loads(manifest_path.read_text()).get(row["id"])
        if not entry:
            return {}
        filename = entry.get("filename", "")
        source = entry.get("source_url", "")
        media_root = (dataset_path.parent / "media").resolve()
        path = (media_root / row["id"] / filename).resolve()
        if not filename or Path(filename).name != filename or not path.is_relative_to(media_root) or not path.is_file():
            return {}
        if not source or source not in row.get("answer", ""):
            return {}
        return {source: f"/api/media/{row['id']}/{filename}"}

    @app.get("/api/dataset")
    def get_dataset():
        data = dataset()
        return {"id": data["id"], "model": data["model"], "target_count": data["target_count"],
                "items": [{"id": r["id"], "query_en": r["query_en"], "query_zh_tw": r["query_zh_tw"],
                           "answer": r["answer"], "media": r.get("media", []),
                           "output_messages": r.get("output_messages"), "playback_sources": playback_sources(r)}
                          for r in data["items"]]}

    @app.get("/api/evaluators/{code}/ratings")
    def get_ratings(code: str):
        check_code(code)
        data = dataset()
        ids = {r["id"] for r in data["items"]}
        with connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT item_id,q1,q2,updated_at FROM ratings WHERE dataset_id=? AND evaluator_code=?",
                (data["id"], code)) if r["item_id"] in ids]
        return {"dataset_id": data["id"], "ratings": rows,
                "completed": sum(completed(r["q1"], r["q2"]) for r in rows), "total": len(ids)}

    @app.put("/api/datasets/{dataset_id}/evaluators/{code}/ratings/{item_id}")
    def put_rating(dataset_id: str, code: str, item_id: str, rating: RatingInput):
        check_code(code)
        data = dataset()
        if dataset_id != data["id"]:
            raise HTTPException(409, "題庫已變更，請重新整理。 / The dataset has changed. Please refresh.")
        if item_id not in {r["id"] for r in data["items"]}:
            raise HTTPException(404, "找不到題目。 / Question not found.")
        timestamp = datetime.now(timezone.utc).isoformat()
        with connect() as db:
            db.execute("""INSERT INTO ratings VALUES (?,?,?,?,?,?)
                ON CONFLICT(dataset_id,evaluator_code,item_id) DO UPDATE SET
                q1=excluded.q1,q2=excluded.q2,updated_at=excluded.updated_at""",
                (dataset_id, code, item_id, rating.q1, rating.q2, timestamp))
        return {"item_id": item_id, "q1": rating.q1, "q2": rating.q2,
                "updated_at": timestamp, "complete": completed(rating.q1, rating.q2)}

    @app.get("/api/media/{item_id}/{filename}")
    def media(item_id: str, filename: str):
        data = dataset()
        if item_id not in {r["id"] for r in data["items"]}:
            raise HTTPException(404)
        root = (dataset_path.parent / "media").resolve()
        path = (root / item_id / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404)
        if path.suffix.lower() in {".html", ".htm", ".svg"}:
            return FileResponse(path, filename=path.name, content_disposition_type="attachment")
        return FileResponse(path)

    # Mount only the built frontend. Never expose raw datasets, traces or credentials.
    if (dist_path / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist_path / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist_path / "index.html").exists():
            raise HTTPException(503, "介面尚未準備完成。 / Frontend build is not ready")
        return FileResponse(dist_path / "index.html", headers={"Cache-Control": "no-cache"})

    return app
