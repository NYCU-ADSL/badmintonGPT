# badminton-db MCP

Self-contained MCP server over the read-only badminton SQLite DB, **plus** the DB-build
step. Has **no** dependency on the sibling `badminton-reels` project — the small parsing
surface it needs is vendored under [`ingest_lib/`](ingest_lib/).

## Contents
```
server.py        # FastMCP server: list_tables / describe_table / query (single SELECT, mode=ro)
ingest.py        # builds badminton.db from the HuggingFace dataset howard9199/Badminton
ingest_lib/      # vendored-from-reels DB-build support (models.py, parse.py, hf_loader.py)
scripts/         # ground_truth.py (oracle), verify_db.py (assertions), test_db_mcp.py (smoke test)
Dockerfile       # serve (default) + ingest (entrypoint override)
```

## Transport
`server.py` serves **streamable-http** at `/mcp` on `MCP_HOST:MCP_PORT` (default `0.0.0.0:8801`)
and a `/healthz` liveness route. nanobot reaches it as a `streamableHttp` MCP at
`http://badminton-db:8801/mcp` over the compose network (no auth — internal only, never
host-published, never tunneled). Set `MCP_TRANSPORT=stdio` to serve over stdio instead
(used by `scripts/test_db_mcp.py`).

## Tools
- `list_tables()` → table names
- `describe_table(table)` → `PRAGMA table_info`
- `query(sql)` → `{rows, row_count}` — a **single** `SELECT` only, max 200 rows, `mode=ro`

## Build the DB (ingest)
Needs only `HF_TOKEN` (no OPENAI/FISH/reels secrets):
```bash
# Docker (one-shot): writes ./data/badminton.db
docker compose --profile ingest run --rm ingest
# Host:
python ingest.py [--db PATH] [--catalog-only] [--only FOLDER] [--limit N] [--include-practice]
python scripts/verify_db.py        # assertions vs ground truth
python scripts/test_db_mcp.py      # stdio smoke test (sets MCP_TRANSPORT=stdio)
```

## Env
| var | default | purpose |
|-----|---------|---------|
| `BADMINTON_DB` | `/app/data/badminton.db` | SQLite path (server reads, ingest writes) |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8801` | HTTP bind |
| `MCP_TRANSPORT` | `streamable-http` | or `stdio` |
| `HF_TOKEN` | — | HuggingFace dataset access (ingest only) |
| `BADMINTON_HF_DIR` | `/app/data/hf_cache` | ingest CSV download cache |

## Decoupling note
If `badminton-reels` ever changes its CSV schema or the `RallySegment`/`ShotLabel` validators,
re-sync `ingest_lib/models.py` + `ingest_lib/parse.py`. `scripts/` includes a parity check that
diffs the vendored output against the live reels modules when `$REELS_SRC` is set.
