# dimensions.dsl — Middah-style dimensional type definitions
#
# Dimensions provide type checking across boundaries. A value
# in one dimension cannot be confused with a value in another,
# even if the underlying machine type is the same.
#
# dimension(Name, Label, BaseType [, Constraint]).

dimension(:count, "Qty", cardinal).
dimension(:port, "Port", range(1024, 65535)).
dimension(:session_id, "SessionId", uuid).
dimension(:duration, "Duration.s", float, positive).
dimension(:latency, "Latency.ms", float, positive).
