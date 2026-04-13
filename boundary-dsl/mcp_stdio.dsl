# mcp_stdio.dsl — stdio/MCP boundary inference chain
#
# Layers:
#   stdio_boundary: pipe transport, newline-delimited framing, duplex
#   mcp_stdio_boundary: adds JSON-RPC content grammar

boundary( NAME, A, B ) :- stdio_boundary( NAME, A, B ) ->
  transport(NAME, :pipe).
  framing(NAME, :newline_delimited).
  direction(NAME, :duplex).

stdio_boundary( NAME, A, MCP_Service ) :- mcp_stdio_boundary( NAME, A, MCP_Service ) ->
  content(NAME, :json_rpc).
