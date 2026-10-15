"""Calculation-only ``exec``: accept nothing but ``python3 -c '<code>'`` that cannot touch the OS.

[badmintonGPT fork] Opt-in with ``NANOBOT_EXEC_PYTHON_ONLY=1``. BadmintonGPT uses ``exec`` only to
run statistics on rows already fetched from badminton-db (skills/data-analysis), so the shell
tool is narrowed to that:

* the command must be exactly ``python3 -c <code>`` (re-quoted before it reaches ``sh``, so no
  shell syntax around or inside it runs);
* the code may import only the calculation modules in :data:`ALLOWED_MODULES`;
* it may not name the escape hatches in :data:`FORBIDDEN_NAMES` (``open``, ``eval``,
  ``__import__``, ``getattr``, ...), nor read any attribute that starts with ``_`` or is in
  :data:`FORBIDDEN_ATTRIBUTES` (module handles that the allowed modules expose, such as
  ``statistics.sys`` or ``json.codecs.builtins``).

This is a static check, so it is best-effort on its own. It runs inside the bwrap sandbox, which
remains the boundary (no network, masked ``/proc``, workspace-only filesystem). What it adds is
that ordinary questions such as "what is the CPU load" cannot be answered through ``os`` /
``/proc`` even if the model is talked into trying.
"""

from __future__ import annotations

import ast
import shlex

ALLOWED_MODULES = frozenset({
    "bisect", "collections", "copy", "datetime", "decimal", "fractions", "functools", "heapq",
    "itertools", "json", "math", "random", "re", "statistics",
})

FORBIDDEN_NAMES = frozenset({
    "__import__", "__builtins__", "breakpoint", "compile", "delattr", "dir", "eval", "exec",
    "exit", "getattr", "globals", "hasattr", "help", "input", "locals", "memoryview", "open",
    "quit", "setattr", "vars",
})

# Public attributes of the allowed modules (or their submodules) that lead to modules outside
# ALLOWED_MODULES; found by walking the modules' attributes three levels deep on Python 3.12.
FORBIDDEN_ATTRIBUTES = frozenset({
    "bltns", "builtins", "codecs", "copyreg", "enum", "importlib", "inspect", "io", "modules",
    "operator", "os", "socket", "subprocess", "sys", "types", "warnings",
})

USAGE = (
    "Error: exec here only runs calculations: `python3 -c '<code>'` with nothing before or after "
    "it, importing only " + ", ".join(sorted(ALLOWED_MODULES)) + ". Files, the operating "
    "system, the network and other commands are not available. Embed the rows you fetched from "
    "badminton-db as a Python literal and print a compact result."
)


def python_only_command(command: str) -> str:
    """Return the safe, re-quoted command for *command*, or an ``Error: ...`` message."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return USAGE
    if len(argv) != 3 or argv[0] not in ("python3", "python") or argv[1] != "-c":
        return USAGE
    problem = check_code(argv[2])
    if problem:
        return f"{USAGE}\nRejected: {problem}."
    return shlex.join(["python3", "-I", "-c", argv[2]])


def check_code(code: str) -> str | None:
    """Return why *code* is not allowed, or None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"syntax error ({exc.msg}, line {exc.lineno})"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    return f"import of {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split(".")[0] not in ALLOWED_MODULES:
                return f"import from {node.module or '.'!r}"
            for alias in node.names:
                if alias.name == "*" or alias.name.startswith("_") \
                        or alias.name in FORBIDDEN_ATTRIBUTES:
                    return f"import of {alias.name!r} from {node.module!r}"
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                return f"use of {node.id!r}"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in FORBIDDEN_ATTRIBUTES:
                return f"attribute {node.attr!r}"
    return None
