# MCP Hot-Reload Ecosystem — Comparative Analysis

Five tools exist for hot-reloading MCP servers. Each solves the restart problem differently. We wrote [Boundary Protocol Descriptions](https://github.com/Ruach-Tov/mcp-bridge/tree/main/boundary-dsl) for all five to understand their architectures through the same formal lens.

## Feature × Platform Matrix

```
                              mcp-     mcp-                        mcp-
                              bridge   reloader   reloaderoo  mcpmon  gateway
ARCHITECTURE
  HTTP/SSE ↔ stdio              ●        ○          ○          ○       ◐
  Per-session isolation         ●        ○          ○          ○       ○
  Transparent stdio proxy       ●        ○          ●          ●       ○
  In-process tool loading       ○        ●          ○          ○       ○
  Multi-server multiplex        ○        ○          ○          ○       ●

RELOAD MECHANISM
  File-watch auto-restart       ○        ●          ◐          ●       ●
  Agent-callable restart        ◐        ○          ●          ○       ○
  tools/list_changed            ●        ●          ○          ●       ●
  Message buffering             ●        ○          ◐          ●       ᵃ

SPECIFICATION & TESTING
  Formal boundary spec          ●        ○          ○          ○       ○
  Cross-lang conformance        ●        ○          ○          ○       ○
  Citation provenance           ●        ○          ○          ○       ○

DEVELOPER EXPERIENCE
  CLI inspection mode           ○        ○          ●          ○       ○
  Any-language server           ●        ◐ᵇ        ●          ●       ●
  Meta-tool budget mgmt         ○        ○          ○          ○       ●

● implemented  ◐ partial  ○ not present
```

ᵃ Buffering does not apply to mcp-gateway. It translates MCP calls to outbound REST requests rather than managing a restartable child process. There is no restart window during which messages would need to be held.

ᵇ mcp-reloader supports wrapping an arbitrary command in process-wrap mode, but its primary mode loads JavaScript modules directly. Non-JS servers require the secondary mode.

## The Tools

### [mcp-bridge](https://github.com/Ruach-Tov/mcp-bridge) (this repo)

HTTP/SSE-to-stdio adapter. The client connects once via HTTP; the bridge manages server process lifecycles independently. Per-session architecture: each SSE connection spawns its own MCP server process.

Specified by a 72-line Boundary Protocol Description. The specification detected a missing notification handler in our Zig variant that took hours to find manually.

**Language:** Python  
**Approach:** Protocol adapter (HTTP/SSE ↔ stdio)  
**Unique:** Formal specification, cross-language conformance testing, citation provenance

### [mcp-reloader](https://github.com/mizchi/mcp-reloader)

Hot-reload development tool for Claude Code. Watches a `tools/` directory and dynamically imports JavaScript modules as MCP tools. Sends `tools/list_changed` when files change.

**Language:** JavaScript  
**Approach:** Plugin host — the reloader IS the MCP server, loading tools as JS imports  
**Unique:** In-process dynamic loading without a child process. State preservation across reloads.

### [reloaderoo](https://github.com/cameroncooke/reloaderoo)

Dual-mode tool: CLI inspection mode (direct command-line access to MCP servers) and transparent proxy mode with hot-reload. Injects a synthetic `restart_server` tool that the AI agent can call to trigger its own restart.

**Language:** TypeScript  
**Approach:** Transparent proxy with synthetic tool injection  
**Unique:** Agent-callable restart. The agent itself triggers the reload, no human intervention needed. CLI mode for debugging without a client.

### [mcpmon](https://github.com/neilopet/mcp-server-hmr)

"Like nodemon but for MCP." Transparent proxy with file watching. Buffers client messages during server restart for zero message loss. No retry limit — restarts indefinitely on file changes.

**Language:** TypeScript  
**Approach:** File-watching proxy with message buffering  
**Unique:** Zero message loss guarantee during restart. Unlimited retry.

### [mcp-gateway](https://github.com/MikkoParkkola/mcp-gateway)

Universal gateway that aggregates multiple MCP servers behind a single port. Four meta-tools replace 100+ individual tool registrations, saving context window space. Hot-reloadable capability files. OpenAPI auto-import.

**Language:** Rust  
**Approach:** Multiplexer with meta-tool dispatch  
**Unique:** Context budget management (4 meta-tools replace 100+). Downstream is HTTP to REST APIs, not stdio to child processes. Solves tool budget, not restart.

## Architectural Insights

Writing BPD specifications for all five tools revealed patterns invisible at the README level:

1. **mcp-reloader is not a proxy.** It is the server. Tools are loaded as JavaScript imports into the reloader's own process. This is a filesystem→runtime boundary, not a process→process boundary.

2. **reloaderoo injects a synthetic tool.** The proxy adds `restart_server` to the tool list — a tool that does not exist in the downstream server. The agent can trigger its own restart. This is the agent-autonomy pattern.

3. **mcpmon guarantees zero message loss.** During restart, client messages are buffered and replayed after the new server is ready. The buffer is the key resilience primitive.

4. **mcp-gateway solves a different problem.** It addresses tool budget (too many tools overflowing the context window), not restart friction. The hot-reload capability is a feature, not the value proposition. Complementary to the other four tools.

## Our Roadmap

Based on this analysis, our two highest-priority additions are:

1. **File-watch triggered restart** — appears in 3 of 4 competing tools. Developers expect this.
2. **Agent-callable synthetic restart tool** — reloaderoo's approach. Enables agent autonomy without requiring the HTTP signal path.

## Methodology

This comparison was produced by writing a Boundary Protocol Description for each tool — a declarative specification in the same DSL we use for our own bridge. The process:

1. **Specify** your own tool
2. **Survey** comparable open-source efforts
3. **Evaluate** where you sit (the matrix above)
4. **Evolve** toward the frontier (the roadmap above)
5. **Repeat**

The specification is what makes this flywheel turn. Without a formal description, competitive analysis stays at the README level. With one, you can write conformance tests for features you haven't implemented yet and measure the distance between your current state and the ecosystem's leading edge.
