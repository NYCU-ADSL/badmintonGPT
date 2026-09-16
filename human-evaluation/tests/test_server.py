import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_app


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"id": "test-v1", "model": "test", "target_count": 2, "items": [
        {"id": "q001", "query_en": "First question", "query_zh_tw": "第一題", "answer": "Answer",
         "intention": "PRIVATE TRACE", "sampled_data": {"internal": True}},
        {"id": "q002", "query_en": "Second question", "query_zh_tw": "第二題", "answer": "Answer 2"}]}))
    ratings = tmp_path / "ratings.sqlite3"
    return path, ratings, TestClient(create_app(path, ratings, tmp_path / "dist"))


def put(client, item="q001", code="alice", dataset="test-v1", **rating):
    return client.put(f"/api/datasets/{dataset}/evaluators/{code}/ratings/{item}", json=rating)


def test_branch_rules_and_persistence_across_restart(setup):
    path, ratings, client = setup
    assert put(client, q1="realistic", q2=None).status_code == 200
    assert client.get("/api/evaluators/alice/ratings").json()["completed"] == 0
    assert put(client, q1="realistic", q2="fully_addresses").json()["complete"]
    assert put(client, q1="unrealistic", q2=None).json()["complete"]
    restarted = TestClient(create_app(path, ratings))
    result = restarted.get("/api/evaluators/alice/ratings").json()
    assert result["completed"] == 1
    assert len(result["ratings"]) == 1
    assert result["ratings"][0]["q2"] is None
    assert restarted.get("/api/evaluators/bob/ratings").json()["ratings"] == []


@pytest.mark.parametrize("rating", [
    {"q1": "invalid"}, {"q1": "unrealistic", "q2": "fully_addresses"},
    {"q1": None, "q2": "fully_addresses"}, {"q1": "realistic", "q2": "invalid"},
    {"q1": "realistic", "unexpected": "field"},
])
def test_invalid_ratings_do_not_write(setup, rating):
    _, _, client = setup
    assert put(client, **rating).status_code == 422
    assert client.get("/api/evaluators/alice/ratings").json()["ratings"] == []


def test_dataset_and_item_boundaries(setup):
    path, _, client = setup
    assert put(client, item="missing", q1="unrealistic").status_code == 404
    assert put(client, dataset="old", q1="unrealistic").status_code == 409
    assert put(client, code="x", q1="unrealistic").status_code == 422
    assert put(client, q1="unrealistic").status_code == 200
    data = json.loads(path.read_text())
    data["id"] = "test-v2"
    path.write_text(json.dumps(data))
    assert client.get("/api/evaluators/alice/ratings").json()["completed"] == 0


def test_only_review_data_is_public(setup):
    path, _, client = setup
    response = client.get("/api/dataset")
    assert response.status_code == 200
    assert "PRIVATE TRACE" not in response.text
    assert "sampled_data" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/data/ratings.sqlite3").status_code == 404
    assert client.get("/dataset.json").status_code == 404
    media = path.parent / "media/q001"
    media.mkdir(parents=True)
    (media / "clip.mp4").write_bytes(b"test-video-content")
    assert client.get("/api/media/q001/clip.mp4").content == b"test-video-content"
    assert client.get("/api/media/missing/clip.mp4").status_code == 404
    (media / "secret.txt").symlink_to(path)
    assert client.get("/api/media/q001/secret.txt").status_code == 404


def test_server_ready_before_dataset(tmp_path):
    client = TestClient(create_app(tmp_path / "missing.json", tmp_path / "ratings.db"))
    assert client.get("/api/health").json() == {"status": "ok", "dataset_ready": False}
    assert client.get("/api/dataset").status_code == 503


def test_public_output_preserves_gateway_text_and_urls(setup):
    path, _, client = setup
    data = json.loads(path.read_text())
    original = "  Original reply\n![clip](https://example.org/clip.mp4)  "
    messages = [{"text": original, "media_urls": []}]
    data["items"][0].update(answer=original, output_messages=messages, display_answer="must not replace output")
    path.write_text(json.dumps(data))
    item = client.get("/api/dataset").json()["items"][0]
    assert item["answer"] == original
    assert item["output_messages"] == messages
