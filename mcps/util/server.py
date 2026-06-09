#!/usr/bin/env python3
"""util-mcp — tiny local helper tools (stdio transport).

Currently exposes a single `sleep` tool so an agent can pace a polling loop
(e.g. "check status -> sleep -> check again") without busy-spinning. Keep this
server dependency-free and read-only; it must never touch external state.
"""
import time
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP("util")

MAX_SLEEP_SECONDS = 60


@mcp.tool()
def sleep(
    seconds: Annotated[int, Field(
        description="Number of seconds to pause. Values are clamped to "
                    "[0, 60]; use ~20-30 to space out a polling loop.")],
) -> dict:
    """Pause execution for `seconds` (capped at 60).

    Use this to space out a polling loop, e.g. when waiting for an async job:
    call get_*_status, and if it is still running, sleep(20-30) before checking
    again. Returns {"slept": <actual seconds slept>}.
    """
    n = max(0, min(int(seconds), MAX_SLEEP_SECONDS))
    time.sleep(n)
    return {
        "slept": n,
        "reminder": (
            "If you are polling a long-running job, do NOT emit a text-only "
            "reply while it is still running — that would end your turn and "
            "abort the polling loop. Keep polling silently (status -> sleep) "
            "until the job reaches a terminal state; the UI shows progress "
            "automatically. Only reply once you have the final result."
        ),
    }


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
