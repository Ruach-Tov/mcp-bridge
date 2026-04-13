# connection_acceptor.dsl — Universal listen/accept connection loop
#
# A standard networking pattern: bind to an address, listen for
# connections, accept each into a new handler. The handler is
# parameterized — the acceptor doesn't know what protocol runs
# on the accepted connection.
#
# This is SM2 in a typical network service:
#   SM1 (process lifecycle) creates SM2 (acceptor) during :running
#   SM2 creates SM3 (session handler) for each accepted connection
#   SM2 itself is stateless per-connection — it just dispatches
#
# Semantic note: the acceptor is not itself the HTTP session boundary.
# It is the mechanism that turns a listener-owned socket admission event
# into a fresh per-session boundary instance.

state_machine_template(:connection_acceptor, host, port, on_accept) ->

  parameter(:connection_acceptor, :host, string, host).
  parameter(:connection_acceptor, :port, port, port).
  parameter(:connection_acceptor, :socket, fd, :nil).
  parameter(:connection_acceptor, :on_accept, template_ref, on_accept).

  state(:connection_acceptor, :unbound).
  state(:connection_acceptor, :listening).
  state(:connection_acceptor, :discontinued).

  # ── Bind and listen ──
  on(:connection_acceptor, :unbound, enter()) ->
    :socket := bind(:host, :port),
    listen(:socket).
  transition(:connection_acceptor, :unbound, :listening, socket_ready(:socket)).

  # ── Accept loop ──
  # accept() blocks until a connection arrives. Each accepted connection
  # instantiates the on_accept template with the new connection fd.
  # The acceptor stays in :listening — it does not follow the connection.
  on(:connection_acceptor, :listening, connection_arrived(:conn_fd)) ->
    instantiate(:on_accept, connection(:conn_fd)).
  # Self-transition: after dispatching, return to listening.
  transition(:connection_acceptor, :listening, :listening, dispatched).

  # ── Shutdown ──
  on(:connection_acceptor, :discontinued, enter()) ->
    close(:socket).
  transition(:connection_acceptor, :listening, :discontinued, stop_accepting).
