# How to add an MCP (BadmintonGPT)

This document explains how to add an MCP server to BadmintonGPT's nanobot agent. Refer to these three existing examples:
- `mcps/badminton-db/server.py` — MCP in **its own container + Streamable HTTP** (`badminton-db`, **the default pattern**)
- `mcps/util/server.py` — **local stdio** MCP (`util`, a tiny in-process utility)
- Remote `badminton-reels` — **remote Streamable HTTP** MCP (specification in `REELS_MCP_HANDOFF.md`)

Architecture convention: **MCP = access layer (tools), skill = playbook (how to use them)**. Adding an MCP usually means writing a server and registering it in nanobot (optionally adding a skill playbook).

This repo's own MCPs live in `mcps/<name>/`, each self-contained.

> **Relationship to `REMOTE_MCP_SERVER_GUIDE.md`**: this document focuses on connecting an MCP to **this repo's** nanobot
> agent (own-container HTTP / local stdio / writing skills / registration in `nanobot/config.json`). For a complete tutorial on
> building a public **remote** MCP server **from scratch** and deploying it (including `example-mcp-server/`,
> Cloudflare deployment, and publishing a public documentation site), see [`REMOTE_MCP_SERVER_GUIDE.md`](./REMOTE_MCP_SERVER_GUIDE.md).

---

## 0. Choose first: own-container HTTP, local stdio, or remote HTTP?

