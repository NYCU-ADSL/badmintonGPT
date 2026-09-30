import asyncio
import json
from pathlib import Path
import random
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate import (
    DATA_SAMPLING, INTENTION_SAMPLING, INTENTION_TOOLS, MODEL, intention_history, intention_tool_pool,
    QUERY_SCOPES, choose_query_scope, poisson_one_plus, sample_data, sample_query_data, sample_tools,
    question_completion, validate_question, validate_question_scope, validate_resume,
    COURT_TOOLS, PRESENTATIONS, PRESENTATION_SAMPLING, PROMPT_POLICY, choose_presentation, presentation_requirement,
    DATABASE_TOOL, WEB_TOOL, WEB_TOPICS, ANSWER_LOCALE, ANSWER_INSTRUCTION_POLICY, source_requirement, scope_requirement,
)


def test_presentations_match_primary_capability_and_cover_formats():
    observed = set()
    for tool in INTENTION_TOOLS:
        modes = {choose_presentation(tool, 42, i) for i in range(300)}
        observed.update(modes)
        if tool == WEB_TOOL:
            assert modes == {"text"}
        elif tool != DATABASE_TOOL and "badminton-analyze" not in tool:
            assert modes == {"video"}
        else:
            expected = {"text", "comparison_chart", "interactive_visualization"}
            if tool in COURT_TOOLS:
                expected.add("court_diagram")
            assert modes == expected
    assert observed == set(PRESENTATIONS)
    with pytest.raises(ValueError, match="Unknown primary"):
        choose_presentation("mcp_util_sleep", 42, 0)


def test_presentation_sampling_is_reproducible_without_changing_tools():
    original = [sample_tools(INTENTION_TOOLS, 20260916, i) for i in range(50)]
    modes = [choose_presentation(row["primary_tool"], 20260916, i) for i, row in enumerate(original)]
    for i in reversed(range(50)):
        assert choose_presentation(original[i]["primary_tool"], 20260916, i) == modes[i]
        assert sample_tools(INTENTION_TOOLS, 20260916, i) == original[i]
    assert any(choose_presentation(row["primary_tool"], 7, i) != modes[i] for i, row in enumerate(original))
    for name in modes:
        requirement = presentation_requirement({"presentation": name})
        assert requirement == {"name": name, "instruction": PRESENTATIONS[name]}


def test_question_checks_real_focus_and_missing_input():
    row = {"query_scope": "player_year", "query_data": {"focus": {"players": ["LEE Zii Jia"], "year": 2023}}}
    with pytest.raises(ValueError, match="focus player"):
        validate_question_scope({"query_en": "How did Viktor Axelsen play in 2023?", "query_zh_tw": "2023 年表現？"}, row)
    with pytest.raises(ValueError, match="focus year"):
        validate_question_scope({"query_en": "How did Lee Zii Jia play?", "query_zh_tw": "李梓嘉表現？"}, row)
    with pytest.raises(ValueError, match="missing input"):
        validate_question_scope({"query_en": "Analyze Lee Zii Jia in the match ID I provide.", "query_zh_tw": "分析比賽"}, row)
    assert validate_question_scope({"query_en": "How did Lee Zii Jia play in 2023?", "query_zh_tw": "李梓嘉 2023 年表現？"}, row)


def test_question_revision_preserves_drafts_before_answering(tmp_path):
    replies = iter([
        {"query_en": "Analyze Viktor Axelsen's shots.", "query_zh_tw": "分析安賽龍的球種。"},
        {"query_en": "Analyze Lee Zii Jia's shots.", "query_zh_tw": "分析李梓嘉的球種。"},
    ])
    async def chat_with_retry(**kwargs):
        return SimpleNamespace(content=json.dumps(next(replies)), usage={}, finish_reason="stop")
    row = {"query_scope": "player_shots", "query_data": {"focus": {"players": ["LEE Zii Jia"], "year": None}}}
    result = asyncio.run(question_completion(SimpleNamespace(chat_with_retry=chat_with_retry), "system", {}, tmp_path / "question", row, tmp_path / "row.json"))
    assert "Lee Zii Jia" in result["query_en"]
    assert row["question_attempts"] == 2
    assert row["question_prompt"] == "question-revision-2.prompt.json"
    assert (tmp_path / "question.attempt-1.json").exists()
    assert (tmp_path / "question-revision-2.attempt-1.json").exists()
    assert "validation_feedback" in (tmp_path / "question-revision-2.prompt.json").read_text()


