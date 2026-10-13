# Deploying BadmintonGPT (Docker Compose + Cloudflare Tunnel)

This is the reproducible way to host the BadmintonGPT agent — clone the repo, set a few
secrets, and `docker compose up`. It stands up three services (each MCP is its own container;
reels stays remote):

| service | what | exposure |
|---|---|---|
| `gateway` | nanobot agent + **patched** WebUI (built from `vendor/nanobot/`) + the embedded `util` stdio MCP (sleep) | internal `:8765` only |
| `badminton-db` | the `badminton-db` MCP, served over **streamable-HTTP** at `/mcp` on `:8801` (reads `./data/badminton.db` read-only); also `GET /healthz` | internal `:8801` only |
| `cloudflared` | Cloudflare tunnel `badmintongpt.<zone>` → `http://gateway:8765` | outbound only |

The gateway reaches `badminton-db` at `http://badminton-db:8801/mcp` over the compose network
(no auth — internal only, never host-published, never tunneled) and reaches the **remote**
`badminton-reels` MCP over HTTPS (a separate deployment, `REELS_CF_*` headers). Nothing listens
on a public port; the only way in is the Cloudflare tunnel, gated by Cloudflare Access.

```
browser → badmintongpt.<zone>  (Cloudflare edge + Access)
        → cloudflared container → gateway:8765 (nanobot WebUI + WS)
                                   ├─ stdio MCP  util             (sleep, for job polling; in-process)
                                   ├─ HTTP       badminton-db     → badminton-db:8801/mcp (compose net, no auth)
                                   │                                 └─ /app/data/badminton.db (ro)
                                   └─ HTTPS      badminton-reels  (remote, REELS_CF_* headers)
```

---

## Prerequisites

- Docker + Docker Compose v2 on the host.
- A **Cloudflare account with a zone** you control (for `badmintongpt.<your-zone>`).
- An **OpenAI API key** with access to the configured model (`gpt-5.1`, see `nanobot/config.json`).
- To build the DB: only a **HuggingFace token**. The DB build is self-contained — `ingest.py`
  ships its own parsing (`mcps/badminton-db/ingest_lib/`) and no longer imports the sibling
  `badminton-reels` repo, so there is nothing to bind-mount or pin.

---

## 1. One-time Cloudflare setup (cannot come from a clone)

These are account-bound and done once in the Cloudflare dashboard.

1. **Create a remote-managed tunnel.** Zero Trust → **Networks → Tunnels** → *Create a tunnel* →
   **Cloudflared** connector → name it (e.g. `badmintongpt`). Copy the **tunnel token** → this is
   `TUNNEL_TOKEN` in `.env`. (Remote-managed = ingress lives in the dashboard, not in a file.)
2. **Add a public hostname** on that tunnel: hostname `badmintongpt.<your-zone>`, service
   `http://gateway:8765`. The DNS `CNAME` is created automatically. (`gateway` is the compose
   service name — cloudflared resolves it over the compose network.)
