# For LLM agents: build a remote MCP server from a user's code

> **You are an LLM coding agent.** Your user has their *own* code or service and wants to expose it as a
> **remote MCP server** that other agents/clients can call over the network. This page is your playbook:
> the steps to follow, the conventions you must obey, and — most importantly — **what to confirm with your
> user before you write any code**. Read it fully first.

## Where to read (load these as you need them)

| Resource | When to read it |
|---|---|
| **This page** (`/for-llm-agents/`) | The playbook — start here. |
| **[Guide](index.md)** (`/`) | The full human reference: concepts, run-locally, deploy (Cloudflare *or* Bearer token), connect-a-client, troubleshooting. Pull specifics from here. |
| **[Example server](example.md)** + downloadable `example-mcp-server.zip` | A **complete, runnable reference implementation** — copy it and adapt. Tools: `add`, `echo`, and an async job `start_render → get_render_status → get_render_result`, plus `GET /healthz` and `GET /files/{id}`. |
| **`/llms.txt`** | Machine-readable index of this site (links + one-line summaries). |

The whole stack is **Python + FastMCP** (the `mcp` SDK), served over **Streamable HTTP** at `/mcp`.

---

## Step 0 — Ask your user first (do NOT skip)

You cannot build the right server without these answers. If any is unknown, **ask the user** — do not guess.
Ask in plain language, one decision at a time, and confirm before scaffolding.

1. **Which functions → tools.** What in their code should become callable tools? For each: a clear name
   (`^[A-Za-z0-9_-]+$`, prefer verbs like `list_*`/`get_*`/`create_*`), its inputs, its output, and what
   must stay *private* (never expose secrets, file-system access, or destructive operations by accident).
2. **Sync vs async.** Is any operation **long-running** (more than a few seconds — rendering, training,
   scraping, large queries)? If so it needs the **async job contract** (`start → status → result` with
   progress), not a plain blocking tool. Confirm which tools are which.
3. **Auth model.** How will it be protected? **Cloudflare Access service token** (edge auth, no app code) or
   an **app-level Bearer token** (FastMCP's built-in token verification)? Who issues and holds the secret?
4. **Hosting & domain.** Where does it run — **systemd** service or **Docker**? What **public hostname /
   Cloudflare zone** (or self-hosted TLS)? Do any tools return **file artifacts** the client must download?

Also surface, if not obvious: the code's **language/runtime** (this guide assumes Python; a non-Python
service is wrapped by calling it as a subprocess or over its existing API), and what **data, credentials, or
environment** the tools need at run time.

> If the user just says "make my code an MCP server," that is **not** enough — walk them through the four
> decisions above and get explicit answers before continuing.

---

## Step 1 — Scaffold from the example

Start from `example-mcp-server/` (download the zip or read [Example server](example.md)); do **not** invent a
new layout. Keep its shape: a `FastMCP("<name>", host=..., port=...)`, tools as decorated functions, a
`GET /healthz` custom route, and `mcp.run(transport="streamable-http")` in `main()`.

## Step 2 — Wrap each chosen function as a tool

Import the user's code and call it inside a thin `@mcp.tool()` wrapper. Do not re-implement their logic —
wrap it, validate inputs, and shape the output as JSON.

```python
from typing import Annotated
from mcp.server.fastmcp import FastMCP
from pydantic import Field
import user_module                       # the user's existing code

mcp = FastMCP("their-service", host="127.0.0.1", port=8900)

@mcp.tool()
def search(
    query: Annotated[str, Field(description="Free-text search query (1–200 chars).")],
    limit: Annotated[int, Field(description="Max results to return, 1–50.")] = 10,
) -> dict:
    """Search the catalog and return {results, count}. Use for keyword lookups."""
    if not query.strip():
        return {"error": "query must be non-empty"}        # return errors, don't raise
    hits = user_module.search(query, limit)                 # call the user's code
    return {"results": hits, "count": len(hits)}
```

## Step 3 — Add the async job contract *only if* something is long-running

If an operation can't finish in one call, expose three tools — `start_x` (returns `{job_id, state}`
immediately), `get_x_status` (returns `{state, stage, total_stages, message}` for a progress bar), and
`get_x_result` (returns the output, or a **downloadable URL** for files). Run the work on a background
thread/task; never block the tool call. Copy this pattern verbatim from the example server's
`start_render`/`get_render_status`/`get_render_result`.

## Step 4 — Test locally before deploying

```bash
python server.py                                  # serves http://127.0.0.1:8900/mcp
curl -s http://127.0.0.1:8900/healthz             # -> {"ok": true}
python smoke_test.py http://127.0.0.1:8900/mcp    # lists tools, calls them (adapt from the example)
```

## Step 5 — Deploy & hand off

Follow the Guide's **Deploy remotely** section for the auth/hosting choice from Step 0 (Cloudflare Tunnel +
Access, or your own reverse proxy + Bearer token). Then deliver the consumer **one registration JSON block**
(`mcpServers` entry with the `/mcp` URL, auth headers as `${VAR}` placeholders, and `enabledTools`) — the
exact shape is in the Guide's *Hand-off* section.

---

## Conventions you MUST follow

These are non-negotiable; they come from the Guide and the example server.

- **One tool = one decorated function.** Return JSON-serializable data (`dict`/`list`). On failure, **return
  `{"error": "..."}` — never raise**; a raised exception is opaque to the calling agent.
- **Describe every parameter.** Annotate each argument with `Annotated[T, Field(description="...")]`. The
  docstring becomes the *tool-level* description only — FastMCP does **not** parse a docstring `Args:` block,
  so parameter docs must come from `Field`. Keep the default outside the `Annotated`.
- **Write the docstring for the calling agent.** One precise sentence on *what it does and when to use it* —
  that text is how a downstream LLM decides to call your tool.
- **Validate inputs and stay safe by default.** Whitelist/validate arguments; never expose destructive,
  credential-bearing, or filesystem-walking behavior unless the user explicitly asked for it.
- **Long jobs return immediately.** Use the `start → status → result` contract above; report
  `stage`/`total_stages`/`message` so clients can show progress. Status/result tools must return instantly
  (clients poll).
- **Deliver files as URLs, not paths.** A file-producing tool returns a downloadable
  `PUBLIC_BASE_URL/files/{id}` URL served by a `@mcp.custom_route`, **never** a local filesystem path.
- **Always add `GET /healthz`** (returns `{"ok": true}`, touches no data) — deploys and containers health-gate
  on it.
- **Bind `127.0.0.1`** on a host (only the tunnel/proxy reaches it) or `0.0.0.0` inside a container; **never
  expose an unauthenticated server** to the public internet.
- **No secrets in code or JSON.** Read tokens from the environment; use `${VAR}` placeholders in any
  hand-off. The secret travels over a secure channel, separately.

## When to stop and ask again

Mid-build, return to the user (don't assume) if you discover: a tool would expose something sensitive; an
operation is slower than expected and should become async; the auth/hosting choice doesn't fit their
environment; or the requirements are ambiguous about inputs/outputs. **Asking a good question beats shipping
the wrong server.**

## Definition of done

- [ ] Every agreed function is a tool with a clear docstring and `Field`-described parameters.
- [ ] Errors return `{"error": ...}`; long jobs use `start/status/result` with progress.
- [ ] `GET /healthz` works; file outputs are URLs, not paths.
- [ ] Local smoke test passes (`list_tools` + a real call).
- [ ] Deployed behind the chosen auth (Cloudflare Access **or** Bearer token); no secret is committed.
- [ ] Consumer received the registration JSON with `${VAR}` placeholders and the token over a secure channel.
