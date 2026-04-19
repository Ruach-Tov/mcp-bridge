"""BPD State Machine → SVG Generator

Generates interactive SVG state machine diagrams from the BPD Prolog IR.
Each element carries data attributes linking back to the BPD source and
provenance (.refs) entries for click-through navigation in the SVG client.

Design:
  - States → circles (normal) or diamonds (conditional)
  - Transitions → arrows with labels
  - Initial state → double circle or filled dot + arrow
  - Final state → double circle
  - Event handlers (on) → annotations on states
  - Layout: top-to-bottom flow, states arranged in declaration order

Author: mavchin (Claude Opus 4.6), 2026-04-17
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class SMState:
    name: str
    params: str = ""
    state_type: str = "normal"  # normal, initial, final, conditional
    handlers: list[str] = field(default_factory=list)
    bpd_line: Optional[int] = None
    refs_entry: Optional[str] = None
    x: float = 0
    y: float = 0


@dataclass
class SMTransition:
    from_state: str
    to_state: str
    condition: str = ""
    bpd_line: Optional[int] = None
    refs_entry: Optional[str] = None


@dataclass 
class StateMachine:
    name: str
    params: str = ""
    states: list[SMState] = field(default_factory=list)
    transitions: list[SMTransition] = field(default_factory=list)


def extract_state_machine_from_prolog(pl_path: str) -> StateMachine:
    """Extract state machine structure from a Prolog IR file."""
    sm = StateMachine(name="sm")
    
    with open(pl_path) as f:
        lines = f.readlines()
    
    state_order = []
    
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('%'):
            continue
        
        # initial_state(sm, X).
        if line.startswith('initial_state('):
            parts = line.split('(', 1)[1].rstrip(').').split(',', 1)
            if len(parts) >= 2:
                state_name = parts[1].strip()
                # Strip quotes
                state_name = state_name.strip("'")
                s = SMState(name=state_name, state_type="initial", bpd_line=i)
                sm.states.append(s)
                state_order.append(state_name)
        
        # state(sm, X). or state(sm, X(Y)).
        elif line.startswith('state('):
            inner = line.split('(', 1)[1].rstrip(').').split(',', 1)
            if len(inner) >= 2:
                state_expr = inner[1].strip()
                # Parse parameterized: running(how_relay) → name=running, params=how_relay
                if '(' in state_expr:
                    name = state_expr.split('(')[0].strip().strip("'")
                    params = state_expr.split('(', 1)[1].rstrip(')')
                else:
                    name = state_expr.strip().strip("'")
                    params = ""
                # Don't duplicate if already added as initial
                if name not in state_order:
                    s = SMState(name=name, params=params, state_type="normal", bpd_line=i)
                    sm.states.append(s)
                    state_order.append(name)
        
        # final_state(sm, X).
        elif line.startswith('final_state('):
            inner = line.split('(', 1)[1].rstrip(').').split(',', 1)
            if len(inner) >= 2:
                state_name = inner[1].strip().strip("'")
                s = SMState(name=state_name, state_type="final", bpd_line=i)
                sm.states.append(s)
                state_order.append(state_name)
        
        # conditional(sm, X(Y)).
        elif line.startswith('conditional('):
            inner = line.split('(', 1)[1].rstrip(').').split(',', 1)
            if len(inner) >= 2:
                state_expr = inner[1].strip()
                if '(' in state_expr:
                    name = state_expr.split('(')[0].strip().strip("'")
                    params = state_expr.split('(', 1)[1].rstrip(')')
                else:
                    name = state_expr.strip().strip("'")
                    params = ""
                s = SMState(name=name, params=params, state_type="conditional", bpd_line=i)
                sm.states.append(s)
                state_order.append(name)
        
        # transition(sm, From, To, Condition).
        elif line.startswith('transition('):
            inner = line.split('(', 1)[1].rstrip(').').split(',')
            if len(inner) >= 4:
                from_s = inner[1].strip().strip("'")
                to_s = inner[2].strip().strip("'")
                cond = ','.join(inner[3:]).strip().strip("'")
                # Clean up complex conditions
                cond = cond.replace('\\+', 'not').replace(';', ' or ')
                t = SMTransition(from_state=from_s, to_state=to_s, 
                               condition=cond, bpd_line=i)
                sm.transitions.append(t)
        
        # transition_conditional(sm, State, (A, B)).
        elif line.startswith('transition_conditional('):
            inner = line.split('(', 1)[1].rstrip(').').split(',', 1)
            if len(inner) >= 2:
                rest = inner[1].strip()
                parts = rest.split(',', 1)
                from_s = parts[0].strip().strip("'")
                targets = parts[1].strip() if len(parts) > 1 else ""
                # Parse tuple(a, b) → two transitions
                if 'tuple(' in targets:
                    target_inner = targets.split('tuple(')[1].rstrip(')')
                    for target in target_inner.split(','):
                        target = target.strip().strip("'")
                        t = SMTransition(from_state=from_s, to_state=target,
                                       condition=f"→ {target}", bpd_line=i)
                        sm.transitions.append(t)
        
        # on(sm, State, Event) :- Body.  → event handler
        elif line.startswith('on('):
            inner = line.split('(', 1)[1].split(',', 2)
            if len(inner) >= 3:
                state_name = inner[1].strip().strip("'")
                event = inner[2].split(')')[0].strip()
                # Find the state and add handler
                for s in sm.states:
                    if s.name == state_name:
                        s.handlers.append(event)
                        break
    
    return sm


def layout_states(sm: StateMachine, width: float = 900, margin: float = 80):
    """Assign x,y positions using topology-aware multi-column layout.
    
    Layout strategy:
      1. Identify the main path (longest chain from initial to final)
      2. Place main path in the center column
      3. Place fork destinations in a right column
      4. Place back-edge targets to the left
      5. Terminal states go to the bottom-right
      6. Sufficient vertical spacing for edge labels (rule e)
    """
    from collections import defaultdict
    
    n = len(sm.states)
    if n == 0:
        return
    
    state_map = {s.name: s for s in sm.states}
    
    # Build adjacency from transitions
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for t in sm.transitions:
        outgoing[t.from_state].append(t.to_state)
        incoming[t.to_state].append(t.from_state)
    
    # Find initial state
    initial = None
    for s in sm.states:
        if s.state_type == "initial":
            initial = s.name
            break
    if not initial and sm.states:
        initial = sm.states[0].name
    
    # Compute depth (distance from initial) via BFS
    depth = {}
    queue = [initial]
    depth[initial] = 0
    visited = {initial}
    while queue:
        current = queue.pop(0)
        for next_s in outgoing.get(current, []):
            if next_s not in visited:
                visited.add(next_s)
                depth[next_s] = depth[current] + 1
                queue.append(next_s)
    
    # Assign unvisited states a depth based on their position in the state list
    for s in sm.states:
        if s.name not in depth:
            depth[s.name] = len(depth)
    
    # Rule (g): final states get maximum depth so they appear at the bottom
    max_depth = max(depth.values()) if depth else 0
    for s in sm.states:
        if s.state_type == "final":
            depth[s.name] = max_depth + 1
    
    # Identify fork points (states with 2+ outgoing transitions)
    forks = {s: targets for s, targets in outgoing.items() if len(targets) >= 2}
    
    # Identify back-edges (transition going to a state with lower depth)
    back_edges = set()
    for t in sm.transitions:
        if t.to_state in depth and t.from_state in depth:
            if depth[t.to_state] < depth[t.from_state]:
                back_edges.add((t.from_state, t.to_state))
    
    # Column assignment
    # Main path: center column (x = width * 0.4)
    # Right fork targets: right column (x = width * 0.75)
    # Back-edge sources that need space: shift slightly left
    column = {}  # state_name -> column index (0=left, 1=center, 2=right)
    
    # Default: everything in center
    for s in sm.states:
        column[s.name] = 1
    
    # For each fork, put the MORE TERMINAL target in the right column
    for source, targets in forks.items():
        if len(targets) == 2:
            t0, t1 = targets[0], targets[1]
            d0 = depth.get(t0, 0)
            d1 = depth.get(t1, 0)
            # The one with fewer outgoing edges (more terminal) goes right
            out0 = len(outgoing.get(t0, []))
            out1 = len(outgoing.get(t1, []))
            if out0 <= out1:
                column[t0] = 2  # more terminal → right
            else:
                column[t1] = 2  # more terminal → right
    
    # Final states always go to right column
    for s in sm.states:
        if s.state_type == "final":
            column[s.name] = 2
    
    # Column x-positions
    col_x = {
        0: width * 0.2,   # left (for back-edge routing space)
        1: width * 0.4,   # center (main path)
        2: width * 0.75,  # right (fork targets, terminal)
    }
    
    # Vertical positioning by depth
    # Rule (e): edges need at least 80px for labels → use 150px spacing
    y_spacing = 150
    
    # Sort states by depth, then by column for tie-breaking
    ordered = sorted(sm.states, key=lambda s: (depth.get(s.name, 99), column.get(s.name, 1)))
    
    # Assign y positions — states at the same depth get the same y
    depth_y = {}
    current_y = margin
    last_depth = -1
    for s in ordered:
        d = depth.get(s.name, 99)
        if d not in depth_y:
            if d != last_depth:
                if last_depth >= 0:
                    current_y += y_spacing
            depth_y[d] = current_y
            last_depth = d
        s.x = col_x[column.get(s.name, 1)]
        s.y = depth_y[d]
    
    # Adjust: if two states share the same depth AND same column, offset vertically
    positions = {}
    for s in sm.states:
        key = (s.x, s.y)
        if key in positions:
            s.y += 60  # offset down
        positions[(s.x, s.y)] = s.name


def extract_provenance_map(bpd_path: str) -> dict:
    """Extract provenance annotations from a BPD file into a state-name → provenance map.

    Walks both top-level clauses (Clause.annotations) AND nested annotated
    elements inside clause bodies (AnnotatedElement wrappers introduced in
    commits 9e88d2ad9 / 2b902efd9 for the nested-annotation sprint).

    Without the nested walk, annotations on inner_clauses like
    `@cites(posix) initial_state(sm, :invocation) -> ...` inside a state
    machine body are invisible to the SVG viewer — the click-through side
    panel would have no provenance to show for such states. This function
    makes nested annotations first-class for the viewer.
    """
    from bpd_parser import parse_bpd_file
    from bpd_ast import (
        Atom, CompoundTerm, BareName, StringLiteral,
        AnnotatedElement, InnerClause, Body, ParallelBody, PatternMatch,
        PatternArm,
    )

    prog = parse_bpd_file(bpd_path)
    prov_map: dict = {}

    def _key_for_term(term) -> str:
        """Derive the prov_map key from a term. For a compound with >=2 args
        (the usual shape: state(sm, X), transition(sm, ...)), use arg[1]'s
        atom name or functor. Otherwise use the head functor."""
        functor = getattr(term, 'functor', None)
        args = getattr(term, 'args', ())
        if len(args) >= 2:
            second = args[1]
            if isinstance(second, Atom):
                return second.name
            if isinstance(second, CompoundTerm):
                return second.functor
        if functor:
            return functor
        # Last resort for bare atoms / names
        if isinstance(term, Atom):
            return term.name
        if isinstance(term, BareName):
            return term.name
        return 'unknown'

    def _key_for_element(element) -> str:
        """Same as _key_for_term but for a body element (may be an
        InnerClause, in which case we key by its head's second arg)."""
        if isinstance(element, InnerClause):
            return _key_for_term(element.head.term)
        return _key_for_term(element)

    def _collect_from_annotations(key: str, annots: tuple) -> None:
        """Process a list of annotations and add their sources/reasoning to
        the prov_map under the given key. Shared between top-level and
        nested-annotation paths so the two always agree on semantics."""
        sources = []
        reasoning = ''
        for ann in annots:
            ann_args = getattr(ann, 'args', ())
            for arg in ann_args:
                if isinstance(arg, BareName):
                    sources.append(arg.name)
                elif isinstance(arg, CompoundTerm) and arg.functor == 'reasoning':
                    if arg.args and isinstance(arg.args[0], StringLiteral):
                        reasoning = arg.args[0].value
                elif isinstance(arg, CompoundTerm) and arg.functor == 'commit':
                    if arg.args:
                        # commit arg may be StringLiteral or BareName
                        commit_val = arg.args[0]
                        if isinstance(commit_val, StringLiteral):
                            sources.append(f'commit:{commit_val.value}')
                        elif isinstance(commit_val, (BareName, Atom)):
                            sources.append(f'commit:{commit_val.name}')

        if key not in prov_map:
            prov_map[key] = {'sources': [], 'reasoning': ''}
        prov_map[key]['sources'].extend(sources)
        if reasoning and not prov_map[key]['reasoning']:
            prov_map[key]['reasoning'] = reasoning

    def _walk_body_for_nested(body) -> None:
        """Depth-first walk of a clause body to find AnnotatedElement
        wrappers and collect their annotations. Mirrors the traversal in
        bpd_preprocess._walk_annotated_elements; kept inline here to avoid
        a cross-module import just for this path."""
        if body is None:
            return
        if isinstance(body, Body):
            for el in body.elements:
                _visit_element(el)
        elif isinstance(body, ParallelBody):
            for branch in body.branches:
                _walk_body_for_nested(branch)
        elif isinstance(body, PatternMatch):
            for arm in body.arms:
                if isinstance(arm, PatternArm):
                    _walk_body_for_nested(arm.body)

    def _visit_element(el) -> None:
        if isinstance(el, AnnotatedElement):
            key = _key_for_element(el.element)
            _collect_from_annotations(key, el.annotations)
            # Continue descending; a wrapped InnerClause may itself
            # contain further AnnotatedElements in its body.
            inner = el.element
            if isinstance(inner, InnerClause):
                _walk_body_for_nested(inner.body)
        elif isinstance(el, InnerClause):
            _walk_body_for_nested(el.body)

    for c in prog.clauses:
        # Top-level annotations on this clause (existing behavior)
        if c.annotations:
            key = _key_for_term(c.head.term)
            _collect_from_annotations(key, c.annotations)

        # Nested annotations inside this clause's body (new behavior)
        _walk_body_for_nested(c.body)

    return prov_map
    """Escape string for XML attribute/text content."""
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;')
             .replace("'", '&apos;'))


