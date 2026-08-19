# Gatus — BadmintonGPT uptime + public status page

A single-container uptime monitor with a public status page at
`https://badmintongpt-status.nycu-adsl.cc/`. Monitors are defined as committed YAML in
[`config/config.yaml`](config/config.yaml) (config-as-code).

**Full tutorial:** [`../../docs/MONITORING.md`](../../docs/MONITORING.md)

## What's here

| file | purpose |
|---|---|
| `docker-compose.yml` | `gatus` (monitor + status page) + `cloudflared` (the badmintongpt-status tunnel) |
| `config/config.yaml` | the monitor definitions + status-page UI (committed; no secrets) |
| `.env.example` | template → copy to `.env` (git-ignored): `TUNNEL_TOKEN` + `REELS_CF_*` |

## Quickstart

```bash
cd monitoring/gatus
cp .env.example .env        # fill TUNNEL_TOKEN + REELS_CF_CLIENT_ID/SECRET + ANALYZE_MCP_TOKEN
docker compose up -d
docker compose logs -f cloudflared    # watch the tunnel register
```

The BadmintonGPT stack must already be running (gatus joins its `badmintongpt_default` network to
reach `badmintongpt-db:8801` / `badmintongpt-gateway:8765` by name).

- **Public status page:** `https://badmintongpt-status.nycu-adsl.cc/`
- **Local preview:** `http://127.0.0.1:8095/` (loopback only)

## Add / change a monitor

Edit `config/config.yaml`, then `docker compose restart gatus`. Each entry is an HTTP(S) check with
`conditions` (status code, body JSON path, response time, cert expiry, …). Custom request headers
(e.g. the reels Cloudflare Access token) go under `headers:` with `${VAR}` substituted from `.env`.
