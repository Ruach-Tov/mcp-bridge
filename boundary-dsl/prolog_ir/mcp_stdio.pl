% BPD Prolog IR — generated from mcp_stdio.dsl
% 4 clauses, 0 directives

boundary(NAME, A, B) :-
    stdio_boundary(NAME, A, B),
    transport(NAME, pipe).

framing(NAME, newline_delimited).

direction(NAME, duplex).

stdio_boundary(NAME, A, MCP_Service) :-
    mcp_stdio_boundary(NAME, A, MCP_Service),
    content(NAME, json_rpc).
