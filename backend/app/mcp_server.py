"""MCP server (interface — implemented by the MCP teammate). docs/API.md « MCP ».

Contract with ``app.main``:

* ``build_mcp_app()`` returns an ASGI application, or ``None`` while the server is not available
  (then ``/mcp`` is simply not exposed).
* ``app.main`` routes requests whose path is exactly ``/mcp`` or ``/mcp/`` to that application
  **without rewriting the path**, so build the transport with ``streamable_http_path="/mcp"``.
* If the returned object is a Starlette application, its lifespan (e.g. the streamable HTTP session
  manager) is entered by the main application's lifespan — do not start it yourself.

With the official SDK (``mcp`` 2.x, where ``FastMCP`` became ``mcp.server.mcpserver.MCPServer``)::

    from mcp.server.mcpserver import MCPServer
    server = MCPServer("ORBIT")
    ...register tools...
    return server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                      transport_security=...)  # allow the Host headers you serve

Tools: ``get_context``, ``get_snapshot``, ``search_sources``, ``propose_memory``, ``record_turn``,
``send_feedback`` (signatures in docs/API.md). An agent API key is mandatory
(``Authorization: Bearer orb_…`` or ``X-Orbit-Key``); validate it with
``app.deps.authenticate_agent_key`` and act as ``app.deps.Principal.for_agent(agent)`` on the
agent's own project, reusing the same services as the REST routers.
"""

from __future__ import annotations

from starlette.types import ASGIApp


def build_mcp_app() -> ASGIApp | None:
    """Return the MCP ASGI application, or ``None`` when MCP is not available on this instance."""
    return None
