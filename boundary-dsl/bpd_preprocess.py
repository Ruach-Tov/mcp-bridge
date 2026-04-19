"""BPD Provenance Preprocessor.

Strips @cites/@adopts/@provenance/etc. annotations from a BPD source file
and emits them as separate Prolog facts in a companion .prov.pl file.
The stripped BPD (still annotation-free valid BPD) can then be fed to
the existing bpd_to_prolog.py compiler for the mechanistic IR.

Pipeline:

    foo.bpd              ——→ bpd_preprocess
                              ↓                ↓
                      foo.clean.bpd        foo.prov.pl
                          (vanilla        (provenance facts,
                           BPD)             queryable Prolog)
                              ↓
                      bpd_to_prolog (existing Phase 2)
                              ↓
                          foo.pl
                      (mechanistic IR)

Two outputs, both queryable. Truth Flow loads both. Humans who want to
read raw BPD get the clean file.

DESIGN NOTES

Clause identification — positional adjacency (Option A).
    Each annotated clause gets a synthetic stable ID of the form
        <file_stem>_<functor>_<N>
    where N is a per-functor counter incremented on each occurrence.
    This ID is deterministic given the file and serves as the Prolog
    atom that links annotations to their clauses. If the author uses
    @id(name), that name is used instead.

Vocabulary — open set with registry (Option: middle).
    Annotations of any name are accepted. The registry at
    prov_vocabulary.pl declares which are "blessed" and provides
    metadata (normative/conventional/internal categorization,
    optional PROV-O mapping). Unknown annotation kinds are emitted
    with a warning.

Output format — Prolog facts.
    Each annotation becomes a fact of the form:
        <annotation_name>(<clause_id>, <arg1>, <arg2>, ...).
    e.g.
        cites(mcp_bridge_absorb_1, rfc9112, section('2.1')).
        adopts(mcp_bridge_absorb_1, python_sdk_v1x).
    The clause ID is always the first argument. Additional args
    are the annotation's own arguments in order.

Author: metayen (Claude Opus 4.7), BPD provenance DSL Phase 1.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TextIO

from bpd_parser import parse_bpd_file
from bpd_ast import (
    Annotation, Clause, CompoundTerm, Program, Atom, Variable, StringLiteral,
    IntLiteral, BareName, ListTerm, Head, Body, ParallelBody, PatternMatch,
    InnerClause, AnnotatedElement, PatternArm,
)


@dataclass
class PreprocessResult:
    """Result of preprocessing one BPD file."""
    clean_bpd: str                              # BPD text with @-annotations stripped
    provenance_facts: str                       # Prolog facts for .prov.pl
    clause_ids: dict[int, str] = field(default_factory=dict)  # clause_index → stable_id
    warnings: list[str] = field(default_factory=list)


# ── Clause identification ────────────────────────────────────────────────

def _functor_of(clause: Clause) -> str:
    """Extract the head functor name for synthetic ID generation."""
    term = clause.head.term
    if isinstance(term, CompoundTerm):
        return term.functor
    if isinstance(term, Atom):
        return term.name
    if isinstance(term, Variable):
        return "var_" + term.name
    if isinstance(term, BareName):
        return term.name
    return "unknown"


def _explicit_id(clause: Clause) -> Optional[str]:
    """If the clause has an @id(name) annotation, return its name."""
    for ann in clause.annotations:
        if ann.name == "id" and len(ann.args) == 1:
            arg = ann.args[0]
            if isinstance(arg, (Atom, BareName)):
                return arg.name
            if isinstance(arg, Variable):
                return arg.name.lower()
    return None


def _functor_of_element(element) -> str:
    """Extract the functor name from a body_element's underlying AST node.

    Parallels _functor_of but operates on nested body_elements (the things
    that appear inside a clause body, like state(...), on(...), absorb(...),
    or an inner_clause(head -> body)).

    Returns "unknown" if the element type is not recognized as carrying
    a functor — this should surface as a visible nested ID like
    "parent__unknown_1" that flags a missed case for investigation.
    """
    # If the element is an InnerClause, its functor is the functor of its head
    if isinstance(element, InnerClause):
        return _functor_of_head_term(element.head.term)
    # If it's a bare compound term (most common case for state/on/transition)
    if isinstance(element, CompoundTerm):
        return element.functor
    if isinstance(element, Atom):
        return element.name
    if isinstance(element, BareName):
        return element.name
    if isinstance(element, Variable):
        return "var_" + element.name
    return "unknown"


def _element_summary(element) -> str:
    """Return a short string summary of a body element for comments
    in .prov.pl output. Truncates long elements."""
    if isinstance(element, InnerClause):
        head_str = str(element.head.term) if element.head else "?"
        return f"{head_str} -> ..."
    s = str(element)
    if len(s) > 80:
        return s[:77] + "..."
    return s


def _functor_of_head_term(term) -> str:
    """Same as _functor_of but for a raw term (used on Head.term)."""
    if isinstance(term, CompoundTerm):
        return term.functor
    if isinstance(term, Atom):
        return term.name
    if isinstance(term, BareName):
        return term.name
    if isinstance(term, Variable):
        return "var_" + term.name
    return "unknown"


def _explicit_id_of_element(ann_elem: AnnotatedElement) -> Optional[str]:
    """If a nested AnnotatedElement has an @id(name) annotation, extract
    the explicit name override. Otherwise returns None."""
    for ann in ann_elem.annotations:
        if ann.name == "id" and len(ann.args) == 1:
            arg = ann.args[0]
            if isinstance(arg, (Atom, BareName)):
                return arg.name
            if isinstance(arg, Variable):
                return arg.name.lower()
    return None


def _walk_annotated_elements(body) -> list[AnnotatedElement]:
    """Walk a clause body (Body, ParallelBody, or PatternMatch) and return
    all AnnotatedElement nodes found, in depth-first left-to-right order.

    Recursive for nested bodies:
      - Body.elements may contain InnerClause, which itself has a body
      - ParallelBody.branches each has its own body
      - PatternMatch.arms each has a body_element that may be an InnerClause
      - AnnotatedElement wrapping an InnerClause: the element itself is an
        AnnotatedElement (yield it) AND its wrapped InnerClause's body may
        contain more AnnotatedElements (recurse into it)

    The order is important for deterministic clause ID generation: nested
    IDs use a per-functor counter, so the order elements are visited
    determines which gets counter=1 and which gets counter=2, etc.
    """
    results: list[AnnotatedElement] = []

    def visit_body(b):
        if b is None:
            return
        if isinstance(b, Body):
            for el in b.elements:
                visit_element(el)
        elif isinstance(b, ParallelBody):
            for branch in b.branches:
                visit_body(branch)
        elif isinstance(b, PatternMatch):
            for arm in b.arms:
                if isinstance(arm, PatternArm):
                    visit_body(arm.body)

    def visit_element(el):
        if isinstance(el, AnnotatedElement):
            results.append(el)
            # Also descend into the wrapped element's body, if it has one
            inner = el.element
            if isinstance(inner, InnerClause):
                visit_body(inner.body)
        elif isinstance(el, InnerClause):
            # Unwrapped inner clause — descend into its body
            visit_body(el.body)

    visit_body(body)
    return results


def _assign_clause_ids(program: Program, file_stem: str) -> dict[int, str]:
    """Assign stable IDs to every annotated clause.

    Uses @id(name) when present; otherwise generates
    <file_stem>_<functor>_<N> where N is a per-functor counter.

    Unannotated clauses get no ID (not returned) since they have no
    provenance to identify.

    Note: only top-level clause IDs are returned here. Nested-annotation
    IDs are computed separately by _assign_nested_ids() because they
    need the parent clause ID as their prefix, and because a clause may
    have nested annotations even without top-level ones.
    """
    ids: dict[int, str] = {}
    counters: Counter[str] = Counter()

    for i, clause in enumerate(program.clauses):
        # A clause needs an ID if it has top-level annotations OR contains
        # nested annotations in its body. Without either it has no provenance
        # to identify.
        nested = _walk_annotated_elements(clause.body) if clause.body else []
        if not clause.annotations and not nested:
            continue
        explicit = _explicit_id(clause)
        if explicit:
            ids[i] = explicit
            continue
        functor = _functor_of(clause)
        counters[functor] += 1
        ids[i] = f"{file_stem}_{functor}_{counters[functor]}"

    return ids


def _assign_nested_ids(
    program: Program,
    top_level_ids: dict[int, str],
) -> dict[tuple[int, int], str]:
    """Assign stable IDs to every nested AnnotatedElement.

    Returns a dict keyed by (clause_index, nested_index) where nested_index
    is the element's position in the depth-first walk of the clause body
    (matching _walk_annotated_elements order). The value is the nested
    clause ID of the form <parent_id>__<inner_functor>_<N>.

    @id(name) annotations on nested elements override the synthetic naming,
    producing <parent_id>__<explicit_name> — the parent-prefix is preserved
    to avoid cross-clause ID collisions even with explicit names.
    """
    nested_ids: dict[tuple[int, int], str] = {}

    for clause_idx, clause in enumerate(program.clauses):
        if clause.body is None:
            continue
        nested_elements = _walk_annotated_elements(clause.body)
        if not nested_elements:
            continue
        if clause_idx not in top_level_ids:
            # Should not happen: _assign_clause_ids should have assigned
            # an ID if nested annotations exist. Defensive check.
            continue
        parent_id = top_level_ids[clause_idx]

        # Per-functor counter within this clause (reset per-parent)
        counters: Counter[str] = Counter()
        for nested_idx, ann_elem in enumerate(nested_elements):
            explicit = _explicit_id_of_element(ann_elem)
            if explicit:
                nested_ids[(clause_idx, nested_idx)] = f"{parent_id}__{explicit}"
                continue
            functor = _functor_of_element(ann_elem.element)
            counters[functor] += 1
            nested_ids[(clause_idx, nested_idx)] = (
                f"{parent_id}__{functor}_{counters[functor]}"
            )

    return nested_ids


# ── Term → Prolog serialization (minimal, for annotation args) ───────────

def _term_to_prolog(term) -> str:
    """Serialize a BPD AST term into Prolog-readable source.

    This is a minimal form for annotation arguments. It does NOT handle
    every BPD term shape — annotations typically contain atoms, strings,
    numbers, lists, and compound terms with reasoning() / commit() /
    section() functors. If a term shape surfaces that isn't handled,
    we emit 'unknown(<type_name>)' so the problem is visible rather
    than silent.
    """
    if isinstance(term, Atom):
        # Match bpd_to_prolog atom-mapping convention: lowercase atoms
        # unquoted, uppercase-initial atoms single-quoted.
        name = term.name
        if name and name[0].islower() and all(c.isalnum() or c == "_" for c in name):
            return name
        return f"'{name}'"
    if isinstance(term, BareName):
        # Bare lowercase identifiers — output as-is
        return term.name
    if isinstance(term, Variable):
        return term.name
    if isinstance(term, IntLiteral):
        return str(term.value)
    if isinstance(term, StringLiteral):
        # Escape single quotes in string content
        escaped = term.value.replace("'", "\\'")
        return f"'{escaped}'"
    if isinstance(term, ListTerm):
        parts = ", ".join(_term_to_prolog(e) for e in term.elements)
        return f"[{parts}]"
    if isinstance(term, CompoundTerm):
        args = ", ".join(_term_to_prolog(a) for a in term.args)
        # Functor follows same casing convention as atoms
        functor = term.functor
        if functor and functor[0].islower() and all(c.isalnum() or c == "_" for c in functor):
            return f"{functor}({args})"
        return f"'{functor}'({args})"
    # Fallback — visible leak for future debugging
    return f"unknown_{type(term).__name__}"


# ── Annotation → provenance Prolog fact ──────────────────────────────────

def _annotation_to_fact(clause_id: str, ann: Annotation) -> str:
    """Convert one annotation into a Prolog fact string.

    Normalized form:  <name>(<ClauseID>, <Source>, <Extras>).
    where:
        ClauseID — the stable identifier for the annotated clause
        Source   — the annotation's first argument (primary reference target),
                   or the atom `none` if the annotation took no arguments
        Extras   — a Prolog list of remaining arguments (may be empty [])

    This fixed-arity shape is endorsed by mavchin (2026-04-17) to enable
    uniform queries across all annotation kinds: findall(C, cites(C, S, _), ...)
    returns every clause that cites anything, regardless of how many
    decorating sub-terms (section, reasoning, etc.) the annotation carried.

    The alternative (variable arity: cites/2, cites/3, cites/4, ...) made
    findall-style queries miss annotations with different sub-term counts,
    and every consumer of the provenance facts had to know all arities
    in advance. List-based Extras trades one extra character for that
    entire class of query bugs.

    Skips @id annotations — those set the clause_id itself and do not
    emit a fact.
    """
    if ann.name == "id":
        return ""  # @id sets the clause's ID; it's not a provenance fact

    if not ann.args:
        # Zero-arg annotation: Source = none, Extras = []
        return f"{ann.name}({clause_id}, none, [])."

    source = _term_to_prolog(ann.args[0])
    extras_list = ann.args[1:]
    if not extras_list:
        return f"{ann.name}({clause_id}, {source}, [])."
    extras_str = ", ".join(_term_to_prolog(e) for e in extras_list)
    return f"{ann.name}({clause_id}, {source}, [{extras_str}])."


# ── Clean BPD emission (re-serialize without annotations) ────────────────

# We don't reconstruct from the AST — we strip @-annotations from the source
# text. Full AST → BPD re-serialization is a larger project. The strip
# approach preserves whitespace, comments, and everything non-annotation
# exactly as authored.

_ANNOTATION_LINE_RE = re.compile(r"^\s*@\w+\s*\([^)]*\)\s*\n", re.MULTILINE)


def _strip_annotations(source: str) -> str:
    """Remove @-annotation lines from BPD source text.

    Handles single-line annotations of the form:
        @name(args)

    Multi-line annotations (parenthesized content spanning lines) are
    handled via balanced-paren scanning rather than regex.
    """
    out: list[str] = []
    lines = source.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("@"):
            # Scan forward for balanced parens to handle multi-line annotations
            paren_depth = 0
            found_open = False
            j = i
            while j < len(lines):
                for ch in lines[j]:
                    if ch == "(":
                        paren_depth += 1
                        found_open = True
                    elif ch == ")":
                        paren_depth -= 1
                if found_open and paren_depth == 0:
                    # Reached end of this annotation
                    i = j + 1
                    break
                j += 1
            else:
                # Malformed — unbalanced parens. Fall back to one-line strip.
                i += 1
        else:
            out.append(line)
            i += 1
    return "".join(out)


# ── Main preprocess function ─────────────────────────────────────────────

def preprocess(source: str, file_stem: str = "source") -> PreprocessResult:
    """Preprocess BPD source: extract annotations into provenance facts,
    emit clean BPD text.

    Parameters
    ----------
    source : str
        BPD source text (with or without @-annotations).
    file_stem : str
        Short identifier for the source file (used in synthetic clause IDs).
        Usually the file name without extension, e.g., "mcp_bridge_tier2".

    Returns
    -------
    PreprocessResult with fields:
        clean_bpd — BPD text with @-annotation lines removed
        provenance_facts — Prolog facts (one per annotation), ready to
                           be written to <file_stem>.prov.pl
        clause_ids — mapping clause_index → stable ID
        warnings — any issues encountered (unknown vocabulary, etc.)
    """
    # Parse the annotated source to identify clauses with annotations
    from bpd_parser import parse_bpd
    program = parse_bpd(source, source_file=file_stem)

    # Assign IDs to annotated clauses (top-level) and nested AnnotatedElements
    clause_ids = _assign_clause_ids(program, file_stem)
    nested_ids = _assign_nested_ids(program, clause_ids)

    # Emit provenance facts
    fact_lines: list[str] = []
    fact_lines.append(f"% Provenance facts extracted from {file_stem}")
    fact_lines.append(f"% Generated by bpd_preprocess.py")
    fact_lines.append(f"%")
    fact_lines.append(f"% Fact shape: <annotation_name>(<ClauseID>, <Source>, <Extras>).")
    fact_lines.append(f"%   ClauseID — stable identifier for the annotated clause")
    fact_lines.append(f"%   Source   — annotation's primary argument (or `none` if 0-arg)")
    fact_lines.append(f"%   Extras   — Prolog list of decorating sub-terms (may be [])")
    fact_lines.append(f"%")
    fact_lines.append(f"% Uniform 3-arity enables findall(C, cites(C, S, _), Cs) across")
    fact_lines.append(f"% all annotations regardless of decoration count.")
    fact_lines.append(f"%")
    fact_lines.append(f"% Nested clause IDs use <parent_id>__<inner_functor>_<N> format")
    fact_lines.append(f"% (double underscore separator makes the parent/nested boundary")
    fact_lines.append(f"% visible even for deeply-nested specs).")
    fact_lines.append("")

    warnings: list[str] = []
    for i, clause in enumerate(program.clauses):
        nested_elements = _walk_annotated_elements(clause.body) if clause.body else []
        # Skip clauses with neither top-level nor nested annotations
        if not clause.annotations and not nested_elements:
            continue

        cid = clause_ids[i]
        # Comment line showing which clause the annotations belong to
        head_str = str(clause.head.term)
        if len(head_str) > 60:
            head_str = head_str[:57] + "..."
        fact_lines.append(f"% clause_id={cid} :: {head_str}")

        # Top-level annotations
        for ann in clause.annotations:
            fact = _annotation_to_fact(cid, ann)
            if fact:
                fact_lines.append(fact)

        # Nested annotations — emit with their nested IDs
        for nested_idx, ann_elem in enumerate(nested_elements):
            nid = nested_ids[(i, nested_idx)]
            # Short comment describing the nested element
            inner = ann_elem.element
            inner_str = _element_summary(inner)
            fact_lines.append(f"%   nested: {nid} :: {inner_str}")
            for ann in ann_elem.annotations:
                fact = _annotation_to_fact(nid, ann)
                if fact:
                    fact_lines.append(fact)
        fact_lines.append("")

    provenance_facts = "\n".join(fact_lines)

    # Strip annotations from source to produce clean BPD
    clean_bpd = _strip_annotations(source)

    return PreprocessResult(
        clean_bpd=clean_bpd,
        provenance_facts=provenance_facts,
        clause_ids=clause_ids,
        warnings=warnings,
    )


def preprocess_file(path: Path) -> PreprocessResult:
    """Preprocess a BPD file on disk. Same as preprocess() but reads the file."""
    source = Path(path).read_text()
    file_stem = Path(path).stem
    return preprocess(source, file_stem)


# ── CLI ──────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print("Usage: bpd_preprocess.py <file.bpd> [--out-dir DIR]")
        print()
        print("Strips @cites/@adopts/@provenance annotations from a BPD file,")
        print("emits them as Prolog facts in <stem>.prov.pl, and writes a")
        print("clean vanilla-BPD version to <stem>.clean.bpd.")
        return 1

    src_path = Path(argv[1])
    out_dir = Path(argv[3]) if len(argv) > 3 and argv[2] == "--out-dir" else src_path.parent

    result = preprocess_file(src_path)

    clean_path = out_dir / f"{src_path.stem}.clean.bpd"
    prov_path = out_dir / f"{src_path.stem}.prov.pl"

    clean_path.write_text(result.clean_bpd)
    prov_path.write_text(result.provenance_facts)

    print(f"Wrote {clean_path} ({len(result.clean_bpd)} bytes, "
          f"{len(result.clean_bpd.splitlines())} lines)")
    print(f"Wrote {prov_path} ({len(result.provenance_facts)} bytes, "
          f"{sum(1 for _ in result.clause_ids)} annotated clauses)")
    for w in result.warnings:
        print(f"  WARNING: {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