| | Own container + Streamable HTTP (**default**) | Local stdio | Remote Streamable HTTP |
|---|---|---|---|
| When to use | **Most** MCPs in this repo (state/dependencies, health checks, decoupling from gateway) | **Tiny in-process utilities** (no dependencies, stdlib only, e.g. util's sleep) | Heavy/long tasks (video, GPU), or services already running on another machine/in another repo |
| Where it runs | **Its own compose container** (internal network, not public) | Spawned in-process by gateway (no separate container) | Persistent service elsewhere + public access (Cloudflare Tunnel + Access) |
| nanobot settings | `type:"streamableHttp"` + `url: http://<service>:<port>/mcp` (**no internal auth**) | `command` + `args` + `env` | `type:"streamableHttp"` + public `url` + `headers` |
| Example | `badminton-db` (`mcps/badminton-db/`, service `badminton-db`, :8801/mcp) | `util` (`mcps/util/`, stdio) | `badminton-reels` (`reels-mcp.nycu-adsl.cc`) |

Default to **own container + Streamable HTTP** (follow `mcps/badminton-db/`): each MCP has its own container; the gateway connects over the compose network at `http://<service>:<port>/mcp`, without internal auth.
- Use **local stdio** only for **tiny in-process utilities without dependencies** (follow `mcps/util/`, spawned directly by gateway without a separate container).
- Use **remote HTTP** only for services already running on another machine/in another repo and requiring public access (see `REELS_MCP_HANDOFF.md`).

---

## 1. Own container + Streamable HTTP MCP (default pattern)

`mcps/badminton-db/` is a complete template you can copy. One MCP = one `mcps/<name>/` directory (server + its own Dockerfile + one compose service).

### 1.1 Write the server (FastMCP + streamable-http + /healthz)
Place it in the new `mcps/<name>/server.py`. Depend only on `mcp`, required packages, and stdlib. Template (following `mcps/badminton-db/server.py`):

```python
#!/usr/bin/env python3
"""<name> — streamable-http MCP (own container). Tools: ...
Transport (env MCP_TRANSPORT): "streamable-http" (default, /mcp on MCP_HOST:MCP_PORT)
or "stdio" (for smoke tests).
Env: MCP_HOST (default 0.0.0.0), MCP_PORT (e.g. 8802), <other required variables>.
"""
from __future__ import annotations
import os
from typing import Annotated
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

mcp = FastMCP(                       # This name appears in nanobot's tool prefix
    "<name>",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8802")),   # Different port for each MCP (db=8801)
)

@mcp.tool()
def my_tool(
    arg: Annotated[str, Field(description="What this parameter means, its format/examples (visible to the agent in the schema).")],
) -> dict:
    """Describe the tool's purpose and input in one sentence (the LLM reads this to decide when to call it)."""
    # ... Do the work and return a JSON-serializable dict / list / scalar
    return {"result": arg.upper()}

@mcp.custom_route("/healthz", methods=["GET"])   # Container healthcheck; does not access data
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})

def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    if transport == "stdio":
        mcp.run()                              # stdio (for smoke tests)
    else:
        mcp.run(transport="streamable-http")   # MCP endpoint at /mcp

if __name__ == "__main__":
    main()
```

Conventions (following `mcps/badminton-db/server.py`):
- **streamable-http primary, stdio fallback**: default to `mcp.run(transport="streamable-http")` and support `MCP_TRANSPORT=stdio` so smoke tests need no HTTP server.
- **Always add `GET /healthz`** (`@mcp.custom_route`, without accessing data): container healthchecks use it to support compose's `depends_on: service_healthy`.
- **Read-only/security**: for databases, use `sqlite3.connect("file:...?mode=ro", uri=True)` and allow only SELECT (regex rejects multiple/non-SELECT statements). Validate external inputs against an allowlist.
- **Structured output**: return `dict`/`list`; FastMCP wraps these as structured content. Return errors as `{"error": "..."}` rather than raising (so the agent sees the reason).
- **Tool naming**: use clear verbs (`list_*`/`get_*`/`find_*`/`generate_*`). Explain when to use the tool in its docstring.
- **Describe every parameter**: docstrings become tool-level descriptions; FastMCP **does not** split docstring `Args:` into parameter descriptions. Use `Annotated[T, Field(description="...")]` to expose parameter descriptions in `inputSchema` (put defaults outside `Annotated`: `x: Annotated[int, Field(description="...")] = 8`). `Field` also supports validation such as `ge`/`le`/`pattern`, but these **reject** out-of-range values; if you intend to **silently clamp**, use only `description` and describe the bounds in prose.
- **Self-contained**: vendor dependent libraries/data into `mcps/<name>/` where possible (follow `mcps/badminton-db/ingest_lib/`); avoid cross-repo `sys.path` injection so a single Dockerfile can build it.

### 1.2 Write a per-MCP Dockerfile
In `mcps/<name>/Dockerfile` (build context = that directory; follow `mcps/badminton-db/Dockerfile`):

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
RUN uv pip install --system --no-cache "mcp>=1.0" <other-required-packages>
WORKDIR /app
COPY . /app
RUN useradd -m -u 1000 -s /bin/bash app && chown -R app:app /app
USER app
ENV MCP_HOST=0.0.0.0 MCP_PORT=8802 MCP_TRANSPORT=streamable-http
EXPOSE 8802
# The slim image has no curl; use stdlib urllib to call /healthz
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=10s \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8802/healthz', timeout=3).status==200 else 1)"
CMD ["python3", "/app/server.py"]
```

### 1.3 Add a compose service
Add a service in `docker-compose.yml` (follow `badminton-db`): point the build context to `./mcps/<name>`, mount required volumes, add a `healthcheck` calling `/healthz`, **do not publish a host port** (compose network only), and add `{<name>: {condition: service_healthy}}` to the gateway's `depends_on`:

```yaml
  <name>:
    build:
      context: ./mcps/<name>
    image: badmintongpt-<name>:0.1.0
    restart: unless-stopped
    networks: [default]
    expose: ["8802"]                 # Compose network only (no ports:)
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8802/healthz', timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 5
```

### 1.4 Register in nanobot
Edit **`tools.mcpServers`** in the canonical `nanobot/config.json` template (under `tools`, not top-level). Use the service name as the host on the container network; **no auth needed**:

```jsonc
"mcpServers": {
  "<name>": {
    "type": "streamableHttp",
    "url": "http://<name>:8802/mcp",   // Compose service name + port + /mcp (internal, no auth)
    "enabledTools": ["my_tool"]        // Register only these tools; omit for all
  }
}
```
- No `headers`/token needed on the compose network (**never publish externally or tunnel**).
- HOST/DEV mode (without containers): run the server as local HTTP (`MCP_HOST=127.0.0.1 MCP_PORT=8802 python mcps/<name>/server.py`) and point `~/.nanobot/config.json` to `http://127.0.0.1:8802/mcp`.

### 1.5 Load + test
```bash
# (a) First run a standalone smoke test (without nanobot) — follow mcps/badminton-db/scripts/test_db_mcp.py
#     Open a stdio session with MCP_TRANSPORT=stdio; no HTTP server needed
.venv/bin/python mcps/badminton-db/scripts/test_db_mcp.py   # Adapt to your server / tools

# (b) Build + start containers so gateway connects to the new MCP
docker compose up -d --build
docker compose logs gateway | grep "MCP server '<name>'"     # Expect connected

# (c) Check the HTTP endpoint directly (compose network or host; see MCP_TEST.md)
.venv/bin/python -m mcp_test http://<name>:8802/mcp          # Or http://127.0.0.1:8802/mcp (host mode)
```
Standalone test outline (adapt `mcps/badminton-db/scripts/test_db_mcp.py`): use `MCP_TRANSPORT=stdio` with `StdioServerParameters` → `ClientSession` → `list_tools()` / `call_tool("my_tool", {...})`.

---

## 2. Local stdio MCP (tiny in-process utilities only)

Use this only for **tiny, dependency-free, stdlib-only** in-process utilities (follow `mcps/util/`, whose only tool is sleep). Gateway spawns it directly; it has no separate container.

### 2.1 Write the server
Place it in `mcps/<name>/server.py`. Minimal version (no HTTP, no /healthz):

```python
#!/usr/bin/env python3
"""<name> — local stdio MCP (in-process utility). Tools: ..."""
from typing import Annotated
from mcp.server.fastmcp import FastMCP
from pydantic import Field
mcp = FastMCP("<name>")

@mcp.tool()
def my_tool(
    arg: Annotated[str, Field(description="What this parameter means, its format/examples.")],
) -> dict:
    """Describe the tool's purpose and input in one sentence."""
    return {"result": arg.upper()}

if __name__ == "__main__":
    mcp.run()   # stdio transport
```

### 2.2 Register in nanobot (stdio, following util)
```jsonc
"mcpServers": {
  "<name>": {
    "type": "stdio",
    "command": "python3",
    "args": ["/app/mcps/<name>/server.py"],   // Container path (gateway image has COPY mcps/<name>/)
    "enabledTools": ["my_tool"],
    "toolTimeout": 70                          // Increase for blocking tools such as sleep
  }
}
```
- In container mode, the gateway image needs `COPY mcps/<name>/` (follow util); in HOST/DEV mode, set `command` to the absolute Python path in this repo's `.venv` and `args` to the local absolute path.
- stdio utilities need no separate compose service or healthcheck.

---

## 3. Remote HTTP MCP (another machine/repo, public access)

Use this only for services already running on another machine/in another repo and requiring public access (e.g. `badminton-reels`). See `REELS_MCP_HANDOFF.md` for the full procedure. Key points:
1. Use FastMCP **Streamable HTTP**: `mcp.run(transport="streamable-http")`, binding to `127.0.0.1:<port>`.
2. Expose through **Cloudflare Tunnel** (add ingress → `http://127.0.0.1:<port>`) + **Access service token** authentication.
3. Register in nanobot (public URL; **token headers required**, unlike internal HTTP in §1):
```jsonc
"mcpServers": {
  "<name>": {
    "type": "streamableHttp",
    "url": "https://<name>.nycu-adsl.cc/mcp",
    "headers": {
      "CF-Access-Client-Id": "${<NAME>_CF_CLIENT_ID}",
      "CF-Access-Client-Secret": "${<NAME>_CF_CLIENT_SECRET}"
    },
    "toolTimeout": 120,
    "enabledTools": ["..."]
  }
}
```
4. Always use **asynchronous jobs** for long tasks: `start_*` returns `job_id` → poll `get_*_status` → `get_*_result` (see reels).
5. **Not every remote uses Cloudflare Access**: `badminton-analyze` (CoachAI) uses its own bearer token,
   so headers are `{"Authorization": "Bearer ${ANALYZE_MCP_TOKEN}"}`, and its `.env` variable is not named
   `<NAME>_CF_CLIENT_ID/SECRET`. Before integrating someone else's server, **always fetch tool names with `python -m mcp_test <url> --header ...`**:
   the `register_*_tools` names in `todo0819/mcpserver.json` do not actually exist (the real names are
   `get_*` / `verify_match_statistics`); copying them would make `enabledTools` filter out every tool, leaving none visible to the agent.
6. **Health checks may not have `/healthz`**: CoachAI returns 500 for both `GET /` and `/healthz`; only `/mcp` works.
   In this case, use `method: POST` + JSON-RPC `initialize` as the gatus probe, with the condition
   `[BODY] == pat(*<serverInfo.name>*)` (gatus pattern syntax is `== pat(...)`,
   not `pat ...`). See `monitoring/gatus/config/config.yaml`.

---

## 4. Add a skill playbook (recommended)

MCP provides capabilities; skills explain how to use them well (triggers, conventions, examples). Follow `skills/badminton-db/` and `skills/badminton-reels/`:

```
skills/<name>/
└── SKILL.md            # Frontmatter: name + description (clear trigger conditions); body: usage/examples/conventions
    references/         # Optional: enums, schemas, and other details loaded only after triggering
```

Connect to nanobot (skills are discovered in `~/.nanobot/workspace/skills/`):
```bash
ln -sfn "$PWD/skills/<name>" ~/.nanobot/workspace/skills/<name>
```
Add a line under "Tool routing" in `~/.nanobot/workspace/SOUL.md`: which questions → use the `<name>` skill / MCP tools.

> Note: skill triggering is **heuristic** (based on description), so loading is not guaranteed; MCP tools remain available for direct calls. Also put critical conventions (read-only rules, required filters) in always-loaded SOUL.md to cover missed triggers.

---

## 5. Checklist (whenever adding an MCP)

- [ ] MCP lives in `mcps/<name>/` and is self-contained (vendored libraries/data, no cross-repo injection).
- [ ] **Default pattern (own-container HTTP)**: server has `mcp.run(transport="streamable-http")`, `GET /healthz`, and `MCP_TRANSPORT=stdio` fallback; per-MCP `Dockerfile`; compose service (`expose`, not `ports`, with healthcheck); gateway `depends_on` includes `{<name>: service_healthy}`.
- [ ] (stdio utilities only) Confirm it is tiny and dependency-free; gateway image has `COPY mcps/<name>/`; adjust `toolTimeout` for blocking.
- [ ] `tools.mcpServers.<name>`: internal HTTP uses `streamableHttp` + `http://<name>:<port>/mcp` (**no auth**); stdio uses `command: python3` + container `args`; remote uses `streamableHttp` + public URL + token headers.
- [ ] `enabledTools` exposes only the necessary tools.
- [ ] Secrets for remote MCPs use `${VAR}` + `scripts/load_env.sh` (**reads only this project's `.env`, without fallback to other projects**); internal MCPs need no token.
- [ ] Standalone smoke test passes (`MCP_TRANSPORT=stdio`: list_tools / call_tool / error scenarios).
- [ ] After `docker compose up -d --build`, gateway logs show `MCP server '<name>': connected`; the HTTP endpoint passes `python -m mcp_test http://<name>:<port>/mcp`.
- [ ] (Optional) Skill playbook created and symlinked into the workspace; routing line added to SOUL.md.
- [ ] For read-only deployment: confirm new tools preserve the read-only boundary (no user-data writes, no shell).
- [ ] Add one or two acceptance questions in `eval/run_eval.py` (expected `<name>` tool calls + correct answers).

## References
- Own-container HTTP example (default): `mcps/badminton-db/` (`server.py`, `Dockerfile`, `scripts/test_db_mcp.py`), `badminton-db` service in `docker-compose.yml`
- Local stdio example: `mcps/util/server.py`
- Remote example and deployment: `REELS_MCP_HANDOFF.md`, `reels_mcp_usage.md`
- Endpoint acceptance checks: `MCP_TEST.md` (`python -m mcp_test`)
- Overall architecture and nanobot configuration facts: `DESIGN.md`, `CLAUDE.md`