3. **Protect it with Cloudflare Access** (mandatory for a public zone — the gateway itself does
   **no** auth). Zero Trust → **Access → Applications** → *Add* → Self-hosted → domain
   `badmintongpt.<your-zone>` → add a policy (your email / IdP group, or a service token). Without
   this, anyone who learns the hostname reaches the WebUI.
   With accounts on (the default, see [Accounts & quotas](#accounts--quotas)) Access is the **login**,
   not the whitelist: let in everyone who should be able to sign up (e.g. *Include → Everyone* with
   the One-time PIN or Google login method) and put the unlimited users in
   `NANOBOT_ACCOUNTS_WHITELIST` instead. The policy must identify a **person** (an e-mail) — a
   service-token-only policy has no e-mail, so the gateway answers `401 not signed in`.
4. **Welcome page (optional, same hostname).** Signed-out visitors of `/` see a public bilingual
   welcome page (`vendor/nanobot/webui/public/welcome.html`, served by the gateway like any WebUI
   static file); its sign-in button goes to `/?login`, where Access takes over. Two dashboard pieces:
   - **Access bypass for that one path**: Zero Trust → **Access → Applications** → *Add* →
     Self-hosted → name `BadmintonGPT welcome`, domain `badmintongpt.<your-zone>`, **path
     `welcome.html`** → policy action **Bypass**, *Include → Everyone*. The most specific path wins,
     so every other path stays behind the main application. The page must stay self-contained
     (inline CSS/SVG/JS) — anything else it referenced would be blocked for anonymous visitors.
   - **Redirect Rule** (zone `<your-zone>` → **Rules → Redirect Rules** → *Create rule*), custom
     filter expression:
     ```
     (http.host eq "badmintongpt.<your-zone>" and http.request.uri.path eq "/"
      and http.request.uri.query eq "" and not http.cookie contains "CF_Authorization")
     ```
     → *Static*, URL `https://badmintongpt.<your-zone>/welcome.html`, status **302** (never 301 —
     browsers cache a 301 and would bounce signed-in users too), *Preserve query string* off.
     Single Redirects run before Access, so the cookie-less visitor never hits the Access login.
     The `?login` query on the button is what keeps the rule from bouncing it back. A visitor with
     an expired `CF_Authorization` cookie skips the welcome page and lands on the Access login —
     harmless. If the rule is misconfigured, the failure mode is today's behaviour (Access login
     first); nothing else becomes public.

   Verify (no cookie): `curl -sI https://badmintongpt.<your-zone>/` → `302` to `/welcome.html`;
   `curl -sI https://badmintongpt.<your-zone>/welcome.html` → `200`;
   `curl -sI 'https://badmintongpt.<your-zone>/?login'` → redirect to `<team>.cloudflareaccess.com`.

> This repo's `REMOTE_MCP_SERVER_GUIDE.md` covers the same Tunnel+Access concepts for the
> *systemd* path; here cloudflared runs in a container and the tunnel is token-based.

---

## 2. Configure secrets

```bash
cp .env.example .env
# Fill in: OPENAI_API_KEY, REELS_CF_CLIENT_ID, REELS_CF_CLIENT_SECRET, TUNNEL_TOKEN,
#          NANOBOT_ACCOUNTS_WHITELIST (+ recommended CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD)
#          (for the DB build also: HF_TOKEN)
```

`.env` is git-ignored. Compose passes these to the containers; nanobot resolves `${VAR}` in
`nanobot/config.json` at startup (the committed config holds **no** secrets, only `${VAR}` refs).

---

## 3. Build the database (one-time, and whenever the dataset changes)

`data/` is git-ignored, so the DB is built locally — not baked into the image. The `ingest`
profile runs on the `badmintongpt-db` image (which carries `ingest.py` + the vendored
`ingest_lib/`); it is self-contained and needs only `HF_TOKEN`:

```bash
docker compose --profile ingest run --rm ingest           # writes ./data/badminton.db (needs HF_TOKEN)
docker compose run --rm --entrypoint python3 ingest /app/scripts/verify_db.py   # 30 assertions
```

The DB also merges a **local** dataset dir when one is passed. `todo0819/Data-old.zip` (190 match
folders, a superset of the HF dataset) is unpacked with `scripts/extract_data_old.py` — CSVs only
(~22 MB) plus a `rally_video_manifest.txt` that feeds `has_video` — and merged with
`ingest.py --local-data data/Data-old`. The 39 GB of rally videos are NOT part of this repo's data:
`scripts/extract_data_old.py --videos-to <badminton-reels>/data/Data` puts them on the reels host,
which is what renders clips. Until those CSVs are also pushed to HuggingFace
(`scripts/upload_data_old_to_hf.py`, needs a **write**-scoped `HF_TOKEN`), a container ingest must
mount/see `data/Data-old` and pass `--local-data`, otherwise it rebuilds the 32-folder HF-only DB.

The `badminton-db` MCP is an HTTP service now, not a stdio subprocess — so verification runs
against the same `badmintongpt-db` image (via the `ingest` profile, which mounts `./data`).
Once the stack is up you can also hit the live service's health endpoint:
`docker compose exec badminton-db curl -fsS http://127.0.0.1:8801/healthz`.

**Permissions:** the containers run as uid `1000`. If `./data` isn't writable by uid 1000 the
ingest step fails with a permission error — fix once with `sudo chown -R 1000:1000 data` (or
`mkdir -p data && chmod 777 data`). The finished `badminton.db` is world-readable, so the gateway
(also uid 1000) can read it regardless.

---

## 4. Bring up the stack

```bash
docker compose up -d --build
docker compose logs -f gateway cloudflared      # watch it connect
```

Then open `https://badmintongpt.<your-zone>/` (you'll hit the Cloudflare Access challenge first).

---

## 5. Verify end-to-end

```bash
# gateway healthy (internal health endpoint)
docker compose exec gateway curl -fsS http://127.0.0.1:18790/health        # -> ok

# badminton-db MCP healthy (internal HTTP service)
docker compose exec badminton-db curl -fsS http://127.0.0.1:8801/healthz   # -> ok

# public hostname reachable through Cloudflare (200 or an Access login redirect, NOT 502/530)
curl -I https://${BADMINTONGPT_HOSTNAME}/

# functional smoke test: exercises the badminton-db HTTP MCP + tool routing
docker compose exec gateway python3 /app/eval/run_eval.py --skip-reels
```

In the browser, confirm the **tool-progress bar** renders during a reel render — that proves the
**patched** WebUI (from `vendor/nanobot/`) is being served, not the stock dist.

---

## 6. Operations

- **Logs:** `docker compose logs -f gateway` / `... cloudflared`.
- **Restart after editing the agent brain/config** (`nanobot/config.json`, `nanobot/workspace/SOUL.md`,
  or `skills/*`): `docker compose up -d --build gateway` — the entrypoint re-installs the committed
  config/brain on boot; `sessions/` + `memory/` persist in the `nanobot_state` volume.
- **Pin `cloudflared`:** `docker-compose.yml` uses `cloudflare/cloudflared:latest` for convenience.
  For reproducibility, pin it to a specific release tag (or digest) once you've chosen one.
- **Updating nanobot itself:** `git subtree pull` the new upstream tag into `vendor/nanobot/`,
  resolve conflicts once, and rebuild (full runbook in `vendor/README.md`). The WebUI dist is rebuilt
  hermetically by the image's hatch hook, so there is no separate build/deploy-webui step and
  `uv tool upgrade nanobot-ai` does not affect the served dist (it's baked into the pinned image).
- **Monitoring / uptime + public status page:** stand up Gatus alongside this stack (one container,
  monitors as YAML; status page at `badmintongpt-status.<zone>`) — see [`MONITORING.md`](MONITORING.md).

---

## Accounts & quotas

The gateway runs with `NANOBOT_ACCOUNTS=1` (fork module `vendor/nanobot/nanobot/accounts.py`).
Every WebUI request carries the Cloudflare Access identity, and the gateway keys everything on that
e-mail:

| | Whitelisted (`NANOBOT_ACCOUNTS_WHITELIST`) | Everyone else |
|---|---|---|
| Usage limit | none | lifetime `NANOBOT_ACCOUNTS_QUOTA_USD` (default **$3.00**) |
| Settings / Apps / `/restart` `/model` `/dream*` `/pairing` | yes | no (403 / refused) — only Appearance + Speech |
| Conversations, projects, pins & titles, cron jobs | own only | own only |

- **What counts toward the quota:** every chat-model call charged to the user's session (agent
  turns, context compaction, title generation, subagents) at the per-1M-token prices
  (`gpt-5.5`: $5 input / $0.50 cached / $30 output; `gpt-6-luna`: $0.10 / $0.01 / $0.50, all
  doubled for a call with >272k input tokens; override with `NANOBOT_ACCOUNTS_PRICES`), plus
  every reel's **actual** API cost as reported by the reels server (`usage.cost_usd` on
  `generate_reel` / `get_reel_status` / `get_reel_result` — its script-model tokens and Fish TTS
  bytes). Video retrieval, CoachAI analytics and message TTS are not billed.
- **Enforcement:** a turn is refused up front once the allowance is spent (the WebUI shows *Usage
  limit reached*); a turn that crosses the line mid-way stops at its next model call, and new
  paid MCP jobs are refused (status/result polls still run so in-flight reels are metered). So
  the overshoot is at most one model call / one reel.
- **Usage page:** sidebar → the gauge button (shows the remaining balance) → spend, token counts,
  reels, daily spend. `GET /api/usage` returns the same JSON.
- **Ledger:** SQLite at `~/.nanobot/accounts.db` in the `nanobot_state` volume (session owners,
  per-call usage, per-job reel costs). Admin CLI:

  ```bash
  docker compose exec gateway python -m nanobot.accounts list
  docker compose exec gateway python -m nanobot.accounts set-quota someone@example.org 10   # raise one user
  docker compose exec gateway python -m nanobot.accounts reset-quota someone@example.org    # back to default
  ```
- **Invite codes** (`NANOBOT_ACCOUNTS_INVITE_REQUIRED`, on by default in `docker-compose.yml`):
  Cloudflare Access still decides who may sign in; after that a **new** account sees *Enter your
  invite code* and the gateway refuses its turns, model calls and paid MCP jobs until it redeems
  one. Codes are shared (many people use the same code), compared after NFKC / whitespace /
  case folding, and may cap how many accounts can redeem them. Accounts that existed when this
  was first deployed are activated by the ledger migration, and the whitelist never needs a code.
  After two wrong codes an account waits 30 s, then 60 s, 90 s, ... per further wrong code. The
  invite only lets the account in; its spend is still capped by the quota above. Codes live in
  the ledger, not in `.env`:

  ```bash
  docker compose exec gateway python -m nanobot.accounts invite create <code>               # no cap
  docker compose exec gateway python -m nanobot.accounts invite create <code> --max-uses 30 # 30 accounts
  docker compose exec gateway python -m nanobot.accounts invite list      # uses per code
  docker compose exec gateway python -m nanobot.accounts invite disable <code>  # redeemed accounts stay
  docker compose exec gateway python -m nanobot.accounts activate someone@example.org     # no code needed
  ```

  `list` shows accounts still waiting for a code as `NO INVITE`. Set
  `NANOBOT_ACCOUNTS_INVITE_REQUIRED=0` in `.env` to open sign-up again.
- **Input safety** (all on by default in `docker-compose.yml`):
  - *Moderation* (`NANOBOT_MODERATION`, `nanobot/moderation.py`): every chat message except slash
    commands goes through OpenAI's free `omni-moderation-latest` first (adds ~0.4–2 s). A message
    is refused (`content_flagged`, *Message not sent*; self-harm shows crisis lines instead) when a
    category score reaches its threshold. The endpoint's own `flagged` verdict is ignored because
    it flags badminton wording ("net kill", 用殺球把對手殺爆, 怎麼攻擊對手反手後場), so `violence`
    (0.9) and `illicit` (0.85) are set high; sexual, self-harm, hate, harassment and graphic
    violence block at 0.5 (sexual/minors 0.3). On a sample of 16 badminton questions and 10
    harmful requests this passed all 16 and blocked 7; the rest (a threat, poisoning, stalking)
    is left to the chat model's own refusals. Tune with `NANOBOT_MODERATION_THRESHOLDS`. The check
    fails open (a moderation outage logs a warning and lets messages through). Images are not
    moderated. Blocked messages are logged with the account and the categories, not the text.
  - *No local admin behind the proxy*: with `NANOBOT_WEBUI_TRUST_PROXY=1` a header-less request
    from loopback is refused instead of becoming the whitelisted `local@localhost`. Before this,
    anything inside the container (such as an agent `exec` command) could call the gateway's API
    as an unlimited admin.
  - *Sandboxed commands have no network* (`NANOBOT_SANDBOX_NO_NETWORK=1` → bwrap
    `--unshare-net`): `exec` cannot reach the gateway, the compose network or the internet. Web
    access stays with `web_fetch` / `web_search` and their SSRF guard.
- **Identity:** by default the `Cf-Access-Authenticated-User-Email` header is trusted (safe only
  because `8765` is `expose`-only and only cloudflared reaches it). Set `CF_ACCESS_TEAM_DOMAIN` +
  `CF_ACCESS_AUD` to verify the `Cf-Access-Jwt-Assertion` signature instead (recommended).
- **Existing conversations** (created before accounts) have no owner and are hidden from everyone
  until `NANOBOT_ACCOUNTS_LEGACY_OWNER=<e-mail>` adopts them at the next start. Projects created
  before accounts (`workspace/projects/<name>`) are likewise hidden; new ones live under
  `workspace/projects/<user>/`.
- **Shared memory is off** (`NANOBOT_DISABLE_SHARED_MEMORY=1`, `dream.enabled: false`): nanobot's
  `memory/history.jsonl` and `memory/MEMORY.md` are injected into *every* session's prompt, which
  would leak one user's conversations to another. Each chat still keeps its own compaction summary. The agent can no
  longer edit `SOUL.md` / `USER.md` / `memory/` / `skills/`, and cannot read `sessions/`.
- **Not isolated (known):** files the agent writes at the workspace root outside a project are
  visible to other users' agents; keep per-user work inside projects.

---

## Puzzle answer page

`https://badmintongpt.<your-zone>/puzzle.html` is a link-only page (nothing in the WebUI points to
it) where a signed-in user types a puzzle answer. It needs no Cloudflare change: only
`/welcome.html` bypasses Access, so this path asks for sign-in like the app itself.

- Set the answer in `.env` (`NANOBOT_PUZZLE_ANSWER=...`), then `docker compose up -d`. It is
  compared server-side only (full-width forms and whitespace are ignored). Unset → the page says
  answering is closed.
- After the n-th wrong answer an account must wait n/2 minutes (30 s, 1 min, 1.5 min, ...).
  Attempts are per e-mail in `~/.nanobot/puzzle.db` (volume). To reset one player:
  `docker compose exec gateway python -c "import sqlite3,os; sqlite3.connect(os.path.expanduser('~/.nanobot/puzzle.db')).execute('DELETE FROM puzzle_attempts WHERE email=?', ('someone@example.org',)).connection.commit()"`.

## 7. Migrating off the old in-session setup

The previous deployment ran `nanobot gateway` inside a login session and shared the single
`reels-mcp` cloudflared tunnel (`~/.cloudflared/config.yml`) for both `reels-mcp.<zone>` and
`badmintongpt.<zone>`. To cut over:

1. Bring up the new compose stack and confirm the new tunnel connects (`docker compose logs cloudflared`).
2. Move the `badmintongpt.<zone>` hostname onto the **new** tunnel (steps in §1).
3. **Remove the `badmintongpt.* → :8765` ingress line** from the old `~/.cloudflared/config.yml`
   and reload it — **leave `reels-mcp.* → :8900` intact** (reels stays externally hosted, untouched).
4. Stop the in-session host `nanobot gateway` so only the container serves the hostname.

The container keeps its own `nanobot_state` volume, so host and container agent state don't collide.
