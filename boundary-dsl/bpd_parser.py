"""BPD Tier II Parser — Lark grammar → typed AST.

Usage:
    from bpd_parser import parse_bpd, parse_bpd_file

    program = parse_bpd_file("mcp_bridge_tier2.bpd")
    for clause in program.clauses:
        print(clause.head)

Author: mavchin (Claude Opus 4.6), 2026-04-16
"""

from pathlib import Path
from lark import Lark, Transformer, Token, v_args
from bpd_ast import (
    Atom, Variable, IntLiteral, StringLiteral,
    CompoundTerm, FieldAccess, TupleFieldAccess, ListTerm,
    InfixExpr, NotExpr, RangeExpr, SafeNavCall, Increment,
    BareName, TypedParam, TupleTerm,
    Assignment, Destructure,
    Body, ParallelBody, PatternArm, PatternMatch,
    Head, Clause, InnerClause, Include, Program, Annotation,
    AnnotatedElement,
)

_GRAMMAR_PATH = Path(__file__).parent / "bpd.lark"


def _drop_tokens(items):
    """Drop bare Lark Token objects from an items list.

    In Lark grammars that mention named terminals in a rule body (like
    ``assignment: atom ASSIGN term``), the named terminals appear as
    Token objects in the transformer's ``items`` argument. These tokens
    are structural (operators, separators) and should not appear in the
    AST. Historically, transformer methods that used positional access
    (``items[1]``) on unfiltered items leaked these Tokens into AST
    node fields, where they subsequently leaked into the Prolog IR as
    ``unknown(Token)``.

    This helper filters them out uniformly. Use in any transformer
    method where the grammar rule includes a named terminal between
    the payload elements.
    """
    return [i for i in items if not isinstance(i, Token)]