def test_poisson_count_distribution():
    rng = random.Random(42)
    counts = [poisson_one_plus(rng) for _ in range(100_000)]
    assert min(counts) == 1
    assert sum(counts) / len(counts) == pytest.approx(2, abs=0.02)
    for count, probability in [(1, 0.367879), (2, 0.367879), (3, 0.183940), (4, 0.061313)]:
        assert counts.count(count) / len(counts) == pytest.approx(probability, abs=0.005)
    assert max(counts) > 5  # No legacy five-function cap.


def test_scope_schedule_covers_broad_and_single_match_questions():
    assert {choose_query_scope(i) for i in range(6)} == set(QUERY_SCOPES)
    assert [choose_query_scope(i) for i in range(6)] == [choose_query_scope(i) for i in range(6, 12)]


def test_scoped_context_is_grounded_complete_and_read_only(tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE matches(name TEXT,player_a TEXT,player_b TEXT,year INT,tournament TEXT,is_practice INT,analyze_match_id INT);
          CREATE TABLE rallies(match_name TEXT,set_no INT,rally_id TEXT,has_video INT,score_a INT,score_b INT);
          CREATE TABLE shots(match_name TEXT,set_no INT,rally INT,ball_round INT,roundscore_a INT,roundscore_b INT,type TEXT);
          INSERT INTO matches VALUES
            ('m1','Alice','Bob',2023,'Open A',0,1),
            ('m2','ALICE','Dan',2023,'Open B',0,2),
            ('m3','Bob','Eve',2023,'Open C',0,3),
            ('m4','Alice','Bob',2024,'Open D',0,4),
            ('practice','Alice','Bob',2023,'Training',1,5),
            ('missing-player',NULL,'Alice',2023,'Unknown',0,6);
          INSERT INTO rallies SELECT name,1,'1_00_01',1,0,1 FROM matches;
          INSERT INTO shots SELECT name,1,1,1,0,1,'net' FROM matches;
        """)
    before = path.read_bytes()
    tools = ["mcp_badminton-analyze_get_running_distance"]
    for i in range(6):
        row = sample_query_data(path, tools, 42, i)
        assert row == sample_query_data(path, tools, 42, i)
        data = row["query_data"]
        assert data == row["sampled_data"]
        assert {"match", "rally", "shots", "focus", "related_matches", "available_shot_types", "coverage"} <= data.keys()
        assert data["rally"]["match_name"] == data["shots"][0]["match_name"] == data["match"]["name"]
        assert data["available_shot_types"] == ["net"]
        related = data["related_matches"]
        assert all(m["is_practice"] == 0 for m in related)
        assert all(m["player_a"] and m["player_b"] for m in related)
        assert data["coverage"]["match_count"] == len(related)
        if row["query_scope"] in ("player_year", "player_comparison", "cross_match"):
            assert len(related) >= 2
            assert {m["year"] for m in related} == {data["focus"]["year"]}
        if row["query_scope"] == "player_comparison":
            assert len(data["focus"]["players"]) == 2
            for player in data["focus"]["players"]:
                assert sum(player.casefold() in (m["player_a"].casefold(), m["player_b"].casefold()) for m in related) >= 2
        if row["query_scope"] == "cross_match":
            assert len({m["tournament"] for m in related}) >= 2
        if row["query_scope"] == "single_match":
            assert len(related) == 1
        assert "selected_data_categories" not in row
    assert path.read_bytes() == before
    # Database-only analysis must work without CoachAI IDs or video availability.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE matches SET analyze_match_id=NULL")
        db.execute("UPDATE rallies SET has_video=0")
    before = path.read_bytes()
    row = sample_query_data(path, [DATABASE_TOOL], 42, 2)
    row["question_source"] = "database"
    assert row["query_scope"] == "player_shots"
    assert row["query_data"]["match"]["analyze_match_id"] is None
    assert "type" in source_requirement(row)["schema"]["shots"]
    assert path.read_bytes() == before


def test_web_context_needs_no_database_or_analysis_metrics(tmp_path):
    topics = set()
    for cycle in range(4):
        row = sample_query_data(tmp_path / "missing.db", [WEB_TOOL], 42, cycle * 12)
        assert row == sample_query_data(tmp_path / "missing.db", [WEB_TOOL], 42, cycle * 12)
        row["question_source"] = "web"
        assert row["query_scope"] == "public_web"
        assert scope_requirement(row)["name"] == "public_web"
        assert row["query_data"]["focus"] == {"players": [], "year": None}
        assert "match" not in row["query_data"]
        assert source_requirement(row)["as_of"]
        topics.add(row["query_data"]["topic"])
        validate_question_scope({"query_en": "What are the latest badminton rules?", "query_zh_tw": "最新羽球規則是什麼？"}, row)
    assert topics == set(WEB_TOPICS)
    assert not (tmp_path / "missing.db").exists()


def test_primary_coverage_and_resume_are_independent_of_call_order():
    names = sorted(INTENTION_TOOLS)
    size = len(names)
    assert size == 12
    rows = [sample_tools(names, 42, i) for i in range(size * 3)]
    for start in range(0, size * 3, size):
        assert {r["primary_tool"] for r in rows[start:start + size]} == set(names)
    for i in reversed(range(size * 3)):
        assert sample_tools(list(reversed(names)), 42, i) == rows[i]
        selected = rows[i]["selected_tools"]
        assert selected[0] == rows[i]["primary_tool"]
        assert len(selected) == len(set(selected)) == min(rows[i]["sampled_tool_count"], rows[i]["eligible_tool_count"])


def test_count_caps_at_compatible_tools(monkeypatch):
    monkeypatch.setattr("generate.poisson_one_plus", lambda rng: 6)
    for i in range(12):
        row = sample_tools(INTENTION_TOOLS, 42, i)
        exclusive = row["primary_tool"] in (DATABASE_TOOL, WEB_TOOL)
        assert len(row["selected_tools"]) == (1 if exclusive else 6)
        if exclusive:
            assert row["selected_tools"] == [row["primary_tool"]]
            assert row["question_source"] in ("database", "web")
        else:
            assert DATABASE_TOOL not in row["selected_tools"]
    monkeypatch.setattr("generate.poisson_one_plus", lambda rng: 20)
    for i in range(12):
        row = sample_tools(INTENTION_TOOLS, 42, i)
        assert row["sampled_tool_count"] == 20
        assert len(row["selected_tools"]) == row["eligible_tool_count"]
    with pytest.raises(ValueError, match="empty"):
        sample_tools([], 42, 0)


def test_history_preserves_intents_without_answers_or_query_examples():
    rows = [{"primary_tool": "tool", "intention": str(i), "answer": "PRIVATE", "query_en": "example"}
            for i in range(35)] + [{"status": "new"}]
    history = intention_history(rows)
    assert len(history) == 30
    assert history[0] == {"primary_tool": "tool", "query_scope": None, "intention": "5"}
    assert history[-1] == {"primary_tool": "tool", "query_scope": None, "intention": "34"}
    assert all(set(row) == {"primary_tool", "query_scope", "intention"} for row in history)


def test_intentions_exclude_supporting_tools_without_removing_available_tools():
    names = [
        "mcp_badminton-db_list_tables", "mcp_badminton-db_describe_table", "mcp_badminton-db_query",
        "mcp_util_sleep", "mcp_badminton-reels_get_reel_status", "mcp_badminton-reels_get_reel_result",
        "mcp_badminton-video-retrieval_get_video_retrieval_status",
        "mcp_badminton-video-retrieval_get_video_retrieval_result",
        "mcp_badminton-video-retrieval_get_service_health",
        "mcp_badminton-video-retrieval_list_milvus_collections",
        "mcp_badminton-analyze_get_future_service_status",
        "mcp_badminton-analyze_get_running_distance",
        "mcp_badminton-reels_generate_reel",
        "mcp_badminton-video-retrieval_start_video_retrieval",
    ]
    pool = [{"function": {"name": name, "description": "Definition", "parameters": {}}} for name in names]
    before = json.dumps(pool)
    selected = intention_tool_pool(pool)
    assert [d["function"]["name"] for d in selected] == sorted([DATABASE_TOOL, *names[-3:]])
    assert selected[0]["function"]["description"] == "Definition"
    assert json.dumps(pool) == before


def test_support_only_pool_cannot_generate_intentions():
    with pytest.raises(ValueError, match="No user-facing capabilities"):
        intention_tool_pool([{"function": {"name": "mcp_util_sleep"}}])


def test_resume_cannot_mix_intention_policies():
    args = SimpleNamespace(seed=42, count=10)
    manifest = {"answer_source": "gateway-websocket", "model": MODEL, "seed": 42, "count": 10}
    with pytest.raises(ValueError, match="new --dataset"):
        validate_resume(manifest, args)
    manifest["intention_sampling"] = "user-capabilities-v1"
    with pytest.raises(ValueError, match="new --dataset"):
        validate_resume(manifest, args)
    manifest["intention_sampling"] = INTENTION_SAMPLING
    with pytest.raises(ValueError, match="different data sampling policy"):
        validate_resume(manifest, args)
    manifest["data_sampling"] = "optional-data-poisson-v1"
    with pytest.raises(ValueError, match="different data sampling policy"):
        validate_resume(manifest, args)
    manifest["data_sampling"] = DATA_SAMPLING
    with pytest.raises(ValueError, match="different presentation sampling policy"):
        validate_resume(manifest, args)
    manifest["presentation_sampling"] = "old-policy"
    with pytest.raises(ValueError, match="different presentation sampling policy"):
        validate_resume(manifest, args)
    manifest["presentation_sampling"] = PRESENTATION_SAMPLING
    with pytest.raises(ValueError, match="different prompt policy"):
        validate_resume(manifest, args)
    manifest["prompt_policy"] = "old-policy"
    with pytest.raises(ValueError, match="different prompt policy"):
        validate_resume(manifest, args)
    manifest["prompt_policy"] = PROMPT_POLICY
    with pytest.raises(ValueError, match="different answer locale"):
        validate_resume(manifest, args)
    manifest["answer_locale"] = "zh-TW"
    with pytest.raises(ValueError, match="different answer locale"):
        validate_resume(manifest, args)
    manifest["answer_locale"] = ANSWER_LOCALE
    with pytest.raises(ValueError, match="different answer instruction policy"):
        validate_resume(manifest, args)
    manifest["answer_instruction_policy"] = ANSWER_INSTRUCTION_POLICY
    validate_resume(manifest, args)


def test_sampling_is_seeded_and_filters_supported_data(tmp_path):
    path = tmp_path / "source.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE matches(name TEXT,is_practice INT,analyze_match_id INT);
          CREATE TABLE rallies(match_name TEXT,set_no INT,rally_id TEXT,has_video INT,score_a INT,score_b INT);
          CREATE TABLE shots(match_name TEXT,set_no INT,rally INT,ball_round INT,roundscore_a INT,roundscore_b INT);
          INSERT INTO matches VALUES ('supported',0,123),('unmapped',0,NULL),('practice',1,5);
          INSERT INTO rallies VALUES ('supported',1,'1_00_01',1,0,1),('unmapped',1,'1_00_01',0,0,1);
          INSERT INTO shots VALUES ('supported',1,1,1,0,1),('unmapped',1,1,1,0,1);
        """)
    tools = ["mcp_badminton-analyze_get_running_distance", "mcp_badminton-reels_generate_reel"]
    before = path.read_bytes()
    one = sample_data(path, tools, random.Random(42))
    assert one == sample_data(path, tools, random.Random(42))
    assert one["match"]["name"] == "supported"
    assert one["shots"][0]["match_name"] == "supported"
    assert path.read_bytes() == before


def test_translation_required():
    with pytest.raises(ValueError):
        validate_question({"query_en": "Question", "query_zh_tw": ""})
    assert validate_question({"query_en": " Question ", "query_zh_tw": "問題"})["query_en"] == "Question"
    with pytest.raises(ValueError, match="foreign-script"):
        validate_question({"query_en": "Question", "query_zh_tw": "在目前 उपलब्ध的比賽中？"})


def test_cross_match_question_must_compare_tournaments():
    row = {"query_scope": "cross_match", "query_data": {"focus": {"players": ["Wen Chi Hsu"], "year": 2023}}}
    with pytest.raises(ValueError, match="across tournaments"):
        validate_question_scope({"query_en": "Summarize Wen Chi Hsu in 2023.", "query_zh_tw": "許玟琪 2023 年表現？"}, row)
    assert validate_question_scope({"query_en": "Compare Wen Chi Hsu's lost-point patterns across tournaments in 2023.", "query_zh_tw": "比較許玟琪 2023 年不同賽事的失分模式。"}, row)
