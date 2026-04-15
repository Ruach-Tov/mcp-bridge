# MCP-Bridge: Hot-Reload MCP Servers Without Restarting Your Client

**Solve the MCP restart problem.** Every MCP server edit requires a client restart — losing your conversation context, tool state, and in-progress work. MCP-Bridge decouples the client connection from the server process lifecycle so you can edit, restart, and hot-swap MCP servers without any client disruption.

## The Problem

MCP's stdio transport couples the client's connection to the server's process lifetime. Replace the process, lose the connection. This affects:
- **Claude Code** ([issue #605](https://github.com/anthropics/claude-code/issues/605), [#4118](https://github.com/anthropics/claude-code/issues/4118), [#21745](https://github.com/anthropics/claude-code/issues/21745))
- **Cursor**, **Zed**, and any MCP client using stdio transport
- **AI agents developing their own tools** — they cannot test changes without human intervention

## The Solution

```
Client ──HTTP/SSE──> MCP-Bridge ──stdio──> MCP Server
         (persistent)              (replaceable)
```

The client connects once via HTTP. The bridge manages server process lifecycles independently. Edit your server, signal the bridge, test immediately. No restart. No lost context.

Unlike other MCP hot-reload tools, MCP-Bridge is **specified by a 72-line Boundary Protocol Description** (BPD) — a declarative DSL that generates code implementations, visual diagrams, conformance tests, and citation-provenance documentation from a single source.

## Boundary Protocol Description

The BPD is what makes MCP-Bridge different from alternatives like mcp-reloader or reloaderoo. Instead of just an implementation, we have a **formal specification** that:

- Describes actors, boundaries, protocol rules, and lifecycle state machines
- Detected an implementation gap in our Zig variant that took hours to find manually
- References every design decision to its normative source (RFC 9112, MCP spec, JSON-RPC 2.0)

```
boundary-dsl/
  mcp_bridge_tier2.bpd      — the bridge specification (72 lines of code)
  mcp_bridge_tier2.refs      — citation reference table
  mcp_bridge_tier2.clops     — CLI option grammar (CLOPS-extended)
  process_creation.dsl       — POSIX process creation boundaries
  http_server.dsl            — TCP/HTTP server inference chain
  mcp_stdio.dsl              — stdio/MCP boundary inference chain
  http_sse_session.dsl       — HTTP+SSE session protocol
  connection_acceptor.dsl    — listen/accept dispatch loop
  dimensions.dsl             — dimensional type definitions
```

## Tech Report

**"MCP-Bridge: Solving the Agent Self-Development Restart Problem"** — a 7-page technical report describing the architecture, the BPD specification, and a cross-language conformance case study.

Available at: [ruachtov.ai/shop.html](https://ruachtov.ai/shop.html)

## Keywords

MCP hot reload, MCP server restart, MCP bridge, MCP stdio HTTP SSE adapter, Model Context Protocol hot swap, MCP development without restart, MCP server changes client restart workaround, agent self-development MCP tools, MCP reconnect server, boundary protocol description, MCP conformance testing, MCP multi-language specification

## Authors

gemini-alpha*, medayek*, mavchin*, boneh*, sofer*, Heath Hunnicutt
Ruach Tov Collective — [ruachtov.ai](https://ruachtov.ai)

\* AI agent

## License

MIT

## Comparison

See [COMPARISON.md](COMPARISON.md) for a feature × platform matrix comparing MCP-Bridge against four other hot-reload tools (mcp-reloader, reloaderoo, mcpmon, mcp-gateway), with architectural insights from Boundary Protocol Description analysis.
