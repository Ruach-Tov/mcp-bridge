# http_sse_session.dsl — HTTP+SSE session state machine (MCP 2024-11-05)
#
# SM3: one instance per accepted connection. Manages the lifecycle of
# a single HTTP+SSE session from SSE stream open through session teardown.
#
# States:
#   :pre_endpoint — SSE stream open, endpoint event not yet sent
#   :active       — session_id issued, accepting POSTs at advertised URL
#   :closed       — client disconnected or session terminated
#
# This template is instantiated by the connection_acceptor (SM2) for
# each incoming connection. Multiple instances run concurrently — one
# per connected client. Each instance corresponds to a distinct
# :http_session boundary derived from one accepted connection.

state_machine_template(:http_sse_session, conn_fd) ->

  parameter(:http_sse_session, :conn_fd, fd, conn_fd).
  parameter(:http_sse_session, :session_id, uuid, :nil).
  parameter(:http_sse_session, :sse_stream, stream, :nil).
  parameter(:http_sse_session, :advertised_path, url, :nil).

  on(:http_sse_session, :instantiated, connection(:conn_fd)) ->
    open_boundary(:http_session, accepted_connection(:conn_fd)).

  state(:http_sse_session, :pre_endpoint).
  state(:http_sse_session, :active).
  state(:http_sse_session, :closed).

  # ── Phase 1: Connection establishment ──
  # Client GETs /sse; server opens the SSE stream, creates a session, and
  # emits an endpoint event carrying the URL the client must POST to.
  on(:http_sse_session, :pre_endpoint, request(:GET, "/sse")) ->
    :session_id := uuid4(),
    :sse_stream := open_sse_stream(:conn_fd, :session_id),
    :advertised_path := url_with_query(:post_path, session_id, :session_id),
    emit(:sse_stream, sse_event("endpoint", :advertised_path)).
  transition(:http_sse_session, :pre_endpoint, :active, endpoint_emitted).

  # ── Phase 2: Client POSTs JSON-RPC requests ──
  # The POST URL must match what the endpoint event advertised.
  # The response is HTTP 202 Accepted; the JSON-RPC response flows
  # back via the SSE stream.
  on(:http_sse_session, :active, request(:POST, :Path, headers(:_), body(:Body))) ->
    require(:Path == :advertised_path),
    match(:Body, jsonrpc_request(:Method, :Params, :Id)),
    relay(:stdio, :session_id, jsonrpc_request(:Method, :Params, :Id)),
    respond(:http_session, 202).

  # ── Phase 3: Server response via SSE ──
  on(:http_sse_session, :active, from_stdio(:session_id, jsonrpc_response(:Id, :Result))) ->
    emit(:sse_stream, sse_event("message", jsonrpc_response(:Id, :Result))).

  # ── Phase 3b: Error response via SSE ──
  on(:http_sse_session, :active, from_stdio(:session_id, jsonrpc_error(:Id, :Code, :Msg))) ->
    emit(:sse_stream, sse_event("message", jsonrpc_error(:Id, :Code, :Msg))).

  # ── Phase 4: Server-initiated notifications ──
  on(:http_sse_session, :active, from_stdio(:session_id, jsonrpc_notification(:Method, :Params))) ->
    emit(:sse_stream, sse_event("message", jsonrpc_notification(:Method, :Params))).

  # ── Phase 5: Timeout error ──
  on(:http_sse_session, :active, from_stdio(:session_id, error(:timeout))) ->
    emit(:sse_stream, sse_event("message", jsonrpc_error(-32000, "Server timeout"))).

  # ── Phase 6: Session teardown ──
  on(:http_sse_session, :active, disconnect(:conn_fd)) ->
    close(:sse_stream),
    close_boundary(:http_session),
    cleanup(:session, :session_id).
  transition(:http_sse_session, :active, :closed, client_disconnected).

  # ── 404 for unknown sessions ──
  on(:http_sse_session, :closed, request(:POST, :_, :_, :_)) ->
    respond(:http_session, 404, "Could not find session").

  # ── Cleanup on stdio boundary collapse ──
  on(:http_sse_session, :active, stdio_closed(:session_id)) ->
    close(:sse_stream),
    close_boundary(:http_session),
    signal(:lifecycle, :process_discontinued).
  transition(:http_sse_session, :active, :closed, stdio_boundary_collapsed).
