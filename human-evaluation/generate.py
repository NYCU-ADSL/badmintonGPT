#!/usr/bin/env python3
"""Generate bilingual evaluation questions and genuine BadmintonGPT replies.

Run in the generator Compose service; evaluation artifacts live under this directory.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("EVAL_REPO", str(HERE.parent)))
MODEL = "gpt-5.6-luna"
INTENTION_SAMPLING = "user-capabilities-poisson-v2"
DATA_SAMPLING = "full-context-scopes-v2"
PRESENTATION_SAMPLING = "compatible-presentation-v1"
PRESENTATIONS = {
    "text": "Ask for a written explanation. Do not add a chart, diagram or interactive-view requirement.",
    "comparison_chart": "Explicitly ask for a chart comparing the main metric across relevant players, matches, tournaments or shot types within the required scope. Choose one useful comparison, not additional metrics.",
    "court_diagram": "Explicitly ask for a badminton court diagram showing the relevant lost-point zones or backcourt positioning. Use supported zones or a clearly labelled schematic; do not invent measured coordinates or trajectories.",
    "interactive_visualization": "Explicitly ask for an interactive visual comparison of the main metric, with one useful selector or filter (such as player, tournament, match or shot type) that fits the scope. Do not invent data or request a dashboard of unrelated metrics.",
    "video": "Explicitly request relevant video clips for retrieval, or a compilation for reel creation. Do not add a chart or interactive-view requirement.",
}
COURT_TOOLS = frozenset({
    "mcp_badminton-analyze_get_backcourt_count",
    "mcp_badminton-analyze_get_lost_point_distribution",
})
QUERY_SCOPES = {
    "player_year": "One player's performance across available matches in one year, not a specific match or rally.",
    "player_shots": "One player's shot selection or effectiveness across matches. For video capabilities, request examples of that player's shot technique, not one match's highlights.",
    "tactical_clips": "Examples of one tactical situation. Do not require the representative match, score or rally; name the focus player only if useful.",
    "cross_match": "One player's differences across tournaments in the focus year, not only the representative match.",
    "player_comparison": "Compare the two focus players across available matches in the focus year, not only their head-to-head match.",
    "single_match": "One focused question about the representative match. Mention a rally only if necessary and supported by the data.",
}
# Only capabilities that directly express a user's badminton goal seed intentions.
# This allowlist affects evaluation question generation, never gateway tools.
INTENTION_TOOLS = frozenset({
    "mcp_badminton-analyze_get_backcourt_count",
    "mcp_badminton-analyze_get_shot_height",
    "mcp_badminton-analyze_get_lost_point_distribution",
    "mcp_badminton-analyze_get_rally_rest_time",
    "mcp_badminton-analyze_get_running_distance",
    "mcp_badminton-analyze_get_shot_win_rate",
    "mcp_badminton-analyze_get_smash_followup_speed",
    "mcp_badminton-analyze_verify_match_statistics",
    "mcp_badminton-video-retrieval_start_video_retrieval",
    "mcp_badminton-reels_generate_reel",
})


def intention_tool_pool(pool):
    selected = [d for d in pool if d["function"]["name"] in INTENTION_TOOLS]
    if not selected:
        raise ValueError("No user-facing capabilities available for intention generation")
    return sorted(selected, key=lambda d: d["function"]["name"])


def poisson_one_plus(rng):
    """Draw 1 + Poisson(lambda=1), using Knuth's algorithm without dependencies."""
    product, count = 1.0, 0
    while product > math.exp(-1):
        product *= rng.random()
        count += 1
    return count


