# badminton-reels → MCP refactoring handoff

> **For the next Claude agent**: this document describes adapting `../badminton-reels` (relative to `badmintonGPT`; absolute path `/mnt/ssd1/howchien/badminton-reels`) into a **remote MCP server** accepting external network connections, accessed by badmintonGPT's nanobot agent through a **remote URL**. Three target tools: `generate_reel` (coarse-grained, asynchronous, returns `job_id`, **adjustable reel style and content**), `get_reel_status`, and `get_reel_result`.
>
> **Two key differences for remote access** (apply throughout):
> 1. **Use Streamable HTTP transport** (not stdio), binding the server to an externally reachable host:port.
> 2. **Return downloadable video URLs**, not local file paths—remote clients cannot access local paths. Add a static-file route serving .mp4 downloads.
>
> Understand the current implementation before editing. All paths, functions, and behavior descriptions have been checked against the code. **Preserve the existing CLI** (`uv run python -m badminton ...` must continue to work).

---

## 0. Current implementation at a glance (code verified)

| File | Role | Key points |
|------|------|--------|
| `src/badminton/__main__.py` | CLI entry point | `main()` parses `match_name` + `--style` (default humorous) + `--list-matches`, then calls `Pipeline().run(match_name, style)` |
| `src/badminton/pipeline.py` | End-to-end pipeline | `Pipeline.run(match_name, style)` has five stages: load→analyze→G-E-RG→TTS→compose; **reports progress using print** and returns an output `Path`. Constant `MAX_VIDEO_DURATION=180.0` |
| `src/badminton/match_analyzer.py` | Highlight selection | `MatchAnalyzer.analyze(match)` **automatically** scores and selects **≤8** highlights, assigning five narrative roles (hook/buildup/turning_point/climax/ending). Currently **accepts no filter parameters** |
| `src/badminton/agents/writer.py` | Scriptwriting | `generate_script(analysis, style, ...)`; style is merely inserted into user_msg as `## Style: {style}`; the system prompt always reads `prompts/writer.md` (humorous tone) |
| `src/badminton/agents/graph.py` | G-E-RG loop | `NarrationState` TypedDict carries `style`; `create_narration_graph()` returns a LangGraph |
| `src/badminton/config.py` | Configuration | `Config` reads env at import time (OpenAI key/model, Fish, HF, output_dir, etc.). `get_config()` uses `@lru_cache` |
| `src/badminton/models.py` | Pydantic models | `MatchData / MatchAnalysis / RallyHighlight / NarrativeScript / ...` |

**Actually available filter dimensions** (from shot-by-shot data; verified):
- `type` (shot type): 放小球、挑球、擋小球、殺球、點扣、發短球、推球、切球、過度切球、勾球、長球、發長球、平球、撲球、後場抽平球、防守回抽、防守回挑、未知球種
- `win_reason`/`lose_reason`: 出界、(對手)落地致勝、(對手)未過網、(對手)掛網、落點判斷失誤
- `player`/`getpoint_player`：`A`/`B`
- Rally ID `set_scoreA_scoreB` (e.g. `1_05_04`), corresponding to `rally_video/*.mp4` (**only some rallies actually have video files**)

---

## Refactoring tasks (in order)

### Task 1 — Define ReelSpec / ReelResult (new models)
Add two Pydantic models in `src/badminton/models.py` as the single style/content input and structured output.

```python
class ReelSpec(BaseModel):
    match_name: str
    # Style
    style: str = "humorous"                  # Preset name or free-form string (see task 3)
    duration_target_sec: int = 90            # Target duration, clamped to [30, 180]
    # Content controls (all optional; None = unrestricted)
    focus_player: str | None = None          # "A"/"B" or a substring of a player name; favor rallies they score in or control
    shot_types: list[str] | None = None      # Prefer rallies containing these shot types, e.g. ["殺球","撲球"]
    sets: list[int] | None = None            # Include only specified games, e.g. [3]
    rally_ids: list[str] | None = None       # Explicit rallies (bypass automatic selection when provided)
    max_highlights: int = 8                  # 1..12
    narrative_emphasis: str | None = None    # E.g. "comeback", "long rallies", "attacking tactics"; injected into scriptwriting
    only_with_video: bool = True             # Select only rallies with actual files in rally_video/
    voice_id: str | None = None              # Override Fish voice

class ReelResult(BaseModel):
    video_path: str                          # Server-local path (internal only, not returned to remote clients)
    video_url: str = ""                      # Public downloadable URL (for remote clients; see tasks 7/8)
    match_name: str
    selected_rally_ids: list[str]
    duration_sec: float
    quality_score: float
    style: str
    script_summary: str                      # Concatenated segment subtitles or first N characters
```

