# http_server.dsl — TCP listener and HTTP session boundary inference chain
#
# Layers:
#   http_listener_boundary: bind/listen surface owned by the server process
#   http_session_boundary: per-accepted-connection HTTP/SSE session boundary
#
# The key semantic split is that listening and accepted-session handling are
# not the same boundary. The listener persists across many sessions; each
# accepted connection creates a fresh per-session boundary.

boundary(NAME, A, B) :- http_listener_boundary(NAME, A, B)(:port, :addr) ->
  transport(NAME, :tcp).
  direction(NAME, :duplex).
  role(NAME, :listener).

http_listener_boundary(NAME, A, B)(P, H) ->
  bind(NAME, H, P).
  listen(NAME).

boundary(NAME, A, B) :- http_session_boundary(NAME, A, B)(session_ref) ->
  transport(NAME, :sse).                              #«1» MCP specifies HTTP+SSE as transport option
  direction(NAME, :duplex).
  role(NAME, :session).
  content(NAME, :json_rpc).                           #«2» JSON-RPC 2.0 content grammar
  derives_from(NAME, accepted_connection(session_ref)).
