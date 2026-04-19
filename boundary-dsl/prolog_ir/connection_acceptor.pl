% BPD Prolog IR — generated from connection_acceptor.dsl
% 13 clauses, 0 directives

state_machine_template(connection_acceptor, host, port, on_accept) :-
    parameter(connection_acceptor, host, string, host).

parameter(connection_acceptor, port, port, port).

parameter(connection_acceptor, socket, fd, nil).

parameter(connection_acceptor, on_accept, template_ref, on_accept).

state(connection_acceptor, unbound).

state(connection_acceptor, listening).

state(connection_acceptor, discontinued).

on(connection_acceptor, unbound, enter) :-
    assign(socket, bind(host, port)), listen(socket).

transition(connection_acceptor, unbound, listening, socket_ready(socket)).

on(connection_acceptor, listening, connection_arrived(conn_fd)) :-
    instantiate(on_accept, connection(conn_fd)).

transition(connection_acceptor, listening, listening, dispatched).

on(connection_acceptor, discontinued, enter) :-
    close(socket).

transition(connection_acceptor, listening, discontinued, stop_accepting).