def sample_tools(names, seed, index):
    """Independent count draw and shuffled primary coverage; stable on resume."""
    names = sorted(set(names))
    if not names:
        raise ValueError("Cannot sample an empty intention tool pool")
    requested = poisson_one_plus(random.Random(f"{seed}:{index}:tool-count"))
    count = min(requested, len(names))
    cycle, offset = divmod(index, len(names))
    primaries = names.copy()
    random.Random(f"{seed}:{cycle}:primary-tools").shuffle(primaries)
    primary = primaries[offset]
    remaining = [name for name in names if name != primary]
    extras = random.Random(f"{seed}:{index}:extra-tools").sample(remaining, count - 1)
    return {"selected_tools": [primary, *extras], "primary_tool": primary,
            "sampled_tool_count": requested}


def intention_history(rows):
    """Earlier intentions are exclusions, not examples for the next query."""
    return [{"primary_tool": r.get("primary_tool"), "query_scope": r.get("query_scope"), "intention": r["intention"]}
            for r in rows if r.get("intention")][-30:]


def choose_query_scope(index):
    return list(QUERY_SCOPES)[index % len(QUERY_SCOPES)]


def choose_presentation(primary_tool, seed, index):
    """Select an output need separately from function count, with stable retries."""
    if primary_tool not in INTENTION_TOOLS:
        raise ValueError("Unknown primary capability for presentation selection")
    if not primary_tool.startswith("mcp_badminton-analyze_"):
        return "video"
    choices = ["text", "comparison_chart", "interactive_visualization"]
    if primary_tool in COURT_TOOLS:
        choices.append("court_diagram")
    return random.Random(f"{seed}:{index}:presentation").choice(choices)


def presentation_requirement(row):
    name = row["presentation"]
    return {"name": name, "instruction": PRESENTATIONS[name]}


def sample_query_data(db_path, tools, seed, index):
    """Full linked background plus a real catalogue appropriate to the scope."""
    scope = choose_query_scope(index)
    rng = random.Random(seed + index * 1009)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        catalog = [dict(r) for r in db.execute("""
            SELECT m.*, EXISTS(SELECT 1 FROM rallies r WHERE r.match_name=m.name AND r.has_video=1) AS has_video
            FROM matches m WHERE m.is_practice=0
            AND m.player_a IS NOT NULL AND TRIM(m.player_a) != ''
            AND m.player_b IS NOT NULL AND TRIM(m.player_b) != ''
            AND EXISTS(SELECT 1 FROM shots s WHERE s.match_name=m.name) ORDER BY m.name
        """)]
        def player_key(name):
            return " ".join(name.casefold().split())

        def involves(match, players):
            return bool({player_key(match["player_a"]), player_key(match["player_b"])} & {player_key(p) for p in players})

        needs_analysis = any("badminton-analyze" in t for t in tools)
        needs_video = any("badminton-reels" in t for t in tools)
        options = []
        for match in catalog:
            if needs_analysis and match["analyze_match_id"] is None:
                continue
            if needs_video and not match["has_video"]:
                continue
            year = match["year"] if scope in ("player_year", "cross_match", "player_comparison") else None
            if scope in ("player_year", "cross_match", "player_comparison") and year is None:
                continue
            groups = [[match["player_a"], match["player_b"]]] if scope == "player_comparison" else [[match[p]] for p in ("player_a", "player_b")]
            for players in groups:
                related = [m for m in catalog if involves(m, players) and (year is None or m["year"] == year)]
                if scope in ("player_year", "player_shots", "cross_match", "player_comparison"):
                    if any(sum(involves(m, [p]) for m in related) < 2 for p in players):
                        continue
                if scope == "cross_match" and len({m["tournament"] for m in related}) < 2:
                    continue
                options.append((match, players, year, related))
        if not options:
            raise ValueError(f"No database context supports query scope {scope}")
        match, players, year, related = rng.choice(options)
        if scope == "single_match":
            related = [match]
        related_names = {m["name"] for m in related}
        shot_types = sorted({r["type"] for r in db.execute("SELECT DISTINCT match_name,type FROM shots")
                             if r["match_name"] in related_names and r["type"]})
    data = sample_data(db_path, tools, rng, match_name=match["name"])
    data.update(focus={"players": players, "year": year}, related_matches=related,
                available_shot_types=shot_types,
                coverage={"match_count": len(related), "years": sorted({m["year"] for m in related if m["year"] is not None}),
                          "analyzable_match_count": sum(m["analyze_match_id"] is not None for m in related),
                          "note": "Available database recordings only; not an exhaustive season or career. The representative rally and shots are examples, not aggregate evidence."})
    return {"query_scope": scope, "sampled_data": data, "query_data": data}


