#!/usr/bin/env python3
"""Success-metric harness: run the 11-question test bank against the live agent.

Drives `nanobot agent -m "<q>"` as a subprocess (one fresh session per question),
parses the tool-call hints (lines with "↳") and the final answer, then checks:
  (1) tool routing  — was the expected tool/MCP used?
  (2) answer        — does the reply contain the ground-truth signal?

Ground-truth numbers are proven separately by scripts/verify_db.py; here we check
plausible phrasing + correct routing (LLM wording varies).

Env (OPENAI_API_KEY, CF_*) is loaded from the project/reels .env files.
Usage: python eval/run_eval.py [--skip-reels] [--only N]
(Q10/Q11 need the merged DB: ingest.py --local-data data/Data-old.)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPT_ENV = ROOT / ".env"  # this project's .env only (no fallback to other projects)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TOOL_LINE = re.compile(r"↳\s*(.+)")
MATCH = "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals"


def load_env() -> dict:
    """Mirror scripts/load_env.sh: export the WHOLE .env, plus the same fallbacks.

    Not just OPENAI_API_KEY: config.json resolves `${VAR}` for every remote MCP's
    credentials and for the model, and **nanobot aborts on an unset `${VAR}`** — so a
    partial env makes `nanobot agent` die at startup and every case reports "tools: (none)".
    """
    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/.local/bin:" + env.get("PATH", "")

    if GPT_ENV.exists():
        for line in GPT_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    # An EMPTY var is "set" (no crash); an UNSET one crashes nanobot at startup.
    env.setdefault("NANOBOT_MODEL", "gpt-5.5")
    for k in ("CUSTOM_MODEL_API_BASE", "CUSTOM_MODEL_API_KEY", "CUSTOM_MODEL_API_MODEL"):
        env.setdefault(k, "")
    if not env.get("OPENAI_API_KEY"):
        print(f"⚠️  OPENAI_API_KEY not in {GPT_ENV} — add it (no fallback).", file=sys.stderr)
    return env


def has(*subs):
    return lambda a: all(s in a for s in subs)


def any_of(*subs):
    return lambda a: any(s in a for s in subs)


# (id, question, expected tool substring (in ↳ lines), answer check, timeout)
CASES = [
    (1, "Which Axelsen matches are in the database?", "query",
     lambda a: sum(x in a for x in ("GINTING", "CHOU", "MOMOTA", "NARAOKA", "LEE")) >= 4, 180),
    (2, "In the Axelsen vs Lee match, how many points did Axelsen win with smashes?", "query",
     any_of("10"), 180),
    (3, "What was the most common reason for losing points in the Axelsen vs Lee match?", "query",
     any_of("out of bounds", "out-of-bounds", "Out of bounds", "Out-of-bounds", "出界"), 180),
    (4, "Compare the two players' lift counts in the Axelsen vs Lee match.", "query",
     has("116", "86"), 180),
    (5, "What were the scores in each of the three games in the Axelsen vs Lee match?", "query",
     lambda a: ("11" in a and "23" in a), 180),
    (6, "Find rallies with video where Lee played net shots in the Axelsen vs Lee match.", "query",
     any_of("net shot", "Net shot", "has_video", "video", "Video", "放小球"), 180),
    (7, f"Make a highlight video of the Axelsen vs Lee match.", "generate_reel",
     any_of("http", "generat", "Generat", "job", "queued", "running"), 200),
    (8, "What is Viktor Axelsen's latest world ranking?", "search",
     any_of("ranking", "Ranking", "BWF", "ranked", "Ranked"), 180),
    (9, "Which years and competition levels does this database cover?", "query",
     lambda a: (any(y in a for y in ("2022", "2023", "2024"))
                and any(x in a for x in ("194", "189", "138", "practice", "official"))), 180),
    # 10: the merged Data-old matches (2023/2024) — unreachable from the HF-only DB.
    (10, "How many matches from 2024 are in the database?", "query", any_of("35"), 180),
    # 11: badminton-analyze routing — must go through badminton-db for analyze_match_id
    #     (=123 for this match) and report the real names, not "Player A"/"Player B".
    (11, "Analyze post-smash recovery speed in the Axelsen vs Lee Zii Jia match (2022 Indonesia Open semifinals).",
     "get_smash_followup_speed",
     # 0.87 / 1.55 are values only badminton-analyze can produce — a DB-only answer
     # (which cannot compute movement speed at all) must not pass this.
     lambda a: (any(n in a for n in ("0.87", "1.55"))
                and "AXELSEN" in a.upper() and "Player A" not in a), 240),
]


def run_one(env, question: str, timeout: int) -> tuple[str, str]:
    p = subprocess.run(
        ["nanobot", "agent", "-m", question],
        env=env, capture_output=True, text=True, timeout=timeout)
    out = ANSI.sub("", (p.stdout or "") + "\n" + (p.stderr or ""))
    tool_lines = "\n".join(
        m.group(1) for m in TOOL_LINE.finditer(out))
    # drop noisy mcp server log lines for the "answer" blob
    answer = "\n".join(
        ln for ln in out.splitlines()
        if "Processing request" not in ln and "server.py:" not in ln)
    return tool_lines, answer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-reels", action="store_true",
                    help="skip Q7 (avoid triggering a remote video render)")
    ap.add_argument("--only", type=int, default=None)
    args = ap.parse_args()
    env = load_env()

    rows = []
    for cid, q, expect_tool, check, timeout in CASES:
        if args.only and cid != args.only:
            continue
        if cid == 7 and args.skip_reels:
            rows.append((cid, "SKIP", "SKIP", q))
            continue
        print(f"\n[Q{cid}] {q}")
        try:
            tool_lines, answer = run_one(env, q, timeout)
        except subprocess.TimeoutExpired as e:
            tool_lines = ANSI.sub("", (e.stdout or b"").decode("utf-8", "ignore")
                                  if isinstance(e.stdout, bytes) else (e.stdout or ""))
            answer = tool_lines
        tool_ok = expect_tool in tool_lines
        ans_ok = bool(check(answer))
        print(f"   tools: {', '.join(t.split('(')[0][:40] for t in tool_lines.splitlines()) or '(none)'}")
        print(f"   tool_match={'PASS' if tool_ok else 'FAIL'} (want '{expect_tool}')  "
              f"answer_match={'PASS' if ans_ok else 'FAIL'}")
        rows.append((cid, "PASS" if tool_ok else "FAIL",
                     "PASS" if ans_ok else "FAIL", q))

    print("\n==================== eval summary ====================")
    tp = ap_ = n = 0
    for cid, t, a, q in rows:
        print(f"  Q{cid}: tool={t:4}  answer={a:4}  | {q[:42]}")
        if t != "SKIP":
            n += 1
            tp += t == "PASS"
            ap_ += a == "PASS"
    print(f"\n  tool routing: {tp}/{n}   answers: {ap_}/{n}")
    if tp != n or ap_ != n:
        sys.exit(1)


if __name__ == "__main__":
    main()
