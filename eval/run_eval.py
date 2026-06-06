#!/usr/bin/env python3
"""Success-metric harness: run the 9-question test bank against the live agent.

Drives `nanobot agent -m "<q>"` as a subprocess (one fresh session per question),
parses the tool-call hints (lines with "↳") and the final answer, then checks:
  (1) tool routing  — was the expected tool/MCP used?
  (2) answer        — does the reply contain the ground-truth signal?

Ground-truth numbers are proven separately by scripts/verify_db.py; here we check
plausible phrasing + correct routing (LLM wording varies).

Env (OPENAI_API_KEY, CF_*) is loaded from the project/reels .env files.
Usage: python eval/run_eval.py [--skip-reels] [--only N]
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
    env = dict(os.environ)
    env["PATH"] = f"{Path.home()}/.local/bin:" + env.get("PATH", "")

    def grab(path: Path, key: str) -> str | None:
        if not path.exists():
            return None
        for line in path.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
        return None

    for k in ("OPENAI_API_KEY", "CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET"):
        if v := grab(GPT_ENV, k):
            env[k] = v
    if not env.get("OPENAI_API_KEY"):
        print(f"⚠️  OPENAI_API_KEY not in {GPT_ENV} — add it (no fallback).", file=sys.stderr)
    return env


def has(*subs):
    return lambda a: all(s in a for s in subs)


def any_of(*subs):
    return lambda a: any(s in a for s in subs)


# (id, question, expected tool substring (in ↳ lines), answer check, timeout)
CASES = [
    (1, "資料庫裡有哪些 Axelsen 的比賽？", "query",
     lambda a: sum(x in a for x in ("GINTING", "CHOU", "MOMOTA", "NARAOKA", "LEE")) >= 4, 180),
    (2, "Axelsen vs Lee 那場，Axelsen 用殺球得了幾分？", "query",
     any_of("10"), 180),
    (3, "Axelsen vs Lee 那場最常見的失分原因是什麼？", "query",
     any_of("出界"), 180),
    (4, "Axelsen vs Lee 那場，比較兩位選手挑球的使用次數。", "query",
     has("116", "86"), 180),
    (5, "Axelsen vs Lee 那場三局比分各是多少？", "query",
     lambda a: ("11" in a and "23" in a), 180),
    (6, "幫我找 Axelsen vs Lee 那場 Lee 放小球、而且有影片的回合。", "query",
     any_of("放小球", "has_video", "影片"), 180),
    (7, f"幫我做一支 Axelsen vs Lee 這場的精華短影音。", "generate_reel",
     any_of("http", "生成", "job", "queued", "running"), 200),
    (8, "Viktor Axelsen 最近的世界排名如何？", "search",
     any_of("排名", "ranking", "BWF", "名"), 180),
    (9, "這個資料庫收錄哪一年、哪些等級的比賽？", "query",
     lambda a: ("2022" in a and any(x in a for x in ("27", "32", "練習", "正式"))), 180),
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