def validate_resume(manifest, args):
    if manifest.get("answer_source") != "gateway-websocket":
        raise ValueError("Legacy dataset used an instrumented answer process. Use a new dataset ID.")
    if manifest.get("intention_sampling") != INTENTION_SAMPLING:
        raise ValueError("Dataset used a different intention sampling policy. Use a new --dataset to keep existing questions and ratings separate.")
    if manifest.get("data_sampling") != DATA_SAMPLING:
        raise ValueError("Dataset used a different data sampling policy. Use a new --dataset to keep existing questions and ratings separate.")
    if manifest.get("presentation_sampling") != PRESENTATION_SAMPLING:
        raise ValueError("Dataset used a different presentation sampling policy. Use a new --dataset to keep existing questions and ratings separate.")
    if manifest["seed"] != args.seed or manifest["count"] != args.count or manifest["model"] != MODEL:
        raise ValueError("Resume must use the original seed, count and model")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    tmp.replace(path)


def read_json(path):
    return json.loads(path.read_text())


def load_environment():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    os.environ["NANOBOT_MODEL"] = MODEL
    for key in ("CUSTOM_MODEL_API_BASE", "CUSTOM_MODEL_API_KEY", "CUSTOM_MODEL_API_MODEL"):
        os.environ.setdefault(key, "")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required in the project environment")


def make_config(runtime):
    """Configuration for question generation and capability discovery only.

    The answering gateway runs separately and never receives this configuration.
    """
    from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path
    runtime.mkdir(parents=True, exist_ok=True)
    # Persist placeholders, never resolved credentials.
    raw = read_json(ROOT / "nanobot/config.json")
    raw["agents"]["defaults"].update(model=MODEL, modelPreset=None)
    servers = raw["tools"]["mcpServers"]
    servers["badminton-analyze"]["headers"] = {"Authorization": "Bearer ${ANALYZE_MCP_TOKEN}"}
    servers["util"]["args"] = [str(ROOT / "mcps/util/server.py")]
    servers["badminton-db"]["url"] = os.environ.get("EVAL_DB_MCP_URL", "http://badminton-db:8801/mcp")
    path = runtime / "config.json"
    write_json(path, raw)
    set_config_path(path)
    return resolve_config_env_vars(load_config(path))


def parse_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def validate_question(value):
    for key in ("query_en", "query_zh_tw"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"Missing {key}")
    if not re.search(r"[\u4e00-\u9fff]", value["query_zh_tw"]):
        raise ValueError("Traditional Chinese query is missing Chinese text")
    unexpected = {c for c in value["query_zh_tw"] if unicodedata.category(c).startswith("L")
                  and not any(script in unicodedata.name(c, "") for script in ("LATIN", "CJK", "IDEOGRAPH", "BOPOMOFO", "GREEK"))}
    if unexpected:
        raise ValueError("Traditional Chinese query contains unexpected foreign-script letters; translate them into Traditional Chinese")
    return {k: value[k].strip() for k in ("query_en", "query_zh_tw")}