class BPDTransformer(Transformer):
    """Transform Lark parse tree into typed BPD AST nodes."""

    # ── Atoms and Variables ─────────────────────────────────

    def atom(self, items):
        return items[0]

    def ATOM(self, token):
        return Atom(str(token)[1:])  # strip leading ":"

    def ATOM_ZERO(self, token):
        return Atom("0")

    def ATOM_ANON(self, token):
        return Atom("_")

    def VARIABLE(self, token):
        return Variable(str(token))

    def NAME(self, token):
        return str(token)

    # ── Literals ────────────────────────────────────────────

    def INT(self, token):
        return IntLiteral(int(token))

    def STRING(self, token):
        return StringLiteral(str(token)[1:-1])  # strip quotes

    def literal(self, items):
        return items[0]

    # ── Terms ───────────────────────────────────────────────

    def term(self, items):
        return items[0]

    def compound_term(self, items):
        # Pass-through: compound_term -> compound_term_single | compound_term_double
        # Both sub-rules already produce a CompoundTerm.
        return items[0]

    def compound_term_single(self, items):
        # items: [functor, arg_list?] where functor is either a str (NAME) or an Atom
        functor = str(items[0]) if isinstance(items[0], str) else items[0].name
        args = items[1] if len(items) > 1 and isinstance(items[1], list) else ()
        return CompoundTerm(
            functor=functor,
            args=tuple(args) if isinstance(args, list) else args,
            extra_args=None,
        )

    def compound_term_double(self, items):
        # items: [functor, arg_list_1?, arg_list_2?] — second tuple is extra_args
        functor = str(items[0]) if isinstance(items[0], str) else items[0].name
        # Split arg lists: if we have 3 items, both arg lists are present;
        # if 2 items, one is missing and we need to check which.
        lists = [i for i in items[1:] if isinstance(i, list)]
        args = tuple(lists[0]) if lists else ()
        extra_args = tuple(lists[1]) if len(lists) > 1 else ()
        return CompoundTerm(
            functor=functor,
            args=args,
            extra_args=extra_args,
        )

    def arg_list(self, items):
        return list(items)

    def arg(self, items):
        return items[0]

    def field_access(self, items):
        base = items[0]
        field_name = str(items[1])
        return FieldAccess(base, field_name)

    def name_list(self, items):
        return [str(i) for i in items]

    def list_term(self, items):
        elements = items[0] if items and isinstance(items[0], list) else []
        return ListTerm(tuple(elements))

    def infix_expr(self, items):
        return InfixExpr(items[0], str(items[1]), items[2])

    def not_expr(self, items):
        return NotExpr(items[0])

    def range_expr(self, items):
        # Grammar: range_expr: term RANGE_OP term
        # Lark produces items = [term1, Token(RANGE_OP, '..'), term2].
        # We want RangeExpr(low=term1, high=term2) — skip the operator token.
        # (Earlier versions of this method grabbed items[1], which was the
        # RANGE_OP token, producing RangeExpr(high=Token) and leaking into
        # the Prolog IR as "unknown(Token)".)
        return RangeExpr(low=items[0], high=items[2])

    def safe_nav_call(self, items):
        # Grammar: safe_nav_call: (atom | VARIABLE | NAME) "?." NAME "(" arg_list? ")"
        # The base may be an Atom, a Variable, or a bare str (from the NAME
        # terminal callback at line 67 converting Token -> str). If it's a
        # bare str, wrap it as BareName so the compiler knows how to render
        # it; otherwise the compiler emits "unknown(str)".
        base = items[0]
        if isinstance(base, str):
            base = BareName(name=base)
        method = str(items[1])
        args = items[2] if len(items) > 2 and isinstance(items[2], list) else ()
        return SafeNavCall(base, method, tuple(args) if isinstance(args, list) else args)

    def increment(self, items):
        return Increment(items[0])

    # ── New constructs (from metayen review) ────────────────

    def bare_name(self, items):
        name = str(items[0])
        is_array = len(items) > 1  # "[]" matched
        return BareName(name=name, is_array=is_array)

    def string_concat(self, items):
        return StringLiteral("".join(s.value for s in items))

    def typed_param(self, items):
        return TypedParam(type_name=str(items[0].name if hasattr(items[0], 'name') else items[0]),
                          var=items[1])

    def tuple_term(self, items):
        return TupleTerm(tuple(items))

    # (double_params method removed — the old head-level double_params? rule
    # has been replaced by a compound_term_double grammar branch that puts
    # the second tuple into CompoundTerm.extra_args directly.)

    # ── Assignment and Destructure ──────────────────────────

    def assignment(self, items):
        # Grammar: assignment: atom ASSIGN term
        # Lark produces items = [atom, Token('ASSIGN', ':='), term].
        # Filter out the operator Token before positional access, else
        # the Token leaks into Assignment.value and surfaces in the
        # Prolog IR as "unknown(Token)".
        payload = _drop_tokens(items)
        return Assignment(payload[0], payload[1])

    def destructure(self, items):
        # Grammar: destructure: (field_access | atom) DESTRUCTURE term
        # Same Token-leak pattern as assignment: DESTRUCTURE is a named
        # terminal, so it appears in items unless filtered.
        payload = _drop_tokens(items)
        return Destructure(payload[0], payload[1])

    # ── Body ────────────────────────────────────────────────

    def body(self, items):
        # Filter out None entries from body_sep. body_sep returns None
        # because separators are structural, not semantic — but the raw
        # None values leak into Body.elements if not filtered here, and
        # term_to_prolog(None) produces "unknown(NoneType)" in the IR.
        elements = [i for i in items if i is not None]
        if len(elements) == 1 and isinstance(elements[0], (ParallelBody, PatternMatch)):
            return elements[0]
        return Body(elements)

    def body_element(self, items):
        # Grammar: body_element: annotation* (assignment | increment | term
        #                                     | inner_clause | pattern_match_body)
        # With no annotations: items = [inner_element].
        # With annotations:    items = [Annotation, Annotation, ..., inner_element].
        # Wrap the inner element in AnnotatedElement if annotations are present;
        # otherwise pass through unchanged to preserve backward compatibility
        # for the (vast majority of) body_elements without annotations.
        annotations = tuple(i for i in items if isinstance(i, Annotation))
        non_annotations = [i for i in items if not isinstance(i, Annotation)]
        if not non_annotations:
            # Should not happen — a body_element must have exactly one inner
            # element. If it does, that's a parse-tree malformation; raise
            # rather than produce silent garbage.
            raise ValueError(
                f"body_element with only annotations, no inner element: {items!r}"
            )
        inner = non_annotations[0]
        if annotations:
            return AnnotatedElement(annotations=annotations, element=inner)
        return inner

    def body_sep(self, items):
        return None  # separators are structural, not semantic; filtered out in body()

    def parallel_body(self, items):
        branches = [Body([item]) if not isinstance(item, Body) else item for item in items]
        return ParallelBody(branches)

    def pattern_match_body(self, items):
        return PatternMatch(list(items))

    def pattern_arm(self, items):
        # Grammar: pattern_arm: "|" atom ARROW body_element
        # Lark produces items = [atom, Token('ARROW', '->'), body_element].
        # Filter out the operator Token before positional access, else
        # the Token leaks into the PatternArm body and surfaces in the
        # Prolog IR as "arm(pattern, unknown(Token))".
        payload = _drop_tokens(items)
        return PatternArm(payload[0], Body([payload[1]]) if not isinstance(payload[1], Body) else payload[1])

    def inner_clause(self, items):
        # Grammar: inner_clause: head ARROW body "."
        # After filtering out the ARROW token: items = [head, body]
        # (Lark includes ARROW as a token in items because it's a named terminal.)
        filtered = [i for i in items if not (isinstance(i, str) and i in ("->", ":-"))]
        head = filtered[0]
        body = filtered[1] if len(filtered) > 1 else None
        return InnerClause(head, body)

    # ── Head and Clause ─────────────────────────────────────

    def head(self, items):
        # Grammar: head: compound_term | atom | VARIABLE
        # The double-params case is now inside compound_term as extra_args,
        # so `items` always has exactly one element and no separate params.
        return Head(term=items[0], params=None)

    def annotation(self, items):
        # Grammar: annotation: "@" NAME "(" arg_list? ")"
        # items: [NAME, arg_list?] — arg_list (if present) is a list.
        name = str(items[0])
        args = ()
        if len(items) > 1 and isinstance(items[1], list):
            args = tuple(items[1])
        return Annotation(name=name, args=args)

    def clause(self, items):
        # Grammar: clause: annotation* head clause_body? "."
        # Items may begin with zero or more Annotation objects, followed
        # by a Head, optionally followed by a clause_body result (list).
        annotations = []
        head = None
        implies_head = None
        body = None
        for item in items:
            if isinstance(item, Annotation):
                annotations.append(item)
            elif isinstance(item, Head) and head is None:
                head = item
            elif isinstance(item, Head):
                # Second Head → the :- inner head (from clause_body)
                implies_head = item
            elif isinstance(item, list):
                # clause_body returns a list of AST nodes
                for sub in item:
                    if isinstance(sub, Head):
                        implies_head = sub
                    elif isinstance(sub, (Body, ParallelBody, PatternMatch)):
                        body = sub
            elif isinstance(item, (Body, ParallelBody, PatternMatch)):
                body = item
        return Clause(
            head=head,
            implies_head=implies_head,
            body=body,
            annotations=tuple(annotations),
        )

    def clause_body(self, items):
        # Filter out IMPLIES and ARROW Token objects, keep AST nodes
        from lark import Token
        results = [i for i in items if not isinstance(i, Token)]
        return results

    # ── Directives ──────────────────────────────────────────

    def directive(self, items):
        label = None
        path = None
        for item in items:
            if isinstance(item, str) and "/" in item or "." in item:
                path = item
            elif isinstance(item, str):
                label = item
        return Include(path=str(path) if path else str(items[-1]), label=label)

    def include_label(self, items):
        return str(items[0])

    def FILEPATH(self, token):
        return str(token)

    # ── Program ─────────────────────────────────────────────

    def start(self, items):
        directives = [i for i in items if isinstance(i, Include)]
        clauses = [i for i in items if isinstance(i, Clause)]
        return Program(directives=directives, clauses=clauses)


