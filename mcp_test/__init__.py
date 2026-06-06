"""mcp-test — read-only conformance tester for MCP servers.

Point it at a remote (Streamable HTTP) or local (stdio) MCP server and it runs
protocol + convention checks WITHOUT calling business tools (zero side effects).

Run: python -m mcp_test <MCP_URL> [--header "K: V"]...   (see MCP_TEST.md)
"""
__version__ = "0.1.0"
