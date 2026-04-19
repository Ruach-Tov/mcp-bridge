% BPD Semantic Consistency Checker v3
% Uses clause/2 to inspect predicates structurally rather than executing them.
%
% Author: mavchin (Claude Opus 4.6), 2026-04-17

:- use_module(library(aggregate)).
:- use_module(library(lists)).

% Load all IR files — suppress consult directives inside them
:- asserta((user:consult(_) :- true)).

:- load_files('prolog_ir/dimensions.pl', []).
:- load_files('prolog_ir/mcp_stdio.pl', []).
:- load_files('prolog_ir/connection_acceptor.pl', []).
:- load_files('prolog_ir/http_server.pl', []).
:- load_files('prolog_ir/http_sse_session.pl', []).
:- load_files('prolog_ir/process_creation.pl', []).
:- load_files('prolog_ir/policy.pl', []).
:- load_files('prolog_ir/polyarchitecture.pl', []).
:- load_files('prolog_ir/mcp_bridge_tier2.pl', []).

% ── STRUCTURAL QUERIES ──
% Use clause/2 to inspect what's defined, not to execute it.

% Count clauses for a given head pattern
count_clauses(Head, Count) :-
    findall(1, clause(Head, _), Ones),
    length(Ones, Count).

% Check if a state name is declared (handles parameterized states)
% state(sm, :running(:how_relay)) declares state "running"
% transition(sm, :running, ...) references state "running"
% These must match even though the state declaration has a parameter.
state_declared(SM, Name) :-
    clause(state(SM, Name), _), !.
state_declared(SM, Name) :-
    clause(state(SM, Term), _),
    compound(Term),
    functor(Term, Name, _), !.
state_declared(SM, Name) :-
    clause(initial_state(SM, Name), _), !.
state_declared(SM, Name) :-
    clause(final_state(SM, Name), _), !.
state_declared(SM, Name) :-
    clause(conditional(SM, Name), _), !.
state_declared(SM, Name) :-
    clause(conditional(SM, Term), _),
    compound(Term),
    functor(Term, Name, _), !.

run_all :-
    nl, write('BPD SEMANTIC CONSISTENCY CHECK'), nl,
    write('=============================='), nl, nl,

    % Fact inventory
    write('FACT INVENTORY:'), nl,
    count_clauses(process(_), PC), format('  process/1: ~w clauses~n', [PC]),
    count_clauses(actor(_), AC), format('  actor/1: ~w clauses~n', [AC]),
    count_clauses(this_is(_), TI), format('  this_is/1: ~w clauses~n', [TI]),
    count_clauses(boundary(_,_,_), BC), format('  boundary/3: ~w clauses~n', [BC]),
    count_clauses(state(_,_), SC), format('  state/2: ~w clauses~n', [SC]),
    count_clauses(transition(_,_,_,_), TC), format('  transition/4: ~w clauses~n', [TC]),
    count_clauses(on(_,_,_), OC), format('  on/3: ~w clauses~n', [OC]),
    count_clauses(initial_state(_,_), ISC), format('  initial_state/2: ~w clauses~n', [ISC]),
    count_clauses(final_state(_,_), FSC), format('  final_state/2: ~w clauses~n', [FSC]),
    count_clauses(dimension(_,_,_), D3), format('  dimension/3: ~w clauses~n', [D3]),
    count_clauses(dimension(_,_,_,_), D4), format('  dimension/4: ~w clauses~n', [D4]),
    count_clauses(provenance(_,_), PVC), format('  provenance/2: ~w clauses~n', [PVC]),
    count_clauses(relay(_,_,_), RC), format('  relay/3: ~w clauses~n', [RC]),
    count_clauses(service_launcher_state_machine(_,_), SMC),
    format('  service_launcher_state_machine/2: ~w clauses~n', [SMC]),
    nl,

    % Check 1: Collect all declared processes/actors
    write('CHECK 1: Declared actors/processes'), nl,
    findall(P, clause(process(P), true), FactProcesses),
    findall(P, (clause(process(P), Body), Body \= true), RuleProcesses),
    findall(A, clause(actor(A), _), Actors),
    findall(T, clause(this_is(T), _), ThisIs),
    format('  Fact processes: ~w~n', [FactProcesses]),
    format('  Rule processes (derived): ~w~n', [RuleProcesses]),
    format('  Actors: ~w~n', [Actors]),
    format('  this_is: ~w~n', [ThisIs]),
    nl,

    % Check 2: Collect all states
    write('CHECK 2: State declarations'), nl,
    findall(SM-S, clause(state(SM, S), _), States),
    findall(SM-S, clause(initial_state(SM, S), _), InitStates),
    findall(SM-S, clause(final_state(SM, S), _), FinalStates),
    format('  States: ~w~n', [States]),
    format('  Initial: ~w~n', [InitStates]),
    format('  Final: ~w~n', [FinalStates]),
    nl,

    % Check 3: Collect all transitions and verify states exist
    write('CHECK 3: Transitions reference declared states'), nl,
    findall(SM-From-To, clause(transition(SM, From, To, _), _), Transitions),
    format('  Transitions: ~w~n', [Transitions]),
    
    % Check each transition's From state is declared
    % Note: conditional() is a state subtype (diamond on diagram)
    % Note: state(sm, running(how_relay)) declares state "running"
    forall(
        (clause(transition(SM, From, _, _), _),
         \+ state_declared(SM, From)),
        format('  WARNING: state ~w in SM ~w used in transition but not declared~n', [From, SM])
    ),
    
    % Check each transition's To state is declared
    forall(
        (clause(transition(SM, _, To, _), _),
         \+ state_declared(SM, To)),
        format('  WARNING: target state ~w in SM ~w not declared~n', [To, SM])
    ),
    nl,

    % Check 4: Event handlers reference declared states
    write('CHECK 4: Event handlers for declared states'), nl,
    forall(
        (clause(on(SM, State, _), _),
         \+ state_declared(SM, State)),
        format('  WARNING: on(~w, ~w, ...) but state not declared~n', [SM, State])
    ),
    nl,

    % Check 5: Dimensions
    write('CHECK 5: Dimensions'), nl,
    forall(
        clause(dimension(Name, Label, Type), _),
        format('  ~w : ~w (~w)~n', [Name, Type, Label])
    ),
    forall(
        clause(dimension(Name, Label, Type, Constraint), _),
        format('  ~w : ~w (~w) [~w]~n', [Name, Type, Label, Constraint])
    ),
    nl,

    % Check 6: Provenance
    write('CHECK 6: Provenance entries'), nl,
    forall(
        clause(provenance(Concept, _), _),
        format('  ~w~n', [Concept])
    ),
    nl,

    % Check 7: State machine completeness
    write('CHECK 7: State machines'), nl,
    forall(
        clause(service_launcher_state_machine(SM, _), _),
        (
            format('  SM: ~w~n', [SM]),
            (clause(initial_state(SM, IS), _) ->
                format('    initial: ~w~n', [IS])
            ;
                format('    WARNING: no initial state~n', [])
            ),
            (clause(final_state(SM, FS), _) ->
                format('    final: ~w~n', [FS])
            ;
                format('    WARNING: no final state~n', [])
            ),
            count_clauses(state(SM, _), SMStates),
            count_clauses(transition(SM, _, _, _), SMTrans),
            count_clauses(on(SM, _, _), SMHandlers),
            format('    ~w states, ~w transitions, ~w handlers~n', [SMStates, SMTrans, SMHandlers])
        )
    ),
    nl,

    write('=============================='), nl,
    write('CONSISTENCY CHECK COMPLETE'), nl.

:- initialization((run_all, halt)).
