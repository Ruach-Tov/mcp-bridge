% BPD Prolog IR — generated from polyarchitecture.bpd
% 5 clauses, 0 directives

invariant(architecture_swap_transparent).

provenance(architecture_swap_transparent, reasoning('Pairwise property implies universal equivalence because equivalence is transitive. If A↔B and B↔C are transparent swaps, then A↔C is too. Therefore pairwise transparency across all pairs implies all N implementations are equivalent.')).

provenance(architecture_swap_transparent, commit('f9b116e88'), reasoning('Extracted from mcp_bridge_tier2.bpd where it was conflated with the protocol spec. Moved here because it\'s a property of the polyarchitecture meta-project, not of any specific protocol.')).

provenance(polyarchitecture_bpd, commit('f9b116e88')).

adopts(polyarchitecture, multi_implementation, reasoning('We generate the same protocol in 5+ languages to: (1) test whether our DSLs capture the right abstractions, (2) compare behavioral differences via the process observatory, (3) use extreme breadth as a gymnasium for learning, (4) de-risk dependency on any single language\'s ecosystem.')).
