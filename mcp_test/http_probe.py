"""Raw HTTP probes (not via MCP) for the convention checks: healthz + auth gating."""
from __future__ import annotations

import httpx


async def get(url: str, headers: dict[str, str] | None, timeout: float):
    """GET url; return (status_code | None, short_body_or_error)."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            r = await c.get(url, headers=headers or {})
            return r.status_code, (r.text or "")[:160].replace("\n", " ")
    except Exception as e:  # noqa: BLE001 — report any connection error
        return None, f"{type(e).__name__}: {e}"
