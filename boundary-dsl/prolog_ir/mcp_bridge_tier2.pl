% BPD Prolog IR — generated from mcp_bridge_tier2.bpd
% 48 clauses, 8 directives

:- consult('mcp_bridge_tier2.refs').  % references
:- consult('dimensions.dsl').  % dimensions
:- consult('process_creation.dsl').
:- consult('connection_acceptor.dsl').
:- consult('http_server.dsl').
:- consult('mcp_stdio.dsl').
:- consult('http_sse_session.dsl').
:- consult('mcp_bridge_tier2.clops').  % clops

actor(X) :-
    process(X).

process(X) :-
    this_is(X).

process(client).

this_is(bridge).

process(server).

process(os).

process(shell).

posix_create_process(server_creation, bridge, S, extra_args(command)) :-
    create_server_process(S, extra_args(typed(string, command))).

http_listener_boundary(http_listener, client, bridge, extra_args('argv:port', 'argv:host')).

acceptor(http_acceptor, bridge, extra_args(bound_to(http_listener), on_accept(http_sse_session))).

http_session_boundary(http_session, client, bridge, extra_args(http_sse_session)).

lifetime(http_session, created_at(session_start), destroyed_at(session_end)).

derives_from(http_session, accepted_by(http_acceptor)).

on(http_listener, signal, listener_failed) :-
    close_boundary(http_listener).

mcp_stdio_boundary(mcp_server_connection, bridge, server) :-
    lifetime(mcp_server_connection, created_at(session_start), destroyed_at(session_end)).

derives_from(server_creation, channel(fds)).

relay(bridge, http_session, mcp_server_connection) :-
    parallel([relay(field(http_session, recv), field(mcp_server_connection, send)), relay(field(http_session, send), field(mcp_server_connection, recv)), inner_clause(relay_stderr(field(how_relay, stderr_mode)), pattern_match([arm(separate, relay(field(server, recv_stderr), log(bridge)))])), inner_clause(mixin, relay(field(server, recv_stderr), field(http_session, send))), inner_clause(discard, relay(field(server, recv_stderr), '0'))]).

gather_listen_endpoint(endpoint, service_args) :-
    destructure(field(endpoint, ['port', 'host']), field(service, ['port', 'host'])).

gather_atlaunch_args(atlaunch, service_args) :-
    destructure(field(atlaunch, ['command', 'cwd']), field(service, ['command', 'cwd'])).

gather_relay_args(how_relay, service_args) :-
    destructure(field(relay, stderr_mode), field(service, stderr_mode)).

gather_retry_args(how_retry, service_args) :-
    destructure(field(retry, max_retries), field(service, max_retries)).

service_launcher_state_machine(sm, service_args) :-
    inner_clause(initial_state(sm, invocation), gather_listen_endpoint(endpoint, service_args)), gather_atlaunch_args(atlaunch, service_args).

gather_relay_args(how_relay, service_args).

gather_retry_args(how_retry, service_args).

type_assert(consumed(service_args)).

absorbs(sm, [endpoint, atlaunch, how_relay, how_retry]).

constant(sm, max_restarts, cardinal(field(how_retry, max_restarts))).

variable(sm, 'N_restart', cardinal(range(0, max_restarts)), 0).

variable(sm, process_handle, process, nil).

initial_state(sm, invocation).

transition(sm, invocation, server_listen, configuration_absorbed).

state(sm, server_listen(endpoint)).

on(sm, server_listen, enter) :-
    open_boundary(http_listener).

transition(sm, server_listen, starting, boundary_open(http_listener)).

state(sm, starting(atlaunch)).

transition(sm, starting, running, exists(process_handle)).

state(sm, running(how_relay)).

transition(sm, running, discontinuation, (signal(TERM) ; (boundary_status(http_listener) == boundary_closed))).

transition(sm, running, error, \+ exists(process_handle)).

state(sm, error).

transition(sm, error, check_restart_allowed, pass).

conditional(sm, check_restart_allowed(how_retry)).

transition_conditional(sm, check_restart_allowed, tuple(restarting, discontinuation)).

state(sm, restarting).

on(sm, restarting, enter) :-
    increment(N_restart).

transition(sm, restarting, starting, pass).

final_state(sm, discontinuation).

on(sm, discontinuation, enter) :-
    close_boundary(http_listener), safe_call(process_handle, discontinue).