Acceptance: models import successfully; `duration_target_sec`/`max_highlights` are range-clamped using `model_validator`.

---

### Task 2 — Add content filtering to MatchAnalyzer
Make `MatchAnalyzer.analyze` accept optional `spec: ReelSpec | None`. Add filtering/weighting to the current scoring flow **without changing default behavior** (`spec=None` must behave exactly as before).

Changes needed in `match_analyzer.py`:
1. `analyze(self, match, spec=None)`：
   - If `spec.rally_ids` is provided → select segments directly from that list (still run `_describe_key_moments` and assign the five narrative roles), bypassing automatic top-N.
   - Otherwise, **filter** after sorting `scored_rallies` and before `_select_highlights`:
     - `spec.sets` → retain only `seg.set_num in sets`
     - `spec.only_with_video` → retain only existing `seg.video_path` files (ensure the analyzer has video-existence information; see below)
     - `spec.shot_types` → **weight** rallies containing these shot types (add a bonus in `_score_excitement` or multiply weights before sorting), rather than hard filtering, to avoid too few selections.
     - `spec.focus_player` → weight rallies where that player scores or controls play.
   - `spec.max_highlights` → replace the hard-coded `8` in `_select_highlights` (parameterize both `>= 8` and `< 8`).
2. `only_with_video` requires knowing which rallies have video:
   - Simple approach: scan `*.mp4` under `match.rally_video_dir` in the analyzer, or record existence in `RallySegment.video_path` during `DataLoader.load_metadata`. Choose one and document it.

Acceptance: `spec.sets=[3]` selects only game 3 rallies; `spec.rally_ids=[...]` follows the list exactly; `spec=None` matches pre-refactoring output (compare highlight sets for the same match).

---

### Task 3 — Extensible style presets + free-form strings
Currently style is only inserted into user_msg; the system prompt always uses humor. Change this:

1. Add `prompts/styles/`, one snippet file per preset, for example:
   - `humorous.md` (move the "style requirements" section from the existing `prompts/writer.md`)
   - `professional.md` (professional commentary, precise terminology, objective tone)
   - `dramatic.md` (dramatic tension, suspense)
   - `educational.md` (for coaches/players, explaining tactical and technical points)
   - `concise.md` (brief, fast-paced)
2. Split `prompts/writer.md` into a **shared skeleton** (output format, Fish emotion tags, five-part structure, length/pacing limits) and an injected preset style section.
3. Modify `generate_script` in `agents/writer.py`:
   - Add `emphasis: str | None = None` (from `ReelSpec.narrative_emphasis`).
   - Load the system prompt as the shared skeleton + the matching style preset;
     - if `style` is not a known preset, treat it as **free-form style instructions** and inject it directly as the style section for flexibility.
   - Include `duration_target_sec` and `emphasis` in user_msg so the model follows the target duration and narrative focus.
4. `graph.py`: add `emphasis` and `duration_target_sec` to `NarrationState` and pass them through `writer_node` → `generate_script`.

Acceptance: `style="professional"` and `style="humorous"` produce noticeably different tones; unknown style strings are accepted as free-form instructions.

---

### Task 4 — Callable pipeline + progress callback
Make the pipeline callable programmatically with stage reporting for asynchronous jobs.

