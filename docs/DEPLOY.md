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

> This repo's `REMOTE_MCP_SERVER_GUIDE.md` covers the same Tunnel+Access concepts for the
> *systemd* path; here cloudflared runs in a container and the tunnel is token-based.

---

## 2. Configure secrets

```bash
cp .env.example .env
# Fill in: OPENAI_API_KEY, REELS_CF_CLIENT_ID, REELS_CF_CLIENT_SECRET, TUNNEL_TOKEN
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
docker compose run --rm --entrypoint python3 ingest /app/scripts/verify_db.py   # 23 assertions
```

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
- **Updating nanobot itself:** re-vendor `vendor/nanobot/` (see `vendor/README.md`) and rebuild.
  The host scripts `scripts/build_webui.sh` / `deploy_webui.sh` are no longer on the deploy path —
  they remain only for host-mode WebUI dev. `uv tool upgrade nanobot-ai` no longer affects the
  served dist (it's baked into the pinned image).
- **Monitoring / uptime + public status page:** stand up Gatus alongside this stack (one container,
  monitors as YAML; status page at `badmintongpt-status.<zone>`) — see [`MONITORING.md`](MONITORING.md).

---

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
