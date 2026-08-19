# Monitoring BadmintonGPT (Gatus uptime + public status page)

This stands up [**Gatus**](https://github.com/TwiN/gatus) — a tiny, single-container uptime monitor
with a built-in public status page — on the same host as the BadmintonGPT stack. It monitors the
agent gateway and the MCP servers (internally *and* via the public edge) and publishes a status page
at `https://badmintongpt-status.nycu-adsl.cc/`.

Monitors are **config-as-code**: defined in committed YAML
([`monitoring/gatus/config/config.yaml`](../monitoring/gatus/config/config.yaml)). The whole thing is
**two containers** (Gatus + its Cloudflare tunnel) and one config file.

> Why Gatus and not OpenStatus? Self-hosting OpenStatus needs ~9 containers (incl. ClickHouse/Tinybird),
> a Google-Cloud-Tasks scheduler (or a hand-built poller), and its public status page + private
> locations are beta. Gatus does exactly what we need — HTTP checks against internal + Cloudflare
> targets, with a public status page — in one small Go container with committed config.

```
                         ┌─ (internal, badmintongpt_default net) ─ badmintongpt-db:8801/healthz
public internet          │                                        badmintongpt-gateway:8765/
   │                     │
   ▼                     │   Gatus stack (compose project "gatus")
badmintongpt-status.<zone>   gatus  ── checks ──┐
 (Cloudflare, NO Access) │     ▲                ├─▶ internal targets (above)
   │                     │     │ (alias          └─▶ public targets:
cloudflared ─────────────┘     │  status-page)       https://badmintongpt.<zone>/      (edge, behind Access)
  → status-page:3000 ──────────┘                     https://reels-mcp.<zone>/healthz   (CF Access token)
                                                      https://video-retrieval.nycu-cgvlab.org/healthz (public)
                                                      https://coachai.cs.nycu.edu.tw/mcp  (POST initialize, bearer)
                                                      https://badmintongpt-docs.<zone>/ (Pages)
```

## What gets monitored

See [`monitoring/gatus/config/config.yaml`](../monitoring/gatus/config/config.yaml). Seven checks:
`badminton-db` MCP `/healthz` and the agent gateway WebUI (checked **internally** by container name),
plus the public gateway edge, the remote reels MCP, the remote video-retrieval MCP, the remote
badminton-analyze MCP, and the docs site (checked **externally**).

| target | scope | condition |
|---|---|---|
| `http://badmintongpt-db:8801/healthz` | internal | `200` + body `ok == true` |
| `http://badmintongpt-gateway:8765/` | internal | `200` |
| `https://badmintongpt.nycu-adsl.cc/` | public edge | `status < 500` (Access returns 302/403; 5xx = down) |
| `https://reels-mcp.nycu-adsl.cc/healthz` | public | `200` (with CF-Access headers) |
| `https://video-retrieval.nycu-cgvlab.org/healthz` | public | `200` + body `ok == true` (no Access) |
| `https://coachai.cs.nycu.edu.tw/mcp` | public | `POST` JSON-RPC `initialize` → `200` + body matches `BadmintonAnalysisServer` (bearer token; this server has **no** `/healthz` — `GET /` and `/healthz` both 500) |
| `https://badmintongpt-docs.nycu-adsl.cc/` | public | `200` |

## Prerequisites

- The **BadmintonGPT stack is running** (`docker compose up -d` per [`DEPLOY.md`](DEPLOY.md)) — Gatus
  joins its network to reach internal targets:
  ```bash
  docker network ls | grep badmintongpt            # expect: badmintongpt_default
  ```
  If the network has a different name, update the `external` network name in
  `monitoring/gatus/docker-compose.yml`.

## 1. Cloudflare one-time setup (the status subdomain)

Create a **dedicated** tunnel for the status page (don't reuse the `badmintongpt` gateway tunnel).
All steps are in the Cloudflare dashboard.

1. **Create the tunnel.** Zero Trust → **Networks → Tunnels** → *Create a tunnel* → **Cloudflared** →
   name `badmintongpt-status`. Copy the **tunnel token** → `TUNNEL_TOKEN` in `.env`.
2. **Add the public hostname:** **Subdomain** `badmintongpt-status`, **Domain** `nycu-adsl.cc`,
   **Service** `HTTP` → `status-page:3000`.
   - Keep it a **single label** under the zone (`badmintongpt-status.nycu-adsl.cc`, not
     `badmintongpt.status.nycu-adsl.cc`): Cloudflare's free universal cert `*.nycu-adsl.cc` covers one
     label only — a two-label host fails TLS (`handshake failure`) and would need paid Advanced
     Certificate Manager.
   - The service name `status-page` is intentional: the Gatus container is **aliased** to
     `status-page` and listens on `3000`, so this ingress resolves with **no** dashboard change later.
     (If you used a different service URL, point it at `http://status-page:3000` or `http://gatus:3000`.)
3. **Do NOT add a Cloudflare Access policy** — a status page is public.

## 2. Bring it up

```bash
cd monitoring/gatus
cp .env.example .env          # fill TUNNEL_TOKEN + REELS_CF_CLIENT_ID/SECRET (copy reels creds from ../../.env)
docker compose up -d
docker compose logs -f cloudflared      # wait for "Registered tunnel connection"
```

## 3. Verify

```bash
# Gatus up locally (loopback preview)
curl -sI http://127.0.0.1:8095/ | head -1                       # 200

# Gatus can reach the internal targets, and each check's status via its API:
curl -s http://127.0.0.1:8095/api/v1/endpoints/statuses | head -c 600

# Public status page through the tunnel
curl -sI https://badmintongpt-status.nycu-adsl.cc/ | head -1     # 200, no Access challenge
```

Open `https://badmintongpt-status.nycu-adsl.cc/` — every endpoint should go green within a couple of
check intervals. The internal checks prove the actual container health; the `public edge` check proves
the Cloudflare tunnel + Access + origin are alive (it asserts non-5xx, since Access returns a 302/403
login redirect for an unauthenticated probe).

## 4. Add or change a monitor

Edit [`config/config.yaml`](../monitoring/gatus/config/config.yaml) and `docker compose restart gatus`.
Each endpoint supports `conditions` on `[STATUS]`, `[BODY].<json.path>`, `[RESPONSE_TIME]`,
`[CERTIFICATE_EXPIRATION]`, etc., and custom `headers:` (use `${VAR}` — substituted from `.env`).

## 5. Operations

- **Logs:** `docker compose logs -f gatus` / `... cloudflared`.
- **Alerting (optional):** add an `alerting:` block (Slack/Discord/Telegram/PagerDuty/email/webhook)
  and per-endpoint `alerts:` in `config.yaml` — see the [Gatus docs](https://github.com/TwiN/gatus#alerting).
- **History:** uptime/response-time history persists in the `gatus-data` volume (sqlite).
- **Pin the image:** `docker-compose.yml` uses `ghcr.io/twin/gatus:latest`; pin a tag/digest for
  reproducibility once chosen.
- **Ordering:** the BadmintonGPT stack must be up first (the `external` network must pre-exist).

See also: [`DEPLOY.md`](DEPLOY.md) (the BadmintonGPT stack + its tunnel/Access pattern) and
[`REMOTE_MCP_SERVER_GUIDE.md`](REMOTE_MCP_SERVER_GUIDE.md) (the Cloudflare Access service-token pattern
reused for the reels monitor).
