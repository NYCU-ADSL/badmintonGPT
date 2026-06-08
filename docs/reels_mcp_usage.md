# badminton-reels — how to connect (usage)

`badminton-reels` is a **remote** MCP server (deployed at `reels-mcp.nycu-adsl.cc`, behind Cloudflare
Access) that generates highlight videos. This repo does **not** implement or containerize it — it only
points nanobot at the remote URL. This file is the connection cheat-sheet; for the deeper material:

- **Async-job contract** (`generate_reel` → `get_reel_status` → `get_reel_result`, the `{job_id, state}`
  polling shape): [`DESIGN.md`](./DESIGN.md) §3.4.
- **How the agent orchestrates the wait loop** (in-turn `util.sleep` polling, never cron):
  `skills/badminton-reels/SKILL.md` (domain knowledge) + `skills/long-mcp-job/SKILL.md` (the generic
  recipe).
- **How the server was built / its refactor spec**: [`REELS_MCP_HANDOFF.md`](./REELS_MCP_HANDOFF.md).

## nanobot config (`~/.nanobot/config.json` — the committed template is `nanobot/config.json`)

```json
{
  "mcpServers": {
    "badminton-reels": {
      "type": "streamableHttp",
      "url": "https://reels-mcp.nycu-adsl.cc/mcp",
      "headers": {
        "CF-Access-Client-Id": "${REELS_CF_CLIENT_ID}",
        "CF-Access-Client-Secret": "${REELS_CF_CLIENT_SECRET}"
      }
    }
  }
}
```

`REELS_CF_CLIENT_ID` / `REELS_CF_CLIENT_SECRET` live in `.env` (each remote MCP uses its own
`${<NAME>_CF_CLIENT_ID/SECRET}` pair — see `.env.example`). nanobot resolves `${VAR}` at startup, so
they must be exported before `nanobot gateway`.
