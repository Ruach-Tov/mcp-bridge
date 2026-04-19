"""BPD SVG Anti-Pattern Detector

Checks generated state machine SVGs for visual quality issues.
Each rule is atomic and testable. Rules compose to guide layout improvement.

Rules:
  (a) Edge-crosses-node: an edge should not cross any node that isn't an endpoint
  (b) Edge-crosses-edge: an edge should avoid crossing another edge if avoidable
  (c) Crossing angle: unavoidable crossings should be at right angles on rare paths
  (d) Edge path excess: curved edge should not exceed 200% of straight line
  (e) Edge label space: edges should be long enough for 3-5 lines of commentary
  (f) Fork column separation: forked destinations should be in separate columns
  (g) Terminal downstream: more-terminal states should be further downstream

Author: mavchin (Claude Opus 4.6), 2026-04-17
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import xml.etree.ElementTree as ET
import math
import re
from typing import Optional


@dataclass
class Violation:
    rule: str
    severity: str  # "error", "warning", "info"
    element: str   # which element(s) triggered it
    message: str
    suggestion: str = ""


@dataclass
class Point:
    x: float
    y: float


@dataclass
class StateShape:
    name: str
    cx: float
    cy: float
    rx: float  # horizontal extent
    ry: float  # vertical extent
    state_type: str = "normal"


@dataclass
class EdgeShape:
    from_state: str
    to_state: str
    start: Point
    end: Point
    ctrl: Optional[Point] = None  # quadratic bezier control point
    path_length: float = 0
    straight_length: float = 0


def parse_svg(svg_path: str) -> tuple[list[StateShape], list[EdgeShape]]:
    """Parse an SVG file and extract state shapes and edge shapes."""
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = {'svg': 'http://www.w3.org/2000/svg'}

    states = []
    edges = []

    # Extract states from <g> groups
    for g in root.findall('.//svg:g', ns):
        el_type = g.get('data-element-type', '')
        if el_type == 'state':
            name = g.get('data-state-name', '?')
            stype = g.get('data-state-type', 'normal')
            # Find the ellipse or polygon inside
            ellipse = g.find('svg:ellipse', ns)
            polygon = g.find('svg:polygon', ns)
            if ellipse is not None:
                cx = float(ellipse.get('cx', 0))
                cy = float(ellipse.get('cy', 0))
                rx = float(ellipse.get('rx', 30))
                ry = float(ellipse.get('ry', 20))
            elif polygon is not None:
                # Diamond — extract from points
                points_str = polygon.get('points', '')
                pts = [p.strip().split(',') for p in points_str.split()]
                if len(pts) >= 4:
                    xs = [float(p[0]) for p in pts]
                    ys = [float(p[1]) for p in pts]
                    cx = sum(xs) / len(xs)
                    cy = sum(ys) / len(ys)
                    rx = (max(xs) - min(xs)) / 2
                    ry = (max(ys) - min(ys)) / 2
                else:
                    continue
            else:
                continue
            states.append(StateShape(name=name, cx=cx, cy=cy, rx=rx, ry=ry, state_type=stype))

    # Extract edges from <path> elements
    for path in root.findall('.//svg:path', ns):
        el_type = path.get('data-element-type', '')
        if el_type == 'transition':
            from_s = path.get('data-from', '?')
            to_s = path.get('data-to', '?')
            d = path.get('d', '')

            # Parse path data (M x,y Q cx,cy x,y or M x,y L x,y)
            start = end = ctrl = None
            m_match = re.match(r'M\s+([\d.]+),([\d.]+)', d)
            if m_match:
                start = Point(float(m_match.group(1)), float(m_match.group(2)))

            q_match = re.search(r'Q\s+([\d.]+),([\d.]+)\s+([\d.]+),([\d.]+)', d)
            l_match = re.search(r'L\s+([\d.]+),([\d.]+)', d)

            if q_match:
                ctrl = Point(float(q_match.group(1)), float(q_match.group(2)))
                end = Point(float(q_match.group(3)), float(q_match.group(4)))
            elif l_match:
                end = Point(float(l_match.group(1)), float(l_match.group(2)))

            if start and end:
                straight = math.dist((start.x, start.y), (end.x, end.y))
                if ctrl:
                    # Approximate quadratic bezier length
                    d1 = math.dist((start.x, start.y), (ctrl.x, ctrl.y))
                    d2 = math.dist((ctrl.x, ctrl.y), (end.x, end.y))
                    path_len = (d1 + d2 + straight) / 2  # rough approximation
                else:
                    path_len = straight

                edges.append(EdgeShape(
                    from_state=from_s, to_state=to_s,
                    start=start, end=end, ctrl=ctrl,
                    path_length=path_len, straight_length=straight
                ))

    return states, edges


def point_near_segment(px: float, py: float, x1: float, y1: float,
                       x2: float, y2: float, threshold: float = 15) -> bool:
    """Check if a point is within threshold distance of a line segment."""
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx*dx + dy*dy
    if len_sq < 0.001:
        return math.dist((px, py), (x1, y1)) < threshold
    t = max(0, min(1, ((px-x1)*dx + (py-y1)*dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.dist((px, py), (proj_x, proj_y)) < threshold


def segments_cross(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """Check if two line segments intersect."""
    def cross(o, a, b):
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    d1 = cross(b1, b2, a1)
    d2 = cross(b1, b2, a2)
    d3 = cross(a1, a2, b1)
    d4 = cross(a1, a2, b2)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def check_all_rules(states: list[StateShape], edges: list[EdgeShape]) -> list[Violation]:
    """Run all anti-pattern checks."""
    violations = []

    state_map = {s.name: s for s in states}

    # ── RULE (a): Edge crosses non-endpoint node ──
    for edge in edges:
        for state in states:
            if state.name in (edge.from_state, edge.to_state):
                continue
            # Check if the edge path passes near this state
            if edge.ctrl:
                # Check both segments of the quadratic bezier
                near1 = point_near_segment(state.cx, state.cy,
                    edge.start.x, edge.start.y, edge.ctrl.x, edge.ctrl.y,
                    threshold=state.ry + 5)
                near2 = point_near_segment(state.cx, state.cy,
                    edge.ctrl.x, edge.ctrl.y, edge.end.x, edge.end.y,
                    threshold=state.ry + 5)
                if near1 or near2:
                    violations.append(Violation(
                        rule="(a) edge-crosses-node",
                        severity="error",
                        element=f"{edge.from_state} → {edge.to_state}",
                        message=f"Edge passes through/near node '{state.name}'",
                        suggestion=f"Route edge around '{state.name}' or reposition nodes"
                    ))
            else:
                if point_near_segment(state.cx, state.cy,
                    edge.start.x, edge.start.y, edge.end.x, edge.end.y,
                    threshold=state.ry + 5):
                    violations.append(Violation(
                        rule="(a) edge-crosses-node",
                        severity="error",
                        element=f"{edge.from_state} → {edge.to_state}",
                        message=f"Edge passes through/near node '{state.name}'",
                        suggestion=f"Route edge around '{state.name}' or reposition nodes"
                    ))

    # ── RULE (b): Edge crosses edge ──
    for i, e1 in enumerate(edges):
        for e2 in edges[i+1:]:
            # Use start/end points (simplified — should use full path)
            if segments_cross(e1.start, e1.end, e2.start, e2.end):
                violations.append(Violation(
                    rule="(b) edge-crosses-edge",
                    severity="warning",
                    element=f"({e1.from_state}→{e1.to_state}) × ({e2.from_state}→{e2.to_state})",
                    message="Two edges cross",
                    suggestion="Reposition nodes to eliminate crossing, or route edges differently"
                ))

    # ── RULE (d): Edge path excess >200% ──
    # A curved edge should not be more than 3× the straight-line distance.
    # The 200% threshold catches pathological routing (729%, 1224% from v1)
    # while allowing reasonable curves (75-80% from v2 is fine).
    for edge in edges:
        if edge.straight_length > 0:
            excess = (edge.path_length / edge.straight_length) - 1.0
            if excess > 2.0:
                violations.append(Violation(
                    rule="(d) edge-path-excess",
                    severity="warning",
                    element=f"{edge.from_state} → {edge.to_state}",
                    message=f"Edge is {excess*100:.0f}% longer than straight line "
                            f"(path={edge.path_length:.0f}, straight={edge.straight_length:.0f})",
                    suggestion="Increase spacing between states or use straighter routing"
                ))

    # ── RULE (e): Edge too short for labels ──
    MIN_EDGE_LENGTH = 80  # pixels — room for ~3 lines of 9pt text
    for edge in edges:
        if edge.straight_length < MIN_EDGE_LENGTH:
            violations.append(Violation(
                rule="(e) edge-label-space",
                severity="warning",
                element=f"{edge.from_state} → {edge.to_state}",
                message=f"Edge is only {edge.straight_length:.0f}px — too short for labels "
                        f"(minimum {MIN_EDGE_LENGTH}px)",
                suggestion="Increase vertical or horizontal spacing between these states"
            ))

    # ── RULE (f): Fork destinations should be in separate columns ──
    # Find states with multiple outgoing transitions
    from collections import defaultdict
    outgoing = defaultdict(list)
    for edge in edges:
        outgoing[edge.from_state].append(edge.to_state)

    for source, targets in outgoing.items():
        if len(targets) >= 2:
            # Check if targets are in the same column (same x)
            target_xs = []
            for t in targets:
                if t in state_map:
                    target_xs.append((t, state_map[t].cx))
            if len(target_xs) >= 2:
                xs = [x for _, x in target_xs]
                if max(xs) - min(xs) < 50:  # effectively same column
                    violations.append(Violation(
                        rule="(f) fork-column-separation",
                        severity="warning",
                        element=f"{source} → {{{', '.join(targets)}}}",
                        message=f"Fork from '{source}' has destinations in the same column",
                        suggestion=f"Place {targets[0]} and {targets[1]} in separate columns"
                    ))

    # ── RULE (g): Terminal states should be downstream ──
    # Find the most terminal states (fewest outgoing transitions)
    # and check they are positioned downstream (higher y)
    terminal_states = [s for s in states if s.state_type == "final"]
    non_terminal = [s for s in states if s.state_type not in ("final",)]
    for ts in terminal_states:
        for nts in non_terminal:
            if nts.cy > ts.cy + 20:  # non-terminal is below terminal
                violations.append(Violation(
                    rule="(g) terminal-downstream",
                    severity="info",
                    element=f"final:{ts.name} vs {nts.name}",
                    message=f"Final state '{ts.name}' (y={ts.cy:.0f}) is above "
                            f"non-terminal '{nts.name}' (y={nts.cy:.0f})",
                    suggestion=f"Move '{ts.name}' below '{nts.name}' on the diagram"
                ))

    # ── RULE: All states in single column ──
    if len(states) > 3:
        xs = [s.cx for s in states]
        if max(xs) - min(xs) < 50:
            violations.append(Violation(
                rule="(layout) single-column",
                severity="info",
                element="all states",
                message="All states are in a single vertical column",
                suggestion="Use multiple columns, especially for forks and back-edges"
            ))

    return violations


def run_checks(svg_path: str) -> list[Violation]:
    """Parse SVG and run all anti-pattern checks."""
    states, edges = parse_svg(svg_path)
    return check_all_rules(states, edges)


def print_report(violations: list[Violation]):
    """Print a formatted violation report."""
    by_severity = {"error": [], "warning": [], "info": []}
    for v in violations:
        by_severity[v.severity].append(v)

    total = len(violations)
    errors = len(by_severity["error"])
    warnings = len(by_severity["warning"])
    infos = len(by_severity["info"])

    print(f"SVG ANTI-PATTERN REPORT")
    print(f"=======================")
    print(f"  {errors} errors, {warnings} warnings, {infos} info")
    print()

    for severity in ["error", "warning", "info"]:
        if not by_severity[severity]:
            continue
        icon = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}[severity]
        for v in by_severity[severity]:
            print(f"  {icon} [{v.rule}] {v.element}")
            print(f"     {v.message}")
            if v.suggestion:
                print(f"     → {v.suggestion}")
            print()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        violations = run_checks(sys.argv[1])
        print_report(violations)
    else:
        print("Usage: python svg_antipatterns.py <file.svg>")
