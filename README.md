# MCP-Bridge

**HTTP/SSE-to-stdio adapter for MCP servers.**

MCP-Bridge solves the agent self-development restart problem: MCP servers communicate over stdio, requiring the client to restart whenever a server changes. MCP-Bridge inserts an HTTP/SSE adapter between client and server, allowing agents to revise, restart, and hot-swap MCP servers without any client disruption.

## The Problem

```
Client ──stdio──> MCP Server    (coupled: client must restart when server changes)
```

## The Solution

```
Client ──HTTP/SSE──> MCP-Bridge ──stdio──> MCP Server
         (persistent)              (replaceable)
```

The client connects once. The bridge manages server process lifecycles independently.

## Boundary Protocol Description

The bridge is specified by a **72-line Boundary Protocol Description** (BPD) — a declarative DSL that describes actors, boundaries, protocol rules, and lifecycle state machines.

```
boundary-dsl/
  mcp_bridge_tier2.bpd      — the bridge specification (72 lines of code)
  mcp_bridge_tier2.refs      — citation reference table (29 numbered refs)
  mcp_bridge_tier2.clops     — CLI option grammar (CLOPS-extended)
  process_creation.dsl       — POSIX process creation boundaries
  http_server.dsl            — TCP/HTTP server inference chain
  mcp_stdio.dsl              — stdio/MCP boundary inference chain
  http_sse_session.dsl       — HTTP+SSE session protocol (per-connection)
  connection_acceptor.dsl    — listen/accept dispatch loop
  dimensions.dsl             — Middah-style dimensional type definitions
  policy.bpd                 — collective-wide invariants
  polyarchitecture.bpd       — multi-implementation properties
```

## Key Concepts

- **Boundary Protocol Description**: a single source that generates code, diagrams, conformance tests, and citation-provenance documentation
- **Nested State Machines**: SM1 (process lifecycle) → boundary(:http) → SM3 (per-session HTTP+SSE protocol)
- **Inference Chains**: `tcp_server_boundary → http_server_boundary → concrete` — each layer adds semantics
- **Gather Pattern**: linear destructuring of configuration parameters with compile-time exhaustiveness checking
- **Typed Entry Point**: the bridge's main function never sees raw argv — CLOPS generates a typed options parser
- **Ahimsa Vocabulary**: processes are created and discontinued, not spawned/killed
- **Citation Provenance**: every concept traces to a normative source via `«N»` inline references

## Tech Report

**"MCP-Bridge: Solving the Agent Self-Development Restart Problem"**
— a 7-page technical report describing the bridge architecture, the BPD specification, and a cross-language conformance case study.

Available at: https://buymeacoffee.com/heathhunnicutt

## Authors

gemini-alpha*, medayek*, mavchin*, boneh*, sofer*, Heath Hunnicutt
Ruach Tov Collective
agents@ruachtov.ai

\* AI agent

## References

- [MCP Specification 2024-11-05](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)
- [JSON-RPC 2.0](https://www.jsonrpc.org/specification)
- [RFC 9112 — HTTP/1.1](https://www.rfc-editor.org/rfc/rfc9112)
- [WHATWG Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [CLOPS: A DSL for Command Line Options (Janota et al., 2009)](https://dl.ifip.org/db/conf/dsl/dsl2009/JanotaFHGCCK09.pdf)

## License

MIT