Modify `pipeline.py`:
1. Add `Pipeline.generate(self, spec: ReelSpec, on_progress=None) -> ReelResult`:
   - Retain the five existing stages, but:
     - `analyzer.analyze(match, spec)`；
     - include `spec.style` / `spec.narrative_emphasis` / `spec.duration_target_sec` in the graph's initial state;
     - use clamped `spec.duration_target_sec` instead of hard-coded `MAX_VIDEO_DURATION` when deciding whether to speed up (retain 180 as the hard ceiling);
     - pass `voice_id` to TTS when provided.
   - Replace each `print(...)` with `self._emit(on_progress, stage, msg)`, using `on_progress(stage:int, total:int, msg:str)`; printing for the CLI can remain.
   - Return `ReelResult` (collect selected_rally_ids, final duration, quality_score, script_summary, output path).
2. Retain `run(match_name, style)` as a thin wrapper → `self.generate(ReelSpec(match_name=match_name, style=style)).video_path`, returning `Path`, so CLI behavior stays unchanged.

Acceptance: `uv run python -m badminton "<match>"` behaves unchanged; `Pipeline().generate(ReelSpec(...))` returns `ReelResult` programmatically.

---

### Task 5 — Injectable configuration (provider/keys/output overrides)
Currently `Config` captures env at import time, and `get_config()` uses `@lru_cache`. To allow MCP callers to override it (matching badmintonGPT's configurable-provider requirement):
1. Allow `Config` overrides (e.g. `get_config(overrides: dict | None = None)` or `set_config_overrides()`). At minimum, make `output_dir`, `fish_voice_id`, `openai_model`, and `openai_api_key` overridable.
2. Replacing the OpenAI provider is not required now, but centralize writer/critic/audience client acquisition in `get_llm_client()` for future provider changes. **If time is limited, at least support output_dir and voice_id overrides** (jobs need separate output directories).

Acceptance: callers can specify `output_dir` without changing `.env`, and output goes to that directory.

---

### Task 6 — Asynchronous job management
Add `src/badminton/jobs.py` for job state queryable across calls. Recommended: background threads + persisted JSON state files, avoiding MCP tool calls that block for minutes.

```python
# State file: {output_dir}/jobs/{job_id}.json
class JobStatus(BaseModel):
    job_id: str
    state: str            # "queued" | "running" | "succeeded" | "failed"
    stage: int = 0        # 0..5
    total_stages: int = 5
    message: str = ""
    result: ReelResult | None = None
    error: str | None = None
    spec: ReelSpec
```

`JobStore` requirements:
- `create(spec) -> job_id`: generate an ID (**avoid uuid4/time-randomness dependencies**; use `match_name + incrementing sequence + spec hash`), write queued state, and start a background thread.
- The background thread runs `Pipeline().generate(spec, on_progress=callback)`, updating state at each stage (`running`, stage/message); success writes `succeeded` + `result`, exceptions write `failed` + `error` (traceback summary).
- `get(job_id) -> JobStatus`: read the state file; return an explicit error if not found.

Acceptance: immediately after job creation, `get` returns `queued/running`; after a few minutes, it becomes `succeeded` and `result.video_path` exists.

---

### Task 7 — Remote MCP server (Streamable HTTP + video download route)
Add `src/badminton/mcp_server.py` using the official **Python MCP SDK** (`FastMCP` from `mcp`). Add the `mcp` dependency and an entry point in `pyproject.toml` (e.g. `badminton-mcp = "badminton.mcp_server:main"`).

**Transport**: **Streamable HTTP**, not stdio. **Public access uses Cloudflare Tunnel + Access (selected approach; appendix A)**, so bind only to `127.0.0.1`; cloudflared exposes it through an outbound connection. **Do not** bind to `0.0.0.0`, open ports manually, or manage TLS yourself.

```python
mcp = FastMCP(
    "badminton-reels",
    host=os.getenv("MCP_HOST", "127.0.0.1"),  # Only cloudflared connects; not directly public
    port=int(os.getenv("MCP_PORT", "8900")),
)
# Public URL = Cloudflare Tunnel hostname (appendix A), used to construct video_url
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://reels-mcp.example.com")

def main():
    mcp.run(transport="streamable-http")     # MCP endpoint defaults to /mcp
```

**Video download route** (remote clients cannot use local paths; HTTP file access is required): FastMCP is based on Starlette. Add a file route with `@mcp.custom_route` to serve `{output_dir}/.../*.mp4`:

```python
from starlette.responses import FileResponse, JSONResponse
from starlette.requests import Request

@mcp.custom_route("/files/{job_id}.mp4", methods=["GET"])
async def serve_reel(request: Request):
    job_id = request.path_params["job_id"]
    s = STORE.get(job_id)
    if not s or s.state != "succeeded" or not s.result:
        return JSONResponse({"error": "not ready"}, status_code=404)
    return FileResponse(s.result.video_path, media_type="video/mp4",
                        filename=f"{job_id}.mp4")

@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request):
    return JSONResponse({"ok": True})
```

Construct `video_url` from `PUBLIC_BASE_URL` + `/files/{job_id}.mp4` and write it to `ReelResult.video_url` when the job succeeds.

Tools (names, inputs, and outputs are fixed below; the agent integrates against these):

```python
@mcp.tool()
def generate_reel(
    match_name: str,
    style: str = "humorous",
    duration_target_sec: int = 90,
    focus_player: str | None = None,
    shot_types: list[str] | None = None,
    sets: list[int] | None = None,
    rally_ids: list[str] | None = None,
    max_highlights: int = 8,
    narrative_emphasis: str | None = None,
    voice_id: str | None = None,
) -> dict:
    """Create an asynchronous highlight-generation job. Return job_id and initial state."""
    spec = ReelSpec(...parameters above...)
    job_id = STORE.create(spec)
    return {"job_id": job_id, "state": "queued"}

@mcp.tool()
def get_reel_status(job_id: str) -> dict:
    """Query job status: state / stage / message / error."""
    s = STORE.get(job_id)
    return {"job_id": s.job_id, "state": s.state, "stage": s.stage,
            "total_stages": s.total_stages, "message": s.message, "error": s.error}

@mcp.tool()
def get_reel_result(job_id: str) -> dict:
    """Get completed results; otherwise return state and indicate that results are not ready."""
    s = STORE.get(job_id)
    if s.state != "succeeded":
        return {"job_id": s.job_id, "state": s.state, "ready": False,
                "message": s.message or s.error or "Not yet complete"}
    r = s.result
    return {"job_id": s.job_id, "state": s.state, "ready": True,
            "video_url": r.video_url, "selected_rally_ids": r.selected_rally_ids,
            "duration_sec": r.duration_sec, "quality_score": r.quality_score,
            "style": r.style, "script_summary": r.script_summary}
            # Return downloadable video_url, not local video_path
```

Also consider a read-only tool or resource: `list_matches() -> list[str]` (wrap `DataLoader.list_matches()`) so the agent can first inspect available matches.

Acceptance:
- Server listens on `127.0.0.1:8900`; local `GET /healthz` returns 200.
- Through cloudflared, an **external** MCP client with an Access service token (appendix A) can connect to `https://reels-mcp.example.com/mcp` and list three tools.
- `generate_reel(match_name=...)` returns `job_id`.
- Polling `get_reel_status` transitions from running to succeeded.
- `get_reel_result` returns `video_url`, which can be downloaded as .mp4 with curl and an Access service token.

---

### Task 8 — Access control and abuse protection
Cloudflare Access handles public access (appendix A), so the app only needs defense in depth and abuse protection, not its own public authentication/TLS implementation.

1. **Cloudflare Access owns authentication** (service token, appendix A). Access blocks requests without a token; the origin receives only accepted traffic.
2. **Optional origin defense in depth**: validate the Cloudflare-injected `Cf-Access-Jwt-Assertion` in Starlette middleware (verify JWT with the team's public keys at `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`), or retain an app-level `MCP_AUTH_TOKEN` as a second layer (allow `/healthz`). Initially, relying on Access alone is acceptable; mark this layer TODO.
3. **Abuse protection**: limit concurrent jobs with `MAX_CONCURRENT_JOBS`, returning an explicit error when exceeded, to prevent flooding from exhausting the machine.
4. **Video download authorization**: `/files/{job_id}.mp4` and `/mcp` share the same Cloudflare hostname and **Access policy**, so downloads require a service token by default. ⚠️ This also means **end-user browsers cannot play videos directly**; see appendix A, "Video playback in browsers."

New environment variables (document in `.env.example` and README):
`MCP_HOST(=127.0.0.1), MCP_PORT, PUBLIC_BASE_URL(=tunnel domain), MAX_CONCURRENT_JOBS`, plus optional `MCP_AUTH_TOKEN`.
(Cloudflare tunnel credentials and Access service tokens belong to Cloudflare configuration, not app env; see appendix A.)

Acceptance: Access blocks external requests without a service token; valid tokens allow `/mcp` access and `video_url` downloads.

---

## Connecting from badmintonGPT (nanobot) to this remote MCP
(Reference for badmintonGPT configuration, not a badminton-reels change.)

Register as **remote / streamable-http** in nanobot's `~/.nanobot/config.json`, pointing the URL to the Cloudflare Tunnel domain and including **Cloudflare Access service token** headers:

```jsonc
{
  "mcpServers": {
    "badminton-reels": {
      "type": "streamableHttp",               // streamable-http remote
      "url": "https://reels-mcp.example.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "${REELS_CF_CLIENT_ID}",
        "CF-Access-Client-Secret": "${REELS_CF_CLIENT_SECRET}"
      }
    }
  }
}
```

(Use actual key names from nanobot documentation; the key idea is a remote URL + CF-Access service-token headers.) After connection, the agent can call `generate_reel / get_reel_status / get_reel_result`; see appendix A for playback after obtaining `video_url`.

---

## Interface contract (for Agent / nanobot; keep stable)

Connection: **remote Streamable HTTP over Cloudflare Tunnel**, endpoint `<PUBLIC_BASE_URL>/mcp`, requiring a Cloudflare Access service token (`CF-Access-Client-Id` / `CF-Access-Client-Secret`).

| Tool | Required input | Optional input | Key output |
|------|------------|------------|---------|
| `generate_reel` | `match_name` | `style, duration_target_sec, focus_player, shot_types, sets, rally_ids, max_highlights, narrative_emphasis, voice_id` | `{job_id, state}` |
| `get_reel_status` | `job_id` | — | `{state, stage, total_stages, message, error}` |
| `get_reel_result` | `job_id` | — | `{ready, video_url, selected_rally_ids, duration_sec, quality_score, style, script_summary}` |

Fixed `state` values: `queued / running / succeeded / failed`. Download videos through `video_url` (`<PUBLIC_BASE_URL>/files/{job_id}.mp4`); do not return local paths.

---

## Restrictions and notes
- **Do not** break the existing CLI or output quality of `prompts/writer.md` (when splitting prompts, move the full humorous style into `styles/humorous.md`).
- **Do not** rely on `random`/`Date.now` for job IDs or any logic (keep it reproducible).
- Video generation requires `ffmpeg` (libass) and Fish/OpenAI keys. If keys are missing at MCP server startup, report them clearly in `get_reel_status` as `failed.error` instead of crashing the server.
- `only_with_video=True` matters: the dataset contains many shot annotations, but only some rallies have files in `rally_video/`; selecting missing videos causes a black-screen fallback.
- **Remote: never return local `video_path` to tool callers**; always return `video_url`. Local paths are only for server internals and the `/files` route.
- **Do not bind publicly to `0.0.0.0` or open ports yourself**: bind to `127.0.0.1`, expose only through Cloudflare Tunnel (appendix A), and delegate authentication to Cloudflare Access service tokens.
- After refactoring, update `../badminton-reels/README.md` and `CLAUDE.md` with **remote MCP startup instructions (including cloudflared)**, env variables (`MCP_HOST/MCP_PORT/PUBLIC_BASE_URL/MAX_CONCURRENT_JOBS`, optional `MCP_AUTH_TOKEN`), ReelSpec parameters, and style presets.

## Definition of done (DoD)
1. `uv run python -m badminton "<match>"` behaves unchanged.
2. `uv run badminton-mcp` (or equivalent) starts **Streamable HTTP** on `127.0.0.1:MCP_PORT`; local `GET /healthz` returns 200.
3. cloudflared exposes `https://reels-mcp.<your-domain>`; an **external** remote MCP client with an Access service token can list three tools at `/mcp`.
4. One end-to-end run: `generate_reel` → poll `get_reel_status` → obtain `video_url` from `get_reel_result`, then download .mp4 with curl using a service token.
5. Cloudflare Access blocks external requests with missing/invalid service tokens.
6. At least three style presets work with distinct tones; any of `shot_types`/`sets`/`rally_ids`/`focus_player` can actually change selected rallies.
7. README/CLAUDE.md are updated together.
8. Deployment: complete Cloudflare Tunnel + Access per appendix A; an external client with a service token can complete the full flow.

---

## Appendix A — Selected deployment: Cloudflare Tunnel + Access Service Token

**Why this approach**: the reels pipeline uses Python + ffmpeg and takes several minutes; data, videos, and environment are local. Cloudflare Tunnel securely exposes the **local** MCP without opening ports, requiring a public IP, or managing TLS. Access **service tokens** authenticate server-to-server traffic (nanobot ↔ MCP). Workers are unsuitable for this heavy workload; Containers require repackaging and egress charges, so neither is selected.

**Prerequisites**: a Cloudflare-managed domain (zone) and enabled Cloudflare Zero Trust (Access).

### A.1 Install and create a Tunnel (on the MCP machine)
```bash
# 1) Install cloudflared for your platform, log in, and create a tunnel
cloudflared tunnel login
cloudflared tunnel create reels-mcp        # Generate tunnel ID and credentials JSON

# 2) Bind a public hostname to this tunnel
cloudflared tunnel route dns reels-mcp reels-mcp.example.com
```

`~/.cloudflared/config.yml` (forward public traffic to the local MCP at 127.0.0.1:8900):
```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: reels-mcp.example.com
    service: http://127.0.0.1:8900     # FastMCP listener; both /mcp and /files use this
  - service: http_status:404
```

Run persistently as a service:
```bash
cloudflared service install      # Or cloudflared tunnel run reels-mcp
```
Now `https://reels-mcp.example.com/mcp`, `/files/{job_id}.mp4`, and `/healthz` all route through the Cloudflare edge to the local server.

### A.2 Protect with an Access Service Token (server-to-server)
1. Zero Trust dashboard → **Access → Applications → Add → Self-hosted**; set the application domain to `reels-mcp.example.com` (all paths).
2. **Access → Service Auth → Create Service Token**; obtain **Client ID** and **Client Secret** (the secret is displayed once; store it securely).
3. Add an application **policy**: Action = **Service Auth**, Include = the service token just created.
   - Only requests with valid `CF-Access-Client-Id` / `CF-Access-Client-Secret` headers reach the origin; others are blocked at the edge.
4. (Recommended) Enable **Protect with Access** in Tunnel settings so cloudflared also validates the token.

### A.3 nanobot (badmintonGPT) side
Put the service token in nanobot environment variables and include CF-Access headers in `~/.nanobot/config.json` (as in the connection section above):
```
CF_ACCESS_CLIENT_ID=<Client ID>
CF_ACCESS_CLIENT_SECRET=<Client Secret>
```
Set server-side `PUBLIC_BASE_URL` to `https://reels-mcp.example.com` so `video_url` matches the tunnel domain.

### A.4 Video playback in browsers (important)
`/files/*.mp4` and `/mcp` share a hostname and Access policy → **ordinary user browsers lack the service token and cannot play directly**. Choose one:
- **Recommended: proxy through the nanobot backend**. After the agent obtains `video_url`, the backend downloads it with the service token and serves playback through the web UI's domain. End users never interact with tunnel/Access; simplest approach.
- **Signed URL + bypass**: reels generates short-lived signed URLs for `/files` (query-string token), with an Access Bypass policy on `/files/*` and app-signature validation; `/mcp` retains service-token authentication.
- **Separate public subdomain**: publish finished videos on a download domain without Access (or public/signed R2 links). Easiest, but videos become semi-public; consider copyright.

> This project defaults to **the first option (nanobot backend proxy)**: a clear security boundary, no Access-policy changes, and videos always remain token-protected.

### A.5 Quick local test (without Cloudflare)
```bash
# After starting MCP on 127.0.0.1:8900:
curl -s http://127.0.0.1:8900/healthz          # {"ok": true}
# External test through tunnel + service token:
curl -s https://reels-mcp.example.com/healthz \
  -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET"
```
