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
- **Narration language**: `generate_reel` takes `language` (`zh-TW` | `en`, narration script + TTS voice +
  subtitles). The current English-only system instruction explicitly requires `language="en"`.
  If omitted, the nanobot fork fills it from the WebUI language picker (`zh-TW`/`zh-CN` → `zh-TW`,
  other UI languages → `en`). An explicit value wins. Confirm the language from the tool result,
  not the UI locale alone.

## Deploying language support

Repo changes do not update either running service automatically. The reels MCP must expose the
`language` property in its live `generate_reel` schema, and `get_reel_result` must echo it. An old
reels image can keep using Chinese scripts, opening lines and voices despite an English chat reply.

Rebuild and recreate `reels` from `../badminton-reels`, preserving its output/cache volumes. Refresh
BadmintonGPT's MCP connections afterward so its cached tool definitions include the new field.
When updating SOUL, rebuild/recreate the gateway as well. Check for active jobs and conversations
before restarting services. Existing video files retain their original narration/subtitles;
validate the change with a new job and inspect its stored spec, complete script and video.

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
