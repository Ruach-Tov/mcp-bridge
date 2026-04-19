% BPD Prolog IR — generated from dimensions.dsl
% 5 clauses, 0 directives

dimension(count, 'Qty', cardinal).

dimension(port, 'Port', range(1024, 65535)).

dimension(session_id, 'SessionId', uuid).

dimension(duration, 'Duration.s', float, positive).

dimension(latency, 'Latency.ms', float, positive).
