"""BPD Tier II AST — Typed dataclasses for the parsed BPD tree.

Every node in the BPD parse tree maps to one of these dataclasses.
The AST is the bridge between BPD surface syntax and any backend
(Prolog IR, code generation, diagram rendering, verification queries).

Author: mavchin (Claude Opus 4.6), 2026-04-16
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional, Union


# ── Atoms and Variables ─────────────────────────────────────────

@dataclass(frozen=True)
class Atom:
    """A colon-prefixed atom: :client, :bridge, :0, :_"""
    name: str

    def __str__(self) -> str:
        return f":{self.name}"


@dataclass(frozen=True)
class Variable:
    """An uppercase-initial variable: X, S, NAME, PROCESS"""
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class IntLiteral:
    value: int


@dataclass(frozen=True)
class StringLiteral:
    value: str


Literal = Union[IntLiteral, StringLiteral]


# ── Terms ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompoundTerm:
    """A functor with arguments: process(:client), on(sm, :state, event())

    The optional `extra_args` holds the second parameter tuple for
    boundary-style declarations, e.g.
        http_listener_boundary(:http_listener, :client, :bridge)(:argv:port, :argv:host)
    which has args=(:http_listener, :client, :bridge) and
    extra_args=(:argv:port, :argv:host).
    When `extra_args` is None (default), the compound term is single-tuple.
    """
    functor: str
    args: tuple[Term, ...] = ()
    extra_args: Optional[tuple[Term, ...]] = None

    def __str__(self) -> str:
        args_str = ", ".join(str(a) for a in self.args)
        base = f"{self.functor}({args_str})" if self.args else f"{self.functor}()"
        if self.extra_args is not None:
            extra_str = ", ".join(str(a) for a in self.extra_args)
            return f"{base}({extra_str})"
        return base


@dataclass(frozen=True)
class FieldAccess:
    """Dotted field access: :service.port, :how_retry.max_restarts"""
    base: Union[Atom, Variable]
    field: str


@dataclass(frozen=True)
class TupleFieldAccess:
    """Tuple destructure: :service.(port, host)"""
    base: Union[Atom, Variable]
    fields: tuple[str, ...]


@dataclass(frozen=True)
class ListTerm:
    """List: [:endpoint, :atlaunch, :how_relay]"""
    elements: tuple[Term, ...]


@dataclass(frozen=True)
class InfixExpr:
    """Infix expression: a == b, a or b"""
    left: Term
    op: str
    right: Term


@dataclass(frozen=True)
class NotExpr:
    """Negation: not exists(:process_handle)"""
    operand: Term


@dataclass(frozen=True)
class RangeExpr:
    """Range: 0..:max_restarts"""
    low: Union[IntLiteral, Atom, Variable]
    high: Union[IntLiteral, Atom, Variable]


@dataclass(frozen=True)
class BareName:
    """A bare lowercase identifier used as a term value: cardinal, uuid, float"""
    name: str
    is_array: bool = False

    def __str__(self) -> str:
        return f"{self.name}[]" if self.is_array else self.name


@dataclass(frozen=True)
class TypedParam:
    """A typed parameter: string command, process P"""
    type_name: str
    var: Union['Variable', 'BareName']


@dataclass(frozen=True)
class TupleTerm:
    """A parenthesized tuple: (:restarting, :discontinuation)"""
    elements: tuple['Term', ...]


@dataclass(frozen=True)
class SafeNavCall:
    """Safe navigation: process_handle?.discontinue()"""
    base: Union[Atom, Variable]
    method: str
    args: tuple[Term, ...] = ()


@dataclass(frozen=True)
class Increment:
    """Postfix increment: N_restart++"""
    variable: Variable


Term = Union[
    Atom, Variable, IntLiteral, StringLiteral,
    CompoundTerm, FieldAccess, TupleFieldAccess,
    ListTerm, InfixExpr, NotExpr, RangeExpr,
    SafeNavCall, Increment, BareName, TypedParam, TupleTerm,
]


# ── Assignment ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Assignment:
    """:session_id := uuid4()"""
    target: Atom
    value: Term


@dataclass(frozen=True)
class Destructure:
    """:endpoint.(port, host) <- :service.(port, host)"""
    target: Union[FieldAccess, TupleFieldAccess]
    source: Term


# ── Body Elements ───────────────────────────────────────────────

BodyElement = Union[Term, Assignment, Destructure, Increment, "InnerClause", "PatternMatch"]


@dataclass
class Body:
    """A sequence of body elements (conjunction/sequencing)."""
    elements: list[BodyElement] = field(default_factory=list)


@dataclass
class ParallelBody:
    """Parallel composition: relay(a, b) | relay(c, d)"""
    branches: list[Body] = field(default_factory=list)


@dataclass
class PatternArm:
    """One arm of a pattern match: | :separate -> relay(...)"""
    pattern: Atom
    body: Body


@dataclass
class PatternMatch:
    """Pattern match block: | :separate -> ... | :mixin -> ... | :discard -> ..."""
    arms: list[PatternArm] = field(default_factory=list)


# ── Clauses ─────────────────────────────────────────────────────

@dataclass
class InnerClause:
    """A nested clause within a body: initial_state(sm, :invocation) -> body"""
    head: "Head"
    body: Optional[Union[Body, ParallelBody, PatternMatch]] = None


@dataclass
class Head:
    """Clause head: a term with optional parameter tuple."""
    term: Term
    params: Optional[tuple[Term, ...]] = None


@dataclass
class Annotation:
    """A Python-decorator-style annotation attached to a clause.

    Stripped by the provenance preprocessor and emitted as separate
    Prolog facts in the generated IR. The clause itself is unaffected;
    annotations are pure metadata.

    Examples:
      @cites(rfc9112, section("2.1"))
      @adopts(python_sdk_v1x, reasoning("endpoint URL convention"))
      @provenance(commit("cebddea5c"), derived_from([rfc9112, python_sdk_v1x]))
      @id(content_framing_absorption)   # optional stable clause ID
    """
    name: str                           # "cites", "adopts", "provenance", "id", ...
    args: tuple = ()                    # same shape as CompoundTerm args

    def __str__(self) -> str:
        if not self.args:
            return f"@{self.name}()"
        args_str = ", ".join(str(a) for a in self.args)
        return f"@{self.name}({args_str})"


@dataclass
class AnnotatedElement:
    """Wraps a body_element that carries prefix annotations.

    Used for nested annotations (annotations on statements inside a clause
    body, e.g., on a specific state() or on() in a state machine). The
    outer ``element`` is whatever the annotated body_element produced
    (Atom, CompoundTerm, InnerClause, Assignment, etc.). The ``annotations``
    tuple carries the prefix decorations.

    The preprocessor discovers these during body traversal and emits
    provenance facts with the nested clause ID derived from the enclosing
    clause and the functor of the element (see bpd_preprocess._assign_clause_ids).

    Distinct from the ``annotations`` field on ``Clause`` because that
    field applies to the top-level clause while this wraps nested body
    elements. Both mechanisms coexist; a BPD file may have both top-level
    and nested annotations.
    """
    annotations: tuple                  # tuple[Annotation, ...]
    element: Any                        # The wrapped body_element's AST node


@dataclass
class Clause:
    """A top-level clause.

    Forms:
      - Fact:       process(:client).
      - Horn rule:  actor(X) :- process(X).
      - Action:     gather_listen_endpoint(...) -> body.
      - Combined:   boundary(N, A, B) :- specific(N, A, B) -> body.

    Optional prefix annotations (see Annotation) carry provenance metadata.
    """
    head: Head
    implies_head: Optional[Head] = None  # The :- part (if present)
    body: Optional[Union[Body, ParallelBody, PatternMatch]] = None
    citation: Optional[int] = None  # «N» reference number (legacy marker, unused by grammar)
    annotations: tuple[Annotation, ...] = ()  # @cites(...), @adopts(...), etc.


# ── Directives ──────────────────────────────────────────────────

@dataclass
class Include:
    """!include directive."""
    path: str
    label: Optional[str] = None  # (references), (dimensions), (clops), etc.


# ── Program ─────────────────────────────────────────────────────

@dataclass
class Program:
    """A complete BPD file: directives + clauses."""
    directives: list[Include] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    source_file: Optional[str] = None
