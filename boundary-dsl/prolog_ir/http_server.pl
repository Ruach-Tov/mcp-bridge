% BPD Prolog IR — generated from http_server.dsl
% 10 clauses, 0 directives

boundary(NAME, A, B) :-
    http_listener_boundary(NAME, A, B, extra_args(port, addr)),
    transport(NAME, tcp).

direction(NAME, duplex).

role(NAME, listener).

http_listener_boundary(NAME, A, B, extra_args(P, H)) :-
    bind(NAME, H, P).

listen(NAME).

boundary(NAME, A, B) :-
    http_session_boundary(NAME, A, B, extra_args(session_ref)),
    transport(NAME, sse).

direction(NAME, duplex).

role(NAME, session).

content(NAME, json_rpc).

derives_from(NAME, accepted_connection(session_ref)).
