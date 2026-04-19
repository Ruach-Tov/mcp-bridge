% BPD Prolog IR — generated from http_sse_session.dsl
% 20 clauses, 0 directives

state_machine_template(http_sse_session, conn_fd) :-
    parameter(http_sse_session, conn_fd, fd, conn_fd).

parameter(http_sse_session, session_id, uuid, nil).

parameter(http_sse_session, sse_stream, stream, nil).

parameter(http_sse_session, advertised_path, url, nil).

on(http_sse_session, instantiated, connection(conn_fd)) :-
    open_boundary(http_session, accepted_connection(conn_fd)).

state(http_sse_session, pre_endpoint).

state(http_sse_session, active).

state(http_sse_session, closed).

on(http_sse_session, pre_endpoint, request('GET', '/sse')) :-
    assign(session_id, uuid4), assign(sse_stream, open_sse_stream(conn_fd, session_id)), assign(advertised_path, url_with_query(post_path, session_id, session_id)), emit(sse_stream, sse_event('endpoint', advertised_path)).

transition(http_sse_session, pre_endpoint, active, endpoint_emitted).

on(http_sse_session, active, request('POST', 'Path', headers('_'), body('Body'))) :-
    require(('Path' == advertised_path)), match('Body', jsonrpc_request('Method', 'Params', 'Id')), relay(stdio, session_id, jsonrpc_request('Method', 'Params', 'Id')), respond(http_session, 202).

on(http_sse_session, active, from_stdio(session_id, jsonrpc_response('Id', 'Result'))) :-
    emit(sse_stream, sse_event('message', jsonrpc_response('Id', 'Result'))).

on(http_sse_session, active, from_stdio(session_id, jsonrpc_error('Id', 'Code', 'Msg'))) :-
    emit(sse_stream, sse_event('message', jsonrpc_error('Id', 'Code', 'Msg'))).

on(http_sse_session, active, from_stdio(session_id, jsonrpc_notification('Method', 'Params'))) :-
    emit(sse_stream, sse_event('message', jsonrpc_notification('Method', 'Params'))).

on(http_sse_session, active, from_stdio(session_id, error(timeout))) :-
    emit(sse_stream, sse_event('message', jsonrpc_error(-32000, 'Server timeout'))).

on(http_sse_session, active, disconnect(conn_fd)) :-
    close(sse_stream), close_boundary(http_session), cleanup(session, session_id).

transition(http_sse_session, active, closed, client_disconnected).

on(http_sse_session, closed, request('POST', '_', '_', '_')) :-
    respond(http_session, 404, 'Could not find session').

on(http_sse_session, active, stdio_closed(session_id)) :-
    close(sse_stream), close_boundary(http_session), signal(lifecycle, process_discontinued).

transition(http_sse_session, active, closed, stdio_boundary_collapsed).