def validate_question_scope(value, row):
    """Reject missing input and wrong focus before sending any query to the gateway."""
    question = validate_question(value)
    text = question["query_en"]
    if re.search(r"\bI (?:will )?provide\b|\bavailable shot sequence\b|\b(?:attached|above) (?:data|file|match|sequence)\b", text, re.I):
        raise ValueError("Question refers to missing input; include actual identifying details or ask a self-contained general question")
    def normalized(value):
        return "".join(c for c in unicodedata.normalize("NFKD", value).casefold() if c.isalnum())
    if row["query_scope"] != "tactical_clips":
        players = row["query_data"]["focus"]["players"]
        if any(normalized(player) not in normalized(text) for player in players):
            raise ValueError("Question must use the supplied focus player names, not substitute other players")
    year = row["query_data"]["focus"]["year"]
    if year is not None and (str(year) not in text or str(year) not in question["query_zh_tw"]):
        raise ValueError("Both translations must include the supplied focus year")
    if row["query_scope"] == "cross_match" and not re.search(r"\b(tournaments?|competitions?|events?)\b", text, re.I):
        raise ValueError("Ask explicitly how the player's pattern differs across tournaments, rather than only giving an overall annual summary")
    return question


async def question_completion(provider, system, payload, artifact, row, path):
    for _ in range(3):
        attempt = row.get("question_attempts", 0) + 1
        row["question_attempts"] = attempt
        write_json(path, row)
        target = artifact if attempt == 1 else artifact.with_name(f"question-revision-{attempt}")
        value = await json_completion(provider, system,
                                      {**payload, "validation_feedback": row.get("question_validation_error")}, target)
        try:
            question = validate_question_scope(value, row)
            row["question_prompt"] = target.with_suffix(".prompt.json").name
            row.pop("question_validation_error", None)
            return question
        except ValueError as exc:
            row["question_validation_error"] = str(exc)
            write_json(path, row)
    raise ValueError("Question validation failed; all draft attempts preserved, no gateway query sent")


async def json_completion(provider, system, payload, artifact):
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    write_json(artifact.with_suffix(".prompt.json"), messages)
    for attempt in range(3):
        response = await provider.chat_with_retry(messages=messages, model=MODEL)
        write_json(artifact.with_suffix(f".attempt-{attempt + 1}.json"), {
            "content": response.content, "usage": response.usage,
            "finish_reason": response.finish_reason, "model": MODEL, "at": stamp(),
        })
        if response.finish_reason == "error":
            raise RuntimeError(f"Model request failed; see {artifact.name} attempt record")
        try:
            return parse_object(response.content)
        except (ValueError, TypeError):
            messages.append({"role": "assistant", "content": response.content or ""})
            messages.append({"role": "user", "content": "Return only a valid JSON object, without fences or commentary."})
    raise ValueError("Model failed to return valid JSON after three attempts")


def sample_data(db_path, tools, rng, *, match_name=None):
    """Pick a compatible match, then linked entries; no writes to the source DB."""
    names = " ".join(tools)
    where = ["m.is_practice = 0"]
    if "badminton-analyze" in names or "badminton_analyze" in names:
        where.append("m.analyze_match_id IS NOT NULL")
    if "reel" in names:
        where.append("EXISTS (SELECT 1 FROM rallies r WHERE r.match_name=m.name AND r.has_video=1)")
    where.append("EXISTS (SELECT 1 FROM shots s WHERE s.match_name=m.name)")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        matches = db.execute("SELECT m.* FROM matches m WHERE " + " AND ".join(where) + " ORDER BY m.name").fetchall()
        if not matches:
            raise ValueError("No database entries compatible with selected tools")
        if match_name is not None:
            matches = [m for m in matches if m["name"] == match_name]
            if not matches:
                raise ValueError("Requested representative match is not compatible")
        match = dict(rng.choice(matches))
        rallies = db.execute("SELECT * FROM rallies WHERE match_name=? ORDER BY set_no,rally_id", (match["name"],)).fetchall()
        rally = dict(rng.choice(rallies)) if rallies else None
        shots = []
        if rally:
            shots = [dict(r) for r in db.execute(
                "SELECT * FROM shots WHERE match_name=? AND set_no=? AND roundscore_a=? AND roundscore_b=? ORDER BY rally,ball_round LIMIT 12",
                (match["name"], rally["set_no"], rally["score_a"], rally["score_b"]))]
        return {"match": match, "rally": rally, "shots": shots}


