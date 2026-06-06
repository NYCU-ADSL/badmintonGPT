"""mcp-test CLI — read-only MCP conformance + convention checker."""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys

from . import checks, client, http_probe
from .checks import CheckResult, FAIL, INFO, PASS, SKIP, WARN

ICON = {PASS: "✅", FAIL: "❌", WARN: "⚠️", SKIP: "➖", INFO: "ℹ️"}


def _fmt_exc(e: BaseException) -> str:
    """Unwrap ExceptionGroup (anyio/TaskGroup) to the most informative leaf."""
    seen = 0
    while isinstance(e, BaseExceptionGroup) and e.exceptions and seen < 5:
        e = e.exceptions[0]
        seen += 1
    return f"{type(e).__name__}: {e}"


def _parse_kv(items: list[str], sep: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for it in items or []:
        if sep not in it:
            raise SystemExit(f"bad '{it}', expected K{sep}V")
        k, v = it.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


async def _run_mcp_checks(session, results: list[CheckResult], timeout: float) -> None:
    init = await asyncio.wait_for(session.initialize(), timeout)
    si = init.serverInfo
    results.append(CheckResult("protocol", "connect + initialize", PASS,
                               f"{si.name} v{si.version} (protocol {init.protocolVersion})"))
    caps = init.capabilities

    tools = (await asyncio.wait_for(session.list_tools(), timeout)).tools
    results.extend(checks.check_tools(tools))
    results.append(checks.detect_async_job(tools))

    # resources / prompts — only if advertised
    for cap_name, lister, label in (
        ("resources", session.list_resources, "resources/list"),
        ("prompts", session.list_prompts, "prompts/list"),
    ):
        if getattr(caps, cap_name, None) is None:
            results.append(CheckResult("protocol", label, SKIP, f"server 未宣告 {cap_name} capability"))
            continue
        try:
            res = await asyncio.wait_for(lister(), timeout)
            items = getattr(res, cap_name)
            results.append(CheckResult("protocol", label, PASS, f"{len(items)} 個"))
        except Exception as e:  # noqa: BLE001
            results.append(CheckResult("protocol", label, FAIL, f"{type(e).__name__}: {e}"))

    # safe negative: unknown tool must error gracefully (no business tool runs)
    probe_timeout = min(timeout, 8.0)
    try:
        r = await asyncio.wait_for(session.call_tool("__mcp_test_nonexistent__", {}), probe_timeout)
        is_err = bool(getattr(r, "isError", False))
        results.append(CheckResult("protocol", "未知工具回正規錯誤",
                                   PASS if is_err else WARN,
                                   "回 isError" if is_err else "未知工具竟回正常結果"))
    except asyncio.TimeoutError:
        results.append(CheckResult("protocol", "未知工具回正規錯誤", WARN,
                                   f"{probe_timeout:.0f}s 內未回應（server 可能未正確拒絕未知工具）"))
    except Exception as e:  # noqa: BLE001 — McpError 等協定錯誤即正確行為
        results.append(CheckResult("protocol", "未知工具回正規錯誤", PASS, f"以錯誤回應 ({type(e).__name__})"))


async def _run_http_conventions(base: str, headers: dict[str, str], results: list[CheckResult], timeout: float) -> None:
    # /healthz with auth
    st, body = await http_probe.get(base + "/healthz", headers, timeout)
    if st is None:
        results.append(CheckResult("convention", "/healthz 可達", WARN, f"連線失敗: {body}"))
    elif 200 <= st < 300:
        results.append(CheckResult("convention", "/healthz 200", PASS, f"{st} {body.strip()[:40]}"))
    elif st in (401, 403):
        if headers:
            results.append(CheckResult("convention", "/healthz 200", FAIL, f"帶了 token 仍被拒({st}) — 認證設定有誤"))
        else:
            results.append(CheckResult("convention", "/healthz 200", SKIP, f"需 token（本次未提供 headers）→ {st}"))
    else:
        results.append(CheckResult("convention", "/healthz 200", WARN, f"無 healthz 路由或非 2xx ({st})"))

    # auth gating: same path WITHOUT token
    if headers:
        st2, _ = await http_probe.get(base + "/healthz", None, timeout)
        if st2 in (401, 403):
            results.append(CheckResult("convention", "未帶 token 被擋", PASS, f"擋下({st2}) ✅"))
        elif st2 is None:
            results.append(CheckResult("convention", "未帶 token 被擋", WARN, "連線失敗，無法判斷"))
        else:
            results.append(CheckResult("convention", "未帶 token 被擋", WARN, f"端點似乎未受保護（回 {st2}）"))
    else:
        results.append(CheckResult("convention", "未帶 token 被擋", SKIP, "未提供 headers，略過"))

    results.append(CheckResult("convention", "/files 下載 & 錯誤格式", INFO,
                               "唯讀模式不實測（需 functional 測試才驗得到）"))


def _report(results: list[CheckResult], as_json: bool, strict: bool) -> int:
    fails = sum(1 for r in results if r.status == FAIL or (strict and r.status == WARN))
    if as_json:
        print(json.dumps({
            "results": [r.__dict__ for r in results],
            "summary": {s: sum(1 for r in results if r.status == s)
                        for s in (PASS, WARN, FAIL, SKIP, INFO)},
            "ok": fails == 0,
        }, ensure_ascii=False, indent=2))
        return 1 if fails else 0

    for group in ("protocol", "convention"):
        rows = [r for r in results if r.group == group]
        if not rows:
            continue
        print(f"\n## {group}")
        for r in rows:
            line = f"  {ICON.get(r.status, '?')} {r.status:<4} {r.name}"
            if r.detail:
                line += f" — {r.detail}"
            print(line)
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, WARN, FAIL, SKIP, INFO)}
    print(f"\n{len(results)} checks: "
          f"{counts[PASS]} PASS, {counts[WARN]} WARN, {counts[FAIL]} FAIL, "
          f"{counts[SKIP]} SKIP, {counts[INFO]} INFO"
          + ("  [--strict: WARN 算失敗]" if strict else ""))
    print("結果:", "❌ FAIL" if fails else "✅ OK")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="mcp-test",
        description="Read-only conformance tester for an MCP server (no business tools are called).")
    ap.add_argument("url", nargs="?", help="remote MCP endpoint, e.g. https://host/mcp")
    ap.add_argument("--stdio", help='test a local stdio server instead, e.g. "python server.py"')
    ap.add_argument("--env", action="append", default=[], help="K=V env for --stdio (repeatable)")
    ap.add_argument("--header", action="append", default=[], help='HTTP header "K: V" (repeatable)')
    ap.add_argument("--base-url", help="base for /healthz & auth-gating (default: url without trailing /mcp)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="treat WARN as failure")
    args = ap.parse_args(argv)

    if not args.url and not args.stdio:
        ap.error("give an MCP URL or --stdio")
    if args.url and args.stdio:
        ap.error("use either URL or --stdio, not both")

    results: list[CheckResult] = []

    async def _run() -> None:
        if args.stdio:
            toks = shlex.split(args.stdio)
            try:
                await asyncio.wait_for(
                    _stdio_flow(toks[0], toks[1:], _parse_kv(args.env, "="), results, args.timeout),
                    args.timeout * 3)
            except Exception as e:  # noqa: BLE001
                results.append(CheckResult("protocol", "connect + initialize", FAIL, _fmt_exc(e)))
        else:
            headers = _parse_kv(args.header, ":")
            base = args.base_url or (args.url[:-4] if args.url.endswith("/mcp") else args.url.rstrip("/"))
            await _run_http_conventions(base, headers, results, args.timeout)
            try:
                await asyncio.wait_for(_http_flow(args.url, headers, results, args.timeout), args.timeout * 3)
            except Exception as e:  # noqa: BLE001
                results.append(CheckResult("protocol", "connect + initialize", FAIL, _fmt_exc(e)))

    asyncio.run(_run())
    return _report(results, args.json, args.strict)


async def _http_flow(url, headers, results, timeout):
    async with client.open_http(url, headers) as session:
        await _run_mcp_checks(session, results, timeout)


async def _stdio_flow(cmd, cmdargs, env, results, timeout):
    async with client.open_stdio(cmd, cmdargs, env) as session:
        await _run_mcp_checks(session, results, timeout)


if __name__ == "__main__":
    sys.exit(main())
