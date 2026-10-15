"""Calculation-only exec (NANOBOT_EXEC_PYTHON_ONLY). [badmintonGPT fork]"""

from __future__ import annotations

import shlex
import subprocess
import sys

import pytest

from nanobot.agent.tools.python_guard import check_code, python_only_command

# The two examples skills/data-analysis/SKILL.md tells the agent to run.
SKILL_EXAMPLES = [
    """python3 -c '
import json
rows = [{"type": "殺球", "n": 42}, {"type": "挑球", "n": 31}]
total = sum(r["n"] for r in rows)
dist = [{"type": r["type"], "n": r["n"], "pct": round(100 * r["n"] / total, 1)} for r in rows]
print(json.dumps({"total": total, "dist": dist}, ensure_ascii=False))
'""",
    """python3 -c '
import json, statistics as st
spr = [12, 8, 21, 5, 33, 9]
print(json.dumps({
    "n_rallies": len(spr),
    "mean": round(st.mean(spr), 1),
    "median": st.median(spr),
    "max": max(spr),
    "p90": round(st.quantiles(spr, n=10)[-1], 1),
}, ensure_ascii=False))
'""",
    "python3 -c 'from collections import Counter; print(Counter([1, 1, 2]).most_common(1))'",
]


@pytest.mark.parametrize("command", SKILL_EXAMPLES)
def test_skill_calculations_still_run(command):
    safe = python_only_command(command)
    assert not safe.startswith("Error:"), safe
    out = subprocess.run(
        [sys.executable if a == "python3" else a for a in shlex.split(safe)],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("command", [
    "nproc",
    "cat /proc/loadavg",
    "python3 -c 'print(1)' && nproc",
    "python3 -c 'print(1)'; cat /etc/passwd",
    "cd /tmp && python3 -c 'print(1)'",
    "python3 script.py",
    "python3 - <<EOF\nprint(1)\nEOF",
    "python3 -c 'import os; print(os.getloadavg())'",
    "python3 -c 'import subprocess; subprocess.run([\"nproc\"])'",
    "python3 -c 'print(open(\"/proc/loadavg\").read())'",
    "python3 -c '__import__(\"os\").getloadavg()'",
    "python3 -c 'import statistics; print(statistics.sys.modules)'",
    "python3 -c 'import json; print(json.codecs.builtins)'",
    "python3 -c 'print(().__class__.__base__.__subclasses__())'",
    "python3 -c 'from fractions import operator'",
    "python3 -c 'print(eval(\"1+1\"))'",
    "python3 -c 'import random; print(random._os)'",
    "python3 -c 'print(f\"{().__class__}\")'",
])
def test_everything_else_is_refused(command):
    assert python_only_command(command).startswith("Error:")


def test_shell_syntax_inside_the_code_is_inert():
    # $(...) inside the quoted code is re-quoted, so sh never expands it.
    safe = python_only_command("python3 -c 'print(\"$(id)\")'")
    assert safe == shlex.join(["python3", "-I", "-c", 'print("$(id)")'])
    out = subprocess.run(["sh", "-c", safe.replace("python3", sys.executable, 1)],
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "$(id)"


def test_reasons_are_reported():
    assert check_code("import os") == "import of 'os'"
    assert check_code("x = (") .startswith("syntax error")
    assert check_code("import math\nprint(math.sqrt(2))") is None
