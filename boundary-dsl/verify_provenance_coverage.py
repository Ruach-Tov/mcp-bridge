"""Provenance coverage verification tool.

Standing tool for iterating on BPD provenance annotations. Given a BPD
file (and optionally its .refs companion), reports:

  1. Annotation coverage: what fraction of clauses have at least one
     @cites / @adopts / @provenance / @mimics / ... annotation?

  2. Syntax validity: does the BPD file with its annotations still
     parse? (Catches malformed annotation syntax early.)

  3. Emission fidelity: does every annotation in the BPD produce a
     corresponding fact in the .prov.pl output? A silent drop here
     indicates a parser/preprocessor mismatch — every annotation
     should round-trip.

  4. Kind distribution: breakdown of annotation kinds by count, for
     a quick "what style of sources are we citing" summary.

  5. Authority distribution: normative vs conventional vs internal
     vs meta — tells us whether we're leaning on external authority
     or our own reasoning.

  6. Unmotivated clauses: clauses with no annotations at all. The
     target list for the next annotation pass.

USAGE

  python3 verify_provenance_coverage.py <path/to/file.bpd>

Writes a report to stdout suitable for inclusion in a review message.
Designed for iteration: run after every annotation batch, read the
delta, decide what to annotate next.

AUTHOR

  metayen (Claude Opus 4.7), 2026-04-18.
  Built for the mcp_bridge_tier2.bpd provenance annotation sprint
  with mavchin.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

# Allow running from the boundary_dsl directory
sys.path.insert(0, str(Path(__file__).parent))

from bpd_parser import parse_bpd_file
from bpd_preprocess import preprocess_file, _walk_annotated_elements


def _clause_id_for_report(clause, idx: int, stem: str) -> str:
    """Best-effort display name for a clause. Uses explicit @id if present,
    otherwise a synthetic <stem>_<functor>_<idx> name matching what the
    preprocessor would emit."""
    for ann in clause.annotations:
        if ann.name == "id" and ann.args:
            val = ann.args[0]
            if isinstance(val, str):
                return val
            return str(val)

    # Synthetic name: <stem>_<functor>_<N>
    head = clause.head
    if head is None:
        return f"{stem}_unknown_{idx}"

    term = head.term
    functor = getattr(term, "functor", None) or getattr(term, "name", None) or "unknown"
    return f"{stem}_{functor}_{idx}"


def _authority_category(kind: str) -> str:
    """Map annotation kind to authority category for summary statistics.

    Mirrors the classification in prov_vocabulary.pl and the Truth Flow
    adapter's _KIND_TO_AUTHORITY table.
    """
    if kind == "cites":
        return "normative"
    if kind in ("adopts", "mimics", "reverse_engineered_from"):
        return "conventional"
    if kind in ("provenance", "refines", "supersedes", "conflicts_with"):
        return "internal"
    if kind == "id":
        return "meta"
    return "unknown"


def report_coverage(bpd_path: str) -> dict:
    """Compute provenance coverage stats for a BPD file.

    Returns a dict with all the report fields, and ALSO prints a
    human-readable summary to stdout.
    """
    path = Path(bpd_path)
    stem = path.stem

    # Parse the full file. If the grammar rejects annotations at all,
    # this raises — that's the syntax check.
    try:
        program = parse_bpd_file(path)
    except Exception as e:
        print(f"SYNTAX ERROR in {bpd_path}: {type(e).__name__}: {e}")
        return {"error": "syntax", "detail": str(e)}

    # Run the preprocessor to see what facts WOULD be emitted
    try:
        result = preprocess_file(path)
    except Exception as e:
        print(f"PREPROCESS ERROR in {bpd_path}: {type(e).__name__}: {e}")
        return {"error": "preprocess", "detail": str(e)}

    # Count clauses and annotations.
    # Distinguish top-level (on Clause.annotations) from nested (on
    # AnnotatedElement wrappers inside clause bodies). Both contribute
    # to fact count; both deserve to be visible separately because
    # they answer different questions:
    #   top-level coverage = "how many top-level constructs cite sources?"
    #   nested coverage    = "how many inner state machine clauses cite sources?"
    total_clauses = len(program.clauses)
    annotated_clauses = 0
    top_level_annotations = 0
    nested_annotations = 0
    nested_annotated_elements = 0  # distinct inner elements with at least one annotation
    kind_counts: Counter = Counter()       # top-level + nested combined
    top_kind_counts: Counter = Counter()   # top-level only
    nested_kind_counts: Counter = Counter()  # nested only
    category_counts: Counter = Counter()
    unmotivated: list[str] = []

    for idx, clause in enumerate(program.clauses):
        # Top-level annotations on this clause
        clause_has_non_meta = False
        if clause.annotations:
            annotated_clauses += 1
            for ann in clause.annotations:
                top_level_annotations += 1
                kind_counts[ann.name] += 1
                top_kind_counts[ann.name] += 1
                category = _authority_category(ann.name)
                category_counts[category] += 1
                if category != "meta":
                    clause_has_non_meta = True

        # Nested annotations inside this clause's body
        nested_in_this_clause = (
            _walk_annotated_elements(clause.body) if clause.body else []
        )
        for ann_elem in nested_in_this_clause:
            nested_annotated_elements += 1
            for ann in ann_elem.annotations:
                nested_annotations += 1
                kind_counts[ann.name] += 1
                nested_kind_counts[ann.name] += 1
                category = _authority_category(ann.name)
                category_counts[category] += 1
                if category != "meta":
                    clause_has_non_meta = True

        # Track unmotivated: clause has no provenance-bearing annotation
        # at any level (top-level or nested).
        if not clause_has_non_meta:
            unmotivated.append(_clause_id_for_report(clause, idx, stem))

    total_annotations = top_level_annotations + nested_annotations

    # Count prov.pl facts emitted (for fidelity check)
    # Parse the output facts by splitting on ). or \n — simple heuristic
    fact_lines = [
        ln for ln in result.provenance_facts.split("\n")
        if ln.strip() and not ln.lstrip().startswith("%")
    ]
    facts_emitted = len([ln for ln in fact_lines if ln.rstrip().endswith(").")])

    # Expected emission: total annotations minus @id (meta) entries
    meta_count = kind_counts.get("id", 0)
    expected_facts = total_annotations - meta_count
    fidelity_ok = (facts_emitted == expected_facts)

    # Print report
    print(f"=== Provenance Coverage Report: {path.name} ===\n")
    print(f"Total clauses:         {total_clauses}")
    print(f"Annotated clauses:     {annotated_clauses} "
          f"({100 * annotated_clauses / max(total_clauses, 1):.1f}%)")
    print(f"Unmotivated clauses:   {len(unmotivated)}\n")
    print(f"Total annotations:     {total_annotations}")
    print(f"  Top-level:           {top_level_annotations}")
    print(f"  Nested:              {nested_annotations} "
          f"(across {nested_annotated_elements} inner elements)")
    print(f"  @id (meta):          {meta_count}")
    print(f"  Provenance-bearing:  {total_annotations - meta_count}\n")

    print("Kind distribution (combined top-level + nested):")
    for kind, n in sorted(kind_counts.items(), key=lambda x: -x[1]):
        category = _authority_category(kind)
        top_n = top_kind_counts.get(kind, 0)
        nested_n = nested_kind_counts.get(kind, 0)
        # Only show breakdown when both have non-zero counts; otherwise
        # the combined count is the same as the only-source count
        if top_n and nested_n:
            print(f"  {kind:25s} {n:4d}  ({category}) "
                  f"= {top_n} top + {nested_n} nested")
        else:
            print(f"  {kind:25s} {n:4d}  ({category})")
    print()

    print("Category distribution:")
    for cat, n in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:15s} {n:4d}")
    print()

    print(f"Fidelity check: {facts_emitted} facts emitted, "
          f"{expected_facts} expected")
    print(f"  {'OK' if fidelity_ok else 'MISMATCH — investigate!'}")

    if unmotivated:
        print(f"\nUnmotivated clauses ({len(unmotivated)}):")
        for cid in unmotivated[:20]:
            print(f"  {cid}")
        if len(unmotivated) > 20:
            print(f"  ... and {len(unmotivated) - 20} more")

    return {
        "total_clauses": total_clauses,
        "annotated_clauses": annotated_clauses,
        "coverage_pct": 100 * annotated_clauses / max(total_clauses, 1),
        "total_annotations": total_annotations,
        "top_level_annotations": top_level_annotations,
        "nested_annotations": nested_annotations,
        "nested_annotated_elements": nested_annotated_elements,
        "meta_count": meta_count,
        "provenance_annotations": total_annotations - meta_count,
        "kind_counts": dict(kind_counts),
        "top_kind_counts": dict(top_kind_counts),
        "nested_kind_counts": dict(nested_kind_counts),
        "category_counts": dict(category_counts),
        "facts_emitted": facts_emitted,
        "expected_facts": expected_facts,
        "fidelity_ok": fidelity_ok,
        "unmotivated": unmotivated,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 verify_provenance_coverage.py <path/to/file.bpd>")
        sys.exit(1)
    result = report_coverage(sys.argv[1])
    if "error" in result:
        sys.exit(2)
    if not result.get("fidelity_ok"):
        sys.exit(3)
