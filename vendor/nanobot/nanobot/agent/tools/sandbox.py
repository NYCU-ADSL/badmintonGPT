"""Sandbox backends for shell command execution.

To add a new backend, implement a function with the signature:
    _wrap_<name>(command: str, workspace: str, cwd: str) -> str
and register it in _BACKENDS below.
"""

import os
import shlex
from pathlib import Path

from nanobot.config.paths import get_media_dir


def _bwrap(command: str, workspace: str, cwd: str) -> str:
    """Wrap command in a bubblewrap sandbox (requires bwrap in container).

    Only the workspace is bind-mounted read-write; its parent dir (which holds
    config.json) is hidden behind a fresh tmpfs.  The media directory is
    bind-mounted read-only so exec commands can read uploaded attachments.
    """
    ws = Path(workspace).resolve()
    media = get_media_dir().resolve()

    try:
        sandbox_cwd = str(ws / Path(cwd).resolve().relative_to(ws))
    except ValueError:
        sandbox_cwd = str(ws)

    required  = ["/usr"]
    optional  = ["/bin", "/lib", "/lib64", "/etc/alternatives",
                 "/etc/ssl/certs", "/etc/resolv.conf", "/etc/ld.so.cache"]

    args = ["bwrap", "--new-session", "--die-with-parent"]
    # [badmintonGPT fork] NANOBOT_SANDBOX_NO_NETWORK=1: commands get their own empty network
    # namespace, so they cannot reach the gateway's own API on loopback, the compose network or
    # the internet (web access stays with the web_fetch / web_search tools and their SSRF guard).
    if _flag("NANOBOT_SANDBOX_NO_NETWORK"):
        args.append("--unshare-net")
    # NANOBOT_SANDBOX_STRICT=1 also isolates IPC, the hostname and cgroups, and masks the /proc
    # files that describe the host (load, CPU, memory, uptime, mounts). A new PID namespace is not
    # possible inside the container (mounting its /proc is refused), and python needs /proc.
    strict = _flag("NANOBOT_SANDBOX_STRICT")
    if strict:
        args += ["--unshare-ipc", "--unshare-uts", "--hostname", "sandbox", "--unshare-cgroup-try"]
    for p in required: args += ["--ro-bind",     p, p]
    for p in optional: args += ["--ro-bind-try", p, p]
    args += [
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    ]
    if strict:
        for name in _HOST_PROC_FILES:
            args += ["--ro-bind-try", "/dev/null", f"/proc/{name}"]
    args += [
        "--tmpfs", str(ws.parent),        # mask config dir
        "--dir", str(ws),                 # recreate workspace mount point
        "--bind", str(ws), str(ws),
    ]
    args += _account_masks(ws, media)
    args += [
        "--chdir", sandbox_cwd,
        "--", "sh", "-c", command,
    ]
    return shlex.join(args)


_HOST_PROC_FILES = (
    "loadavg", "cpuinfo", "meminfo", "stat", "uptime", "vmstat", "diskstats", "partitions",
    "swaps", "version", "mounts",
)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _account_masks(ws: Path, media: Path) -> list[str]:
    """Extra bwrap mounts after the workspace bind. [badmintonGPT fork]

    Stock: read-only media. With NANOBOT_ACCOUNTS this mirrors
    ``nanobot.accounts.private_path_violation`` for the shell instead: the all-users media dir is
    not mounted, and when *ws* is the agent workspace (project chats only ever mount their own
    project dir) other users' sessions, the shared memory history and other users' projects are
    hidden behind empty tmpfs mounts while shared agent config is read-only.
    """
    from nanobot.accounts import account_slug, accounts_enabled, current_account_email

    if not accounts_enabled():
        return ["--ro-bind-try", str(media), str(media)]
    if not (ws / "sessions").is_dir():
        return []
    masks: list[str] = []
    for name in ("sessions", "memory"):
        if (ws / name).is_dir():
            masks += ["--tmpfs", str(ws / name)]
    for name in ("SOUL.md", "USER.md", "AGENTS.md", "HEARTBEAT.md", "TOOLS.md", "skills"):
        masks += ["--ro-bind-try", str(ws / name), str(ws / name)]
    projects = ws / "projects"
    if projects.is_dir():
        masks += ["--tmpfs", str(projects)]
        email = current_account_email()
        own = projects / account_slug(email) if email else None
        if own is not None and own.is_dir():
            masks += ["--dir", str(own), "--bind", str(own), str(own)]
    return masks


_BACKENDS = {"bwrap": _bwrap}


def wrap_command(sandbox: str, command: str, workspace: str, cwd: str) -> str:
    """Wrap *command* using the named sandbox backend."""
    if backend := _BACKENDS.get(sandbox):
        return backend(command, workspace, cwd)
    raise ValueError(f"Unknown sandbox backend {sandbox!r}. Available: {list(_BACKENDS)}")
