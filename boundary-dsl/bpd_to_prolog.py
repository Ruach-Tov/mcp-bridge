"""BPD → Prolog IR Compiler — Phase 2

Compiles BPD AST nodes into SWI-Prolog facts and rules.
The Prolog IR is the canonical intermediate representation
from which verification queries, code generators, and
diagram renderers can operate.

Design decisions:
  - BPD surface syntax → AST (Phase 1) → Prolog IR (this file)
  - Separated surfaces: BPD is what humans read, Prolog is executable
  - Atoms become Prolog atoms (lowercase, no colon prefix)
  - Variables become Prolog variables (uppercase, preserved)
  - Compound terms become Prolog compound terms directly
  - Directives become :- directives or consult/1 calls
  - String literals become Prolog atoms (single-quoted)

Author: mavchin (Claude Opus 4.6), 2026-04-16
"""

from __future__ import annotations
from pathlib import Path
from typing import TextIO
import sys

from bpd_ast import (
    Atom, Variable, IntLiteral, StringLiteral,
    CompoundTerm, FieldAccess, TupleFieldAccess, ListTerm,
    InfixExpr, NotExpr, RangeExpr, SafeNavCall, Increment,
    BareName, TypedParam, TupleTerm,
    Assignment, Destructure,
    Body, ParallelBody, PatternArm, PatternMatch,
    Head, Clause, InnerClause, Include, Program,
    AnnotatedElement,
)


def term_to_prolog(term) -> str:
    """Convert a BPD AST term to Prolog syntax."""
    # AnnotatedElement wraps another AST node with prefix annotations.
    # Annotations are provenance metadata, not operational semantics —
    # they don't appear in the Prolog IR. Unwrap and compile the inner
    # element. The preprocessor handles the annotations separately,
    # emitting provenance facts in the .prov.pl companion file.
    if isinstance(term, AnnotatedElement):
        return term_to_prolog(term.element)

    if isinstance(term, Atom):
        # BPD :foo → Prolog foo (lowercase atom, unquoted)
        # BPD :Path → Prolog 'Path' (uppercase-initial, single-quoted to force atom)
        # Single-quoting preserves original case for round-trippability and readability.
        # Lowercasing would lose information (:Path vs :path would collapse).
        # ISO Prolog §6.4.2 supports single-quoted atoms natively.
        name = term.name
        # Prolog atoms with special chars need quoting
        if name.isidentifier() and name[0].islower():
            return name
        return f"'{name}'"

    elif isinstance(term, Variable):
        # BPD Variable → Prolog Variable (uppercase, same)
        return term.name

    elif isinstance(term, IntLiteral):
        return str(term.value)

    elif isinstance(term, StringLiteral):
        # Prolog single-quoted atom for strings
        escaped = term.value.replace("'", "\\'").replace("\n", "\\n")
        return f"'{escaped}'"

    elif isinstance(term, CompoundTerm):
        functor = term.functor
        if not term.args:
            return f"{functor}"
        args_str = ", ".join(term_to_prolog(a) for a in term.args)
        result = f"{functor}({args_str})"
        if term.extra_args:
            extra = ", ".join(term_to_prolog(a) for a in term.extra_args)
            result = f"{functor}({args_str}, extra_args({extra}))"
        return result

    elif isinstance(term, FieldAccess):
        base = term_to_prolog(term.base)
        return f"field({base}, {term.field})"

    elif isinstance(term, TupleFieldAccess):
        base = term_to_prolog(term.base)
        fields = ", ".join(term.fields)
        return f"fields({base}, [{fields}])"

    elif isinstance(term, ListTerm):
        elements = ", ".join(term_to_prolog(e) for e in term.elements)
        return f"[{elements}]"

    elif isinstance(term, InfixExpr):
        left = term_to_prolog(term.left)
        right = term_to_prolog(term.right)
        op = term.op
        if op == "==":
            return f"({left} == {right})"
        elif op == "or":
            return f"({left} ; {right})"
        elif op == "and":
            return f"({left} , {right})"
        return f"{op}({left}, {right})"

    elif isinstance(term, NotExpr):
        operand = term_to_prolog(term.operand)
        return f"\\+ {operand}"

    elif isinstance(term, RangeExpr):
        low = term_to_prolog(term.low)
        high = term_to_prolog(term.high)
        return f"range({low}, {high})"

    elif isinstance(term, SafeNavCall):
        base = term_to_prolog(term.base)
        args = ", ".join(term_to_prolog(a) for a in term.args)
        if args:
            return f"safe_call({base}, {term.method}, [{args}])"
        return f"safe_call({base}, {term.method})"

    elif isinstance(term, Increment):
        return f"increment({term_to_prolog(term.variable)})"

    elif isinstance(term, BareName):
        name = term.name
        if term.is_array:
            return f"array_type({name})"
        return name

    elif isinstance(term, TypedParam):
        type_name = term.type_name if isinstance(term.type_name, str) else term.type_name.name
        var = term_to_prolog(term.var)
        return f"typed({type_name}, {var})"

    elif isinstance(term, TupleTerm):
        elements = ", ".join(term_to_prolog(e) for e in term.elements)
        return f"tuple({elements})"

    elif isinstance(term, Assignment):
        target = term_to_prolog(term.target)
        value = term_to_prolog(term.value)
        return f"assign({target}, {value})"

    elif isinstance(term, Destructure):
        target = term_to_prolog(term.target)
        source = term_to_prolog(term.source)
        return f"destructure({target}, {source})"

    elif isinstance(term, PatternMatch):
        arms = ", ".join(
            f"arm({term_to_prolog(a.pattern)}, {body_to_prolog(a.body)})"
            for a in term.arms
        )
        return f"pattern_match([{arms}])"

    elif isinstance(term, InnerClause):
        head = head_to_prolog(term.head)
        if term.body:
            body = body_to_prolog(term.body)
            return f"inner_clause({head}, {body})"
        return f"inner_clause({head})"

    else:
        return f"unknown({type(term).__name__})"