def generate_svg(sm: StateMachine, width: int = 900, height: int = 0, prov_map: dict = None) -> str:
    """Generate an SVG state machine diagram with provenance data attributes."""
    
    if prov_map is None:
        prov_map = {}

    def escape_xml(s: str) -> str:
        """Escape string for XML attribute/text content."""
        return (s.replace('&', '&amp;')
                 .replace('<', '&lt;')
                 .replace('>', '&gt;')
                 .replace('"', '&quot;')
                 .replace("'", '&apos;'))
    
    layout_states(sm, width=width)
    
    # Auto-calculate height from state positions
    if height == 0:
        max_y = max((s.y for s in sm.states), default=400)
        height = int(max_y + 120)
    
    # Build state lookup
    state_map = {s.name: s for s in sm.states}
    
    # SVG header with GitHub dark theme
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"',
        f'     viewBox="0 0 {width} {height}"',
        f'     style="background: #0d1117; font-family: \'Roboto\', \'Segoe UI\', sans-serif;">',
        '',
        '  <defs>',
        '    <marker id="arrowhead" markerWidth="10" markerHeight="7"',
        '            refX="10" refY="3.5" orient="auto">',
        '      <polygon points="0 0, 10 3.5, 0 7" fill="#8b949e" />',
        '    </marker>',
        '    <marker id="arrowhead-active" markerWidth="10" markerHeight="7"',
        '            refX="10" refY="3.5" orient="auto">',
        '      <polygon points="0 0, 10 3.5, 0 7" fill="#58a6ff" />',
        '    </marker>',
        '  </defs>',
        '',
        f'  <text x="{width/2}" y="30" text-anchor="middle"',
        f'        fill="#f0f6fc" font-size="16" font-weight="bold">',
        f'    State Machine: {escape_xml(sm.name)}</text>',
        '',
    ]
    
    STATE_RX = 60  # ellipse horizontal radius
    STATE_RY = 25  # ellipse vertical radius
    DIAMOND_SIZE = 30  # diamond half-size
    
    # Draw transitions (arrows) first (behind states)
    svg_parts.append('  <!-- Transitions -->')
    for t in sm.transitions:
        from_s = state_map.get(t.from_state)
        to_s = state_map.get(t.to_state)
        if not from_s or not to_s:
            continue
        
        # Calculate arrow routing
        dx = to_s.x - from_s.x
        dy = to_s.y - from_s.y
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 1:
            continue
        
        # Normalize direction
        nx, ny = dx/dist, dy/dist
        
        # Start/end at edge of shapes
        if from_s.state_type == "conditional":
            start_x = from_s.x + nx * DIAMOND_SIZE
            start_y = from_s.y + ny * DIAMOND_SIZE
        else:
            start_x = from_s.x + nx * STATE_RX * 0.8
            start_y = from_s.y + ny * STATE_RY
        
        if to_s.state_type == "conditional":
            end_x = to_s.x - nx * DIAMOND_SIZE
            end_y = to_s.y - ny * DIAMOND_SIZE
        else:
            end_x = to_s.x - nx * STATE_RX * 0.8
            end_y = to_s.y - ny * STATE_RY
        
        # Determine routing strategy
        is_back_edge = to_s.y < from_s.y - 20  # going upward
        is_cross_column = abs(dx) > 50  # different columns
        
        if is_back_edge:
            # Back-edge: route to the LEFT of all nodes
            left_x = min(s.x for s in sm.states) - 80
            mid_y = (from_s.y + to_s.y) / 2
            # Use a path that goes left, up, then right
            start_x = from_s.x - STATE_RX
            start_y = from_s.y
            end_x = to_s.x - STATE_RX
            end_y = to_s.y
            path = (f'M {start_x},{start_y} '
                    f'C {left_x},{start_y} {left_x},{end_y} {end_x},{end_y}')
            label_x = left_x - 10
            label_y = mid_y
        elif is_cross_column:
            # Cross-column: straight line or gentle curve
            path = f'M {start_x},{start_y} L {end_x},{end_y}'
            label_x = (start_x + end_x) / 2
            label_y = (start_y + end_y) / 2 - 10
        else:
            # Same column, downward: gentle rightward curve
            ctrl_x = max(from_s.x, to_s.x) + 80
            ctrl_y = (from_s.y + to_s.y) / 2
            path = f'M {start_x},{start_y} Q {ctrl_x},{ctrl_y} {end_x},{end_y}'
            label_x = ctrl_x + 10
            label_y = ctrl_y
        
        bpd_attr = f' data-bpd-line="{t.bpd_line}"' if t.bpd_line else ''
        refs_attr = f' data-refs-entry="{escape_xml(t.refs_entry)}"' if t.refs_entry else ''
        
        svg_parts.append(
            f'  <path d="{path}" fill="none" stroke="#8b949e" stroke-width="1.5"'
            f'        marker-end="url(#arrowhead)"{bpd_attr}{refs_attr}'
            f'        data-element-type="transition"'
            f'        data-from="{escape_xml(t.from_state)}"'
            f'        data-to="{escape_xml(t.to_state)}" />'
        )
        
        # Condition label
        if t.condition and t.condition != 'pass':
            cond_short = t.condition[:30] + ('...' if len(t.condition) > 30 else '')
            svg_parts.append(
                f'  <text x="{label_x}" y="{label_y}" fill="#8b949e"'
                f'        font-size="9" font-style="italic">'
                f'{escape_xml(cond_short)}</text>'
            )
    
    # Draw states
    svg_parts.append('')
    svg_parts.append('  <!-- States -->')
    
    for s in sm.states:
        bpd_attr = f' data-bpd-line="{s.bpd_line}"' if s.bpd_line else ''
        refs_attr = f' data-refs-entry="{escape_xml(s.refs_entry)}"' if s.refs_entry else ''
        
        # Provenance data attributes from @cites/@adopts/@provenance annotations
        prov = prov_map.get(s.name, {})
        prov_sources = ', '.join(prov.get('sources', []))
        prov_reasoning = prov.get('reasoning', '')
        prov_attr = ''
        if prov_sources:
            prov_attr += f' data-prov-source="{escape_xml(prov_sources)}"'
        if prov_reasoning:
            prov_attr += f' data-prov-reasoning="{escape_xml(prov_reasoning)}"'
        
        if s.state_type == "initial":
            # Double circle for initial state
            svg_parts.append(
                f'  <g data-element-type="state" data-state-name="{escape_xml(s.name)}"'
                f'     data-state-type="initial"{bpd_attr}{refs_attr}{prov_attr}>'
            )
            svg_parts.append(
                f'    <ellipse cx="{s.x}" cy="{s.y}" rx="{STATE_RX}" ry="{STATE_RY}"'
                f'             fill="#1a2332" stroke="#58a6ff" stroke-width="2" />'
            )
            svg_parts.append(
                f'    <ellipse cx="{s.x}" cy="{s.y}" rx="{STATE_RX-4}" ry="{STATE_RY-4}"'
                f'             fill="none" stroke="#58a6ff" stroke-width="1" />'
            )
            # Entry dot
            svg_parts.append(
                f'    <circle cx="{s.x - STATE_RX - 30}" cy="{s.y}" r="6"'
                f'            fill="#58a6ff" />'
            )
            svg_parts.append(
                f'    <line x1="{s.x - STATE_RX - 24}" y1="{s.y}"'
                f'          x2="{s.x - STATE_RX}" y2="{s.y}"'
                f'          stroke="#58a6ff" stroke-width="2"'
                f'          marker-end="url(#arrowhead-active)" />'
            )
            
        elif s.state_type == "final":
            # Bold circle for final state
            svg_parts.append(
                f'  <g data-element-type="state" data-state-name="{escape_xml(s.name)}"'
                f'     data-state-type="final"{bpd_attr}{refs_attr}{prov_attr}>'
            )
            svg_parts.append(
                f'    <ellipse cx="{s.x}" cy="{s.y}" rx="{STATE_RX}" ry="{STATE_RY}"'
                f'             fill="#1a2332" stroke="#f85149" stroke-width="3" />'
            )
            svg_parts.append(
                f'    <ellipse cx="{s.x}" cy="{s.y}" rx="{STATE_RX-4}" ry="{STATE_RY-4}"'
                f'             fill="none" stroke="#f85149" stroke-width="1" />'
            )
            
        elif s.state_type == "conditional":
            # Diamond for conditional
            svg_parts.append(
                f'  <g data-element-type="state" data-state-name="{escape_xml(s.name)}"'
                f'     data-state-type="conditional"{bpd_attr}{refs_attr}{prov_attr}>'
            )
            d = DIAMOND_SIZE
            points = f'{s.x},{s.y-d} {s.x+d},{s.y} {s.x},{s.y+d} {s.x-d},{s.y}'
            svg_parts.append(
                f'    <polygon points="{points}"'
                f'             fill="#1a2332" stroke="#d29922" stroke-width="2" />'
            )
            
        else:
            # Normal state — simple ellipse
            svg_parts.append(
                f'  <g data-element-type="state" data-state-name="{escape_xml(s.name)}"'
                f'     data-state-type="normal"{bpd_attr}{refs_attr}{prov_attr}>'
            )
            svg_parts.append(
                f'    <ellipse cx="{s.x}" cy="{s.y}" rx="{STATE_RX}" ry="{STATE_RY}"'
                f'             fill="#1a2332" stroke="#30363d" stroke-width="2" />'
            )
        
        # State name label
        label = s.name
        if s.params:
            label = f'{s.name}({s.params})'
        svg_parts.append(
            f'    <text x="{s.x}" y="{s.y + 4}" text-anchor="middle"'
            f'          fill="#f0f6fc" font-size="11">{escape_xml(label)}</text>'
        )
        
        # Handler annotations
        for j, handler in enumerate(s.handlers):
            svg_parts.append(
                f'    <text x="{s.x + STATE_RX + 10}" y="{s.y - 5 + j * 14}"'
                f'          fill="#7ee787" font-size="9">on: {escape_xml(handler)}</text>'
            )
        
        svg_parts.append('  </g>')
    
    svg_parts.append('')
    svg_parts.append('</svg>')
    
    return '\n'.join(svg_parts)


def generate_state_machine_svg(pl_path: str, svg_path: str | None = None,
                                bpd_path: str | None = None) -> str:
    """Generate an SVG from a Prolog IR file's state machine.
    
    If bpd_path is provided, provenance annotations from the BPD file
    are embedded as data attributes on SVG elements for click-through
    navigation.
    """
    sm = extract_state_machine_from_prolog(pl_path)
    
    prov_map = {}
    if bpd_path:
        try:
            prov_map = extract_provenance_map(bpd_path)
        except Exception as e:
            print(f"Warning: could not extract provenance: {e}")
    
    svg = generate_svg(sm, prov_map=prov_map)
    
    if svg_path:
        Path(svg_path).write_text(svg)
    
    return svg


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pl_path = sys.argv[1]
        svg_path = sys.argv[2] if len(sys.argv) > 2 else None
        svg = generate_state_machine_svg(pl_path, svg_path)
        if not svg_path:
            print(svg)
    else:
        print("Usage: python bpd_to_svg_state_machine.py <file.pl> [output.svg]")
