# mcp-test — MCP server conformance tester

After a subproject finishes its MCP server, use this CLI for quick acceptance checks: point it at the MCP
endpoint to run **read-only** checks (**no business tools are called → no side effects on your server**).
It outputs a report and exit code suitable for CI.

Checks cover the **general MCP protocol** and **this team's guide conventions** (see `REMOTE_MCP_SERVER_GUIDE.md`).

---

## Installation / execution

Within this repo (with `.venv` ready):
```bash
.venv/bin/python -m mcp_test <MCP_URL> [options]
```

For other subprojects, simply copy the `mcp_test/` directory (dependencies: `mcp`, `jsonschema`, `httpx` only):
```bash
pip install mcp jsonschema httpx        # Or uv add
python -m mcp_test <MCP_URL> [options]
```

## Usage

```bash
# 1) Remote MCP (Streamable HTTP) + Cloudflare Access service token
python -m mcp_test https://my-mcp.<zone>/mcp \
  --header "CF-Access-Client-Id: $MYMCP_CF_CLIENT_ID" \
  --header "CF-Access-Client-Secret: $MYMCP_CF_CLIENT_SECRET"

# 2) Containerized internal MCP (Streamable HTTP, compose network, no auth)
#    This repo's badminton-db uses this setup: its own container, service name badminton-db, :8801/mcp.
#    From a sibling container on the same compose network (e.g. gateway):
python -m mcp_test http://badminton-db:8801/mcp
#    From the host (HOST/DEV mode, server runs as local HTTP:
#    MCP_HOST=127.0.0.1 python mcps/badminton-db/server.py):
python -m mcp_test http://127.0.0.1:8801/mcp

# 3) Local stdio server (e.g. mcps/util/server.py, or badminton-db with MCP_TRANSPORT=stdio)
python -m mcp_test --stdio "/path/.venv/bin/python /path/mcps/util/server.py" --env SOME_VAR=/abs/path

# 4) JSON output for CI; --strict treats WARN as failure too
python -m mcp_test https://my-mcp.<zone>/mcp --header "..." --json --strict
```

Options:

| Option | Description |
|---|---|
| `<URL>` | Remote MCP endpoint (e.g. `https://host/mcp`); mutually exclusive with `--stdio` |
| `--stdio "CMD ARGS"` | Test a local stdio server instead |
| `--env K=V` | Environment variables for `--stdio` (repeatable) |
| `--header "K: V"` | HTTP headers/authentication (repeatable) |
| `--base-url URL` | For healthz / auth gating; defaults to the URL with trailing `/mcp` removed |
| `--timeout 30` | Timeout in seconds per step |
| `--json` | Output JSON (including summary and ok) |
| `--strict` | Treat WARN as failure |

**Exit code**: nonzero if any FAIL; otherwise 0 (WARN also counts as failure with `--strict`).

---

## Checks

**A. General MCP protocol**

- Connect and `initialize` handshake; record serverInfo / protocolVersion.
- `tools/list` ≥ 1 tool; unique, valid tool names; **each has a description**; `inputSchema` is valid JSON Schema.
- `resources/list`, `prompts/list` (tested only when declared by the server; empty lists pass).
- Call a **nonexistent tool** → expect a proper MCP error (protocol level; no business logic runs).

**B. This team's guide conventions** (WARN by default; FAIL with `--strict`)

- `/healthz` returns 2xx with a token.
- **Requests without a token are blocked** (Cloudflare Access → 401/403).
- **Asynchronous job convention**: detect `start_*`/`generate_*` + `*status*` + `*result*` (INFO).
- `/files` download and error format: not exercised in read-only mode (INFO; requires functional testing).

> Statuses: `PASS` passed, `FAIL` failed, `WARN` improvement recommended, `SKIP` not applicable, `INFO` informational.

---

## CI example (GitHub Actions)

```yaml
- name: MCP conformance
  run: |
    pip install mcp jsonschema httpx
    python -m mcp_test "$MCP_URL" \
      --header "CF-Access-Client-Id: $CF_ID" \
      --header "CF-Access-Client-Secret: $CF_SECRET" \
      --strict
  env:
    MCP_URL: https://my-mcp.example.com/mcp
    CF_ID: ${{ secrets.MYMCP_CF_CLIENT_ID }}
    CF_SECRET: ${{ secrets.MYMCP_CF_CLIENT_SECRET }}
```

---

## Scope and limitations

- **Read-only**: performs only `list/describe/initialize` and protocol-level negative checks; **does not call business tools**. It cannot verify actual tool output, full async-job workflows, or real `/files` downloads. Those require functional tests (possible future extension: a `mcp-test.json` mapping tools → parameters → expectations).
- Supports three types: remote servers built following `REMOTE_MCP_SERVER_GUIDE.md` (public Streamable HTTP with a token), this repo's containerized internal Streamable HTTP (e.g. `http://badminton-db:8801/mcp`, without auth), and local stdio. Internal MCPs have no Cloudflare Access, so the "requests without a token are blocked" WARN does not apply (ignore or `SKIP`).

## References

- Building a server: `REMOTE_MCP_SERVER_GUIDE.md`, `ADD_NEW_MCP.md`
- Connection settings: `reels_mcp_usage.md`