def body_to_prolog(body) -> str:
    """Convert a body to Prolog."""
    if isinstance(body, Body):
        elements = [term_to_prolog(e) for e in body.elements]
        return ", ".join(elements) if elements else "true"

    elif isinstance(body, ParallelBody):
        branches = [body_to_prolog(b) for b in body.branches]
        return f"parallel([{', '.join(branches)}])"

    elif isinstance(body, PatternMatch):
        return term_to_prolog(body)

    return "true"


def head_to_prolog(head: Head) -> str:
    """Convert a clause head to Prolog."""
    result = term_to_prolog(head.term)
    if head.params:
        extra = ", ".join(term_to_prolog(p) for p in head.params)
        result = f"{result}, extra_params({extra})"
    return result


def clause_to_prolog(clause: Clause) -> str:
    """Convert a clause to a Prolog fact or rule.
    
    Four forms:
      (a) head :- implies_head, body.   (combined rule)
      (b) head :- body.                 (action rule, head -> body)
      (c) head.                         (fact, no body)
      (d) head :- implies_head.         (horn rule, head :- condition)
    """
    head = head_to_prolog(clause.head)

    if clause.implies_head and clause.body:
        # (a) Combined: head :- specific_head -> body
        implies = head_to_prolog(clause.implies_head)
        body = body_to_prolog(clause.body)
        return f"{head} :-\n    {implies},\n    {body}."

    elif clause.body:
        # (b) Action rule: head -> body
        body = body_to_prolog(clause.body)
        return f"{head} :-\n    {body}."

    elif clause.implies_head:
        # (d) Horn rule: head :- condition (e.g., actor(X) :- process(X))
        implies = head_to_prolog(clause.implies_head)
        return f"{head} :-\n    {implies}."

    else:
        # (c) Fact
        return f"{head}."


def program_to_prolog(program: Program, out: TextIO | None = None) -> str:
    """Compile a BPD Program AST to Prolog source text."""
    lines = []

    # Header
    lines.append(f"% BPD Prolog IR — generated from {program.source_file or 'unknown'}")
    lines.append(f"% {len(program.clauses)} clauses, {len(program.directives)} directives")
    lines.append("")

    # Directives → consult/1 calls
    for d in program.directives:
        label = f"  % {d.label}" if d.label else ""
        lines.append(f":- consult('{d.path}').{label}")

    if program.directives:
        lines.append("")

    # Clauses → Prolog facts and rules
    for clause in program.clauses:
        lines.append(clause_to_prolog(clause))
        lines.append("")

    result = "\n".join(lines)

    if out:
        out.write(result)

    return result


def compile_bpd_to_prolog(bpd_path: str | Path, prolog_path: str | Path | None = None) -> str:
    """Parse a BPD file and compile it to Prolog.

    Args:
        bpd_path: Path to the .bpd or .dsl file
        prolog_path: Optional output path for .pl file. If None, returns string only.

    Returns:
        The Prolog source text.
    """
    from bpd_parser import parse_bpd_file

    program = parse_bpd_file(bpd_path)
    prolog_text = program_to_prolog(program)

    if prolog_path:
        Path(prolog_path).write_text(prolog_text)

    return prolog_text


if __name__ == "__main__":
    if len(sys.argv) > 1:
        bpd_path = sys.argv[1]
        prolog_path = sys.argv[2] if len(sys.argv) > 2 else None
        result = compile_bpd_to_prolog(bpd_path, prolog_path)
        if not prolog_path:
            print(result)
    else:
        print("Usage: python bpd_to_prolog.py <file.bpd> [output.pl]")
