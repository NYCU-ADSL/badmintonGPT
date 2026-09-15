"""Pure check helpers — protocol (A) + convention (B). No side effects."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jsonschema.validators import validator_for

PASS, FAIL, WARN, SKIP, INFO = "PASS", "FAIL", "WARN", "SKIP", "INFO"
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class CheckResult:
    group: str        # "protocol" | "convention"
    name: str
    status: str       # PASS/FAIL/WARN/SKIP/INFO
    detail: str = ""


def _valid_schema(schema) -> tuple[str, str]:
    if not isinstance(schema, dict):
        return FAIL, "inputSchema is not an object (dict)"
    try:
        validator_for(schema).check_schema(schema)
        return PASS, ""
    except Exception as e:  # noqa: BLE001
        return FAIL, f"Invalid JSON Schema: {e}"


def check_tools(tools) -> list[CheckResult]:
    out: list[CheckResult] = []
    if not tools:
        return [CheckResult("protocol", "tools/list has at least 1 tool", FAIL, "No tools available")]
    out.append(CheckResult("protocol", "tools/list has at least 1 tool", PASS, f"{len(tools)} tools: " + ", ".join(t.name for t in tools)))

    names = [t.name for t in tools]
    dups = sorted({n for n in names if names.count(n) > 1})
    out.append(CheckResult("protocol", "Tool names are unique",
                           PASS if not dups else FAIL,
                           "" if not dups else f"Duplicates: {dups}"))

    for t in tools:
        if not _NAME.match(t.name or ""):
            out.append(CheckResult("protocol", f"Tool {t.name!r} name format", WARN,
                                   "Use only [A-Za-z0-9_-] (recommended)"))
        if not (t.description or "").strip():
            out.append(CheckResult("protocol", f"Tool {t.name} has a description", FAIL,
                                   "Empty description: the agent cannot determine when to call the tool"))
        st, det = _valid_schema(getattr(t, "inputSchema", None))
        out.append(CheckResult("protocol", f"Tool {t.name} has a valid inputSchema", st, det))
    return out


def detect_async_job(tools) -> CheckResult:
    names = {t.name for t in tools}
    starters = sorted(n for n in names
                      if n.startswith(("start_", "generate_", "create_", "submit_")))
    has_status = any("status" in n for n in names)
    has_result = any("result" in n for n in names)
    if starters and has_status and has_result:
        return CheckResult("convention", "Asynchronous job convention", INFO,
                           f"Detected {starters} + *status* + *result* (follows the guide)")
    return CheckResult("convention", "Asynchronous job convention", SKIP, "Not detected (optional)")