def parse_bpd(text: str, source_file: str | None = None,
              ambiguity: str = "resolve") -> Program:
    """Parse BPD text into a typed AST.

    By default, uses ambiguity="resolve" — Lark picks the highest-priority
    valid parse for any ambiguity, producing a single clean tree. Rule
    priorities in bpd.lark (e.g. clause_body.2) guide this resolution.

    Pass ambiguity="explicit" to surface remaining ambiguities as _ambig
    nodes in the tree — useful for grammar auditing.
    """
    grammar_text = _GRAMMAR_PATH.read_text()
    parser = Lark(grammar_text, parser="earley", ambiguity=ambiguity)
    tree = parser.parse(text)
    program = BPDTransformer().transform(tree)
    if source_file:
        program.source_file = source_file
    return program


def parse_bpd_file(path: str | Path) -> Program:
    """Parse a BPD file into a typed AST."""
    p = Path(path)
    text = p.read_text()
    return parse_bpd(text, source_file=str(p))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        prog = parse_bpd_file(sys.argv[1])
        print(f"Parsed {prog.source_file}:")
        print(f"  {len(prog.directives)} directives")
        print(f"  {len(prog.clauses)} clauses")
        for c in prog.clauses:
            print(f"    {c.head}")
    else:
        print("Usage: python bpd_parser.py <file.bpd>")
