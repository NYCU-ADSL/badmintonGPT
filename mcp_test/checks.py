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
        return FAIL, "inputSchema 不是物件(dict)"
    try:
        validator_for(schema).check_schema(schema)
        return PASS, ""
    except Exception as e:  # noqa: BLE001
        return FAIL, f"非合法 JSON Schema: {e}"


def check_tools(tools) -> list[CheckResult]:
    out: list[CheckResult] = []
    if not tools:
        return [CheckResult("protocol", "tools/list 至少 1 個工具", FAIL, "沒有任何工具")]
    out.append(CheckResult("protocol", "tools/list 至少 1 個工具", PASS, f"{len(tools)} 個: " + ", ".join(t.name for t in tools)))

    names = [t.name for t in tools]
    dups = sorted({n for n in names if names.count(n) > 1})
    out.append(CheckResult("protocol", "工具名稱唯一",
                           PASS if not dups else FAIL,
                           "" if not dups else f"重複: {dups}"))

    for t in tools:
        if not _NAME.match(t.name or ""):
            out.append(CheckResult("protocol", f"工具 {t.name!r} 名稱格式", WARN,
                                   "建議只用 [A-Za-z0-9_-]"))
        if not (t.description or "").strip():
            out.append(CheckResult("protocol", f"工具 {t.name} 有 description", FAIL,
                                   "description 空白：agent 無法判斷何時呼叫"))
        st, det = _valid_schema(getattr(t, "inputSchema", None))
        out.append(CheckResult("protocol", f"工具 {t.name} inputSchema 合法", st, det))
    return out


def detect_async_job(tools) -> CheckResult:
    names = {t.name for t in tools}
    starters = sorted(n for n in names
                      if n.startswith(("start_", "generate_", "create_", "submit_")))
    has_status = any("status" in n for n in names)
    has_result = any("result" in n for n in names)
    if starters and has_status and has_result:
        return CheckResult("convention", "非同步 job 慣例", INFO,
                           f"偵測到 {starters} + *status* + *result*（符合指南）")
    return CheckResult("convention", "非同步 job 慣例", SKIP, "未偵測到（非必要）")