def publish_dataset(run_dir, manifest):
    rows = [read_json(p) for p in sorted((run_dir / "items").glob("*.json"))]
    ready = [r for r in rows if r.get("status") == "complete"]
    dataset = {"id": manifest["id"], "model": MODEL, "created_at": manifest["created_at"],
               "target_count": manifest["count"], "items": ready}
    write_json(run_dir / "dataset.json", dataset)
    return len(ready)


async def run(args):
    from nanobot.agent.tools.mcp import connect_mcp_servers
    from nanobot.agent.tools.registry import ToolRegistry
    from blackbox_client import query_gateway
    from nanobot.providers.factory import make_provider
    from loguru import logger
    logger.disable("nanobot")
    load_environment()
    run_dir = HERE / "data" / args.dataset
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = (run_dir / "generation.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.exists():
        if not args.resume:
            raise RuntimeError("Dataset already exists; use --resume or a new --dataset")
        manifest = read_json(manifest_path)
        validate_resume(manifest, args)
    else:
        manifest = {"id": args.dataset, "count": args.count, "seed": args.seed, "model": MODEL,
                    "created_at": stamp(), "query_language": "en",
                    "answer_source": "gateway-websocket",
                    "intention_sampling": INTENTION_SAMPLING,
                    "data_sampling": DATA_SAMPLING,
                    "presentation_sampling": PRESENTATION_SAMPLING,
                    "presentation_choices": PRESENTATIONS,
                    "presentation_selection": "Independent seeded uniform choice among compatible formats; video for video primaries; court diagrams only for lost-point zones or backcourt positioning",
                    "query_scope_schedule": list(QUERY_SCOPES),
                    "data_context": "All match/rally/shots categories plus scope-related match catalogue",
                    "tool_count_distribution": {"name": "poisson", "lambda": 1, "offset": 1,
                                                "cap": "available intention tools"},
                    "primary_tool_selection": "seeded shuffled cycles without replacement", "skills": {}}
        for p in sorted((ROOT / "skills").rglob("SKILL.md")):
            manifest["skills"][str(p.relative_to(ROOT))] = p.read_text()
        write_json(manifest_path, manifest)
    discovery_config = make_config(HERE / "runtime" / args.dataset / "discovery")
    pool_path = run_dir / "tool-pool.json"
    if not pool_path.exists():
        print("Discovering enabled MCP tools", flush=True)
        registry = ToolRegistry()
        stacks = await connect_mcp_servers(discovery_config.tools.mcp_servers, registry)
        try:
            pool = [d for d in registry.get_definitions() if d["function"]["name"].startswith("mcp_")]
            expected = sum(len(s.enabled_tools) for s in discovery_config.tools.mcp_servers.values())
            if len(pool) != expected:
                raise RuntimeError(f"MCP discovery incomplete: got {len(pool)}, expected {expected}; retry when all servers are available")
            write_json(pool_path, pool)
        finally:
            for stack in reversed(list(stacks.values())):
                await stack.aclose()
    pool = read_json(pool_path)
    intent_pool = intention_tool_pool(pool)
    write_json(run_dir / "intention-tool-pool.json", intent_pool)
    definitions = {d["function"]["name"]: d for d in intent_pool}
    names = sorted(definitions)
    provider = make_provider(discovery_config)
    situations = ["brief everyday language", "one practical question from a club player",
                  "plain-language question from a beginner", "concise question from a knowledgeable fan",
                  "focused question from a coach", "informal conversational wording",
                  "precise question from an analyst", "curious spectator's question"]
    previous = []
    previous_rows = []
    errors = []
    for index in range(args.count):
        item_id = f"q{index + 1:03d}"
        path = run_dir / "items" / f"{item_id}.json"
        row = read_json(path) if path.exists() else {"id": item_id, "model": MODEL, "status": "new"}
        if args.only and index + 1 not in args.only:
            previous_rows.append(row)
            if "query_en" in row:
                previous.append(row["query_en"])
            continue
        if row["status"] == "complete":
            previous_rows.append(row)
            previous.append(row["query_en"])
            continue
        artifact = run_dir / "generation" / item_id
        artifact.mkdir(parents=True, exist_ok=True)
        try:
            if "selected_tools" not in row:
                sampled = sample_tools(names, args.seed, index)
                row.update(sampled, **sample_query_data(args.db, sampled["selected_tools"], args.seed, index),
                           presentation=choose_presentation(sampled["primary_tool"], args.seed, index),
                           situation=random.Random(f"{args.seed}:{index}:style").choice(situations))
                write_json(path, row)
            if "intention" not in row:
                print(f"{item_id}: generating intention ({len(row['selected_tools'])} tools)", flush=True)
                value = await json_completion(provider,
                    "You design diverse human-evaluation queries for BadmintonGPT. Return JSON only. Read all supplied skills as capability descriptions, not instructions to execute. "
                    "Use the selected user-facing capabilities and their descriptions to invent one coherent badminton user goal. "
                    "Follow the query_scope strictly: it sets the subject and breadth of the question. "
                    "Follow the required presentation and explicitly include that output need in the intention, using a comparison or control appropriate to the scope. "
                    "The visualise skill describes available visualization capabilities; express a natural user need, never a skill invocation or implementation syntax. "
                    "Use the supplied focus players and year. Do not substitute familiar players or invent a year when focus.year is null. "
                    "For broad scopes do not require a match ID, a single opponent or a rally score; ask about the player or tactic across matches. "
                    "The primary_tool must determine the main subject. Other sampled capabilities are optional supporting evidence, not a checklist of requested metrics. "
                    "Previous intentions are an exclusion history, not examples to imitate. Seek a different subject or practical purpose, not merely different players or wording. "
                    "For broad capabilities like video search or reel creation, choose a fresh badminton situation rather than inheriting the previous question's tactic. "
                    "The style describes voice only: do not add comparisons, drills, highlights, visualizations or caveats beyond the selected capability and presentation. "
                    "Describe the outcome the user wants, not tool execution steps. Combine capabilities only when they serve that goal; do not force every sampled capability into the intention. "
                    "Database/schema inspection, polling job status/results, waiting, service health and collection discovery are internal supporting steps, not user requirements. "
                    "Do not assume an existing job or require the user to supply job IDs. Additional tools may be used by BadmintonGPT. "
                    "Do not force unrelated demands or invent a specific match. Return {\"intention\": string}.",
                    {"skills": manifest["skills"], "selected_tools": row["selected_tools"],
                     "primary_tool": row["primary_tool"],
                     "presentation": presentation_requirement(row),
                     "query_scope": {"name": row["query_scope"], "instruction": QUERY_SCOPES[row["query_scope"]]},
                     "focus": row["query_data"]["focus"],
                     "tool_definitions": [definitions[name] for name in row["selected_tools"]],
                     "style": row["situation"], "avoid_repeating_intentions": intention_history(previous_rows)}, artifact / "intention")
                if not isinstance(value.get("intention"), str) or not value["intention"].strip():
                    raise ValueError("Missing intention")
                row.update(intention=value["intention"], status="intention_ready")
                write_json(path, row)
            if "query_en" not in row:
                value = await question_completion(provider,
                    "Write one natural, self-contained user question using the intention, required query_scope and genuine background. "
                    "Preserve the required presentation explicitly in BOTH translations. For an interactive visualization, ask for a useful interaction as well as a visual view. "
                    "Use ordinary user wording (chart, court diagram, filter, clips); do not mention skills, visualise, visualizer code fences or implementation details. "
                    "All match/rally/shots data is background, not a template. Follow the scope and focus players/year, not the granularity of the representative row. "
                    "For player/year, shot-profile, cross-tournament and player-comparison scopes, ask across related matches without enumerating match names, rounds or scores. "
                    "For tactical clips, describe the tactic instead of requiring the representative rally; do not assume it demonstrates that tactic. "
                    "The answering system receives ONLY this question, not the background. Name the actual player/year or match needed to understand it. "
                    "Use the supplied English focus player names in query_en and the focus year in both versions when present; never substitute other players. "
                    "Never say 'the match ID I provide', 'the available shot sequence', 'above', or refer to an attachment or data absent from the question. "
                    "Do not infer annual results from one rally. Related matches indicate data availability, not proven performance or complete season coverage. "
                    "Return JSON with query_en and query_zh_tw, semantically equivalent English and Traditional Chinese (Taiwan). "
                    "Use recognizable player/tournament names, year and round when needed to identify the match; avoid raw filenames, IDs or MCP names. "
                    "Ask for the user's badminton outcome, without adding database/schema inspection, job polling, waiting, service health checks or collection discovery as requirements. "
                    "Do not invent facts, statistics or presume the desired answer. Requests may use additional matches when needed. "
                    "Keep the supplied intention's focus; do not expand it into a multi-metric comparison or borrow topics from earlier questions. "
                    "Write query_zh_tw entirely in Traditional Chinese except proper names and necessary technical terms. "
                    "Vary wording and complexity. Preserve players, years and scope in both translations. Translate quarter-final as 八強 and semi-final as 四強. Return no answer.",
                    {"intention": row["intention"], "data": row["query_data"], "style": row["situation"],
                     "presentation": presentation_requirement(row),
                     "query_scope": {"name": row["query_scope"], "instruction": QUERY_SCOPES[row["query_scope"]]},
                     "avoid_repeating_intentions": intention_history(previous_rows)}, artifact / "question", row, path)
                row.update(validate_question(value))
                if any(row["query_en"].casefold() == q.casefold() for q in previous):
                    raise ValueError("Duplicate question")
                row["status"] = "question_ready"
                write_json(path, row)
            validate_question_scope(row, row)
            previous.append(row["query_en"])
            if args.questions_only:
                continue
            row.update(status="answer_running", started_at=stamp(), answer_source="gateway-websocket")
            write_json(path, row)
            print(f"{item_id}: sending query to BadmintonGPT: {row['query_en'][:140]}", flush=True)
            started = time.monotonic()
            response = await query_gateway(row["query_en"], artifact / "gateway",
                                           base_url=args.gateway, expected_model=MODEL, timeout=args.timeout)
            if not any(m["text"] or m["media_urls"] for m in response["messages"]):
                raise RuntimeError("Gateway completed without an output message; raw frames preserved")
            row.update(answer="\n\n".join(m["text"] for m in response["messages"]),
                       output_messages=response["messages"], gateway_chat_id=response["chat_id"],
                       model=response["model"], media=[], status="complete",
                       completed_at=stamp(), latency_seconds=round(time.monotonic() - started, 2))
            row.pop("error", None)
            write_json(path, row)
            count = publish_dataset(run_dir, manifest)
            print(f"{item_id}: saved ({count}/{args.count} ready)", flush=True)
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}", failed_at=stamp())
            write_json(path, row)
            errors.append(item_id)
            print(f"{item_id}: failed: {type(exc).__name__}: {exc}", flush=True)
        finally:
            previous_rows.append(row)
    ready = publish_dataset(run_dir, manifest)
    print(f"Dataset {args.dataset}: {ready}/{args.count} answers; failed IDs: {errors}", flush=True)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--dataset", default="preview-10-presentation-v1")
    parser.add_argument("--db", type=Path, default=ROOT / "data/badminton.db")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--questions-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--only", type=int, nargs="+", help="Process only these one-based question numbers")
    parser.add_argument("--gateway", default=os.environ.get("EVAL_GATEWAY_URL", "http://gateway:8765"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.dataset) or args.count < 1:
        parser.error("Use a simple dataset ID and positive count")
    if args.only and any(n < 1 or n > args.count for n in args.only):
        parser.error("--only values must fall between 1 and --count")
    asyncio.run(run(args))
