"""BPD Yourdon Data Flow Diagram → SVG Generator

Generates classical Yourdon-style DFDs from the BPD Prolog IR.

Yourdon DFD elements:
  - External entities (rectangles): processes outside the system boundary
  - Processes (circles/bubbles): functional transformations within the system
  - Data stores (parallel lines): persistent state
  - Data flows (labeled arrows): named data moving between elements

The generator extracts these from:
  - process() + this_is() → external entities vs system processes
  - boundary() → data flows cross these interfaces
  - relay() → the core process (bidirectional data transformation)
  - on() event handlers → individual processing steps
  - variable() / absorbs() → data stores

Author: mavchin (Claude Opus 4.6), 2026-04-18
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import re
import math


@dataclass
class DFDElement:
    name: str
    element_type: str  # "external", "process", "store"
    label: str = ""
    x: float = 0
    y: float = 0
    bpd_line: Optional[int] = None


@dataclass
class DFDFlow:
    from_element: str
    to_element: str
    label: str
    bpd_line: Optional[int] = None


def extract_dfd_from_prolog(pl_paths: list[str]) -> tuple[list[DFDElement], list[DFDFlow]]:
    """Extract Yourdon DFD elements from one or more Prolog IR files."""
    elements = []
    flows = []
    seen = set()

    system_name = None
    external_entities = []
    boundaries = []

    def ensure_element(name, etype, label=""):
        if name not in seen:
            elements.append(DFDElement(name=name, element_type=etype,
                                       label=label or name))
            seen.add(name)

    for pl_path in pl_paths:
        with open(pl_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('%') or line.startswith(':-'):
                continue

            # this_is(bridge) → identifies the system
            this_match = re.match(r'this_is\((\w+)\)', line)
            if this_match:
                system_name = this_match.group(1)

            # process(X) facts (not rules, not variables) → external entities
            proc_match = re.match(r'process\((\w+)\)\.$', line)
            if proc_match:
                name = proc_match.group(1)
                # Skip variables (uppercase single letter = Prolog variable from horn rule)
                if name != system_name and not (len(name) == 1 and name.isupper()):
                    external_entities.append(name)

            # boundary declarations → identify interfaces
            bound_match = re.match(r'(\w+_boundary)\((\w+),\s*(\w+),\s*(\w+)', line)
            if bound_match:
                bname = bound_match.group(2)
                actor_a = bound_match.group(3)
                actor_b = bound_match.group(4)
                boundaries.append({
                    'name': bname, 'a': actor_a, 'b': actor_b, 'line': i
                })

            # relay() → the core process
            relay_match = re.match(r'relay\((\w+),\s*(\w+),\s*(\w+)\)', line)
            if relay_match:
                ensure_element("relay", "process",
                              label="Relay\n(bidirectional)")

            # on() handlers with request/response patterns → processing steps
            if line.startswith('on(') and 'request(' in line and "'GET'" in line:
                ensure_element("session_init", "process",
                              label="Session\nInitialization")

            if line.startswith('on(') and 'request(' in line and "'POST'" in line and '404' not in line:
                ensure_element("request_handler", "process",
                              label="Request\nHandler")

            # variable/absorbs → data store
            if line.startswith('variable(') or line.startswith('absorbs('):
                ensure_element("session_state", "store",
                              label="Session State")

    # Build external entities
    for name in external_entities:
        if name in ('os', 'shell'):
            continue  # Skip OS-level entities for clarity
        ensure_element(name, "external", label=f":{name}")

    # Build processes from boundaries if we haven't already
    if "relay" not in seen:
        ensure_element("relay", "process", label="Relay")

    # Build flows from boundaries
    for b in boundaries:
        if 'http' in b['name'] and 'listener' in b['name']:
            # HTTP listener → external client connects
            flows.append(DFDFlow(
                from_element="client", to_element="session_init",
                label="GET /sse", bpd_line=b['line']
            ))
            flows.append(DFDFlow(
                from_element="session_init", to_element="client",
                label="SSE stream\n(endpoint event)", bpd_line=b['line']
            ))
        elif 'http' in b['name'] and 'session' in b['name']:
            flows.append(DFDFlow(
                from_element="client", to_element="request_handler",
                label="POST\n(JSON-RPC)", bpd_line=b['line']
            ))
            flows.append(DFDFlow(
                from_element="request_handler", to_element="client",
                label="HTTP 202", bpd_line=b['line']
            ))
        elif 'stdio' in b['name']:
            flows.append(DFDFlow(
                from_element="relay", to_element="server",
                label="stdin\n(JSON-RPC)", bpd_line=b['line']
            ))
            flows.append(DFDFlow(
                from_element="server", to_element="relay",
                label="stdout\n(JSON-RPC)", bpd_line=b['line']
            ))

    # Internal flows
    if "request_handler" in seen and "relay" in seen:
        flows.append(DFDFlow(
            from_element="request_handler", to_element="relay",
            label="forward\nrequest"
        ))
    if "relay" in seen and "session_init" in seen:
        flows.append(DFDFlow(
            from_element="relay", to_element="session_init",
            label="SSE events\n(responses)"
        ))
    if "session_state" in seen:
        flows.append(DFDFlow(
            from_element="session_init", to_element="session_state",
            label="session_id,\nsse_stream"
        ))
        flows.append(DFDFlow(
            from_element="session_state", to_element="request_handler",
            label="session\nlookup"
        ))

    return elements, flows


def layout_dfd(elements: list[DFDElement], width: int = 800, height: int = 600,
               margin: int = 80):
    """Layout DFD elements: externals on edges, processes in center."""
    externals = [e for e in elements if e.element_type == "external"]
    processes = [e for e in elements if e.element_type == "process"]
    stores = [e for e in elements if e.element_type == "store"]

    cx, cy = width / 2, height / 2

    # External entities on left and right edges
    for i, ext in enumerate(externals):
        if i == 0:
            ext.x = margin
            ext.y = cy
        else:
            ext.x = width - margin
            ext.y = cy

    # Processes in the center, arranged in a row or circle
    n_proc = len(processes)
    if n_proc == 1:
        processes[0].x = cx
        processes[0].y = cy
    elif n_proc == 2:
        processes[0].x = cx - 100
        processes[0].y = cy - 60
        processes[1].x = cx + 100
        processes[1].y = cy - 60
    elif n_proc >= 3:
        processes[0].x = cx
        processes[0].y = cy - 80
        processes[1].x = cx - 120
        processes[1].y = cy + 40
        processes[2].x = cx + 120
        processes[2].y = cy + 40

    # Data stores below processes
    for i, store in enumerate(stores):
        store.x = cx
        store.y = cy + 140 + i * 60


def escape_xml(s: str) -> str:
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;')
             .replace("'", '&apos;'))


def generate_dfd_svg(elements: list[DFDElement], flows: list[DFDFlow],
                     width: int = 800, height: int = 600) -> str:
    """Generate a Yourdon-style DFD SVG."""
    layout_dfd(elements, width=width, height=height)

    el_map = {e.name: e for e in elements}

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"')
    svg.append(f'     viewBox="0 0 {width} {height}"')
    svg.append(f'     style="background: #0d1117; font-family: \'Roboto\', \'Segoe UI\', sans-serif;">')
    svg.append('')
    svg.append('  <defs>')
    svg.append('    <marker id="dfd-arrow" markerWidth="8" markerHeight="6"')
    svg.append('            refX="8" refY="3" orient="auto">')
    svg.append('      <polygon points="0 0, 8 3, 0 6" fill="#8b949e" />')
    svg.append('    </marker>')
    svg.append('  </defs>')
    svg.append('')

    # Title
    svg.append(f'  <text x="{width/2}" y="25" text-anchor="middle"')
    svg.append(f'        fill="#f0f6fc" font-size="14" font-weight="bold">')
    svg.append(f'    Data Flow Diagram (Yourdon)</text>')
    svg.append('')

    BUBBLE_R = 45
    RECT_W = 90
    RECT_H = 50
    STORE_W = 120
    STORE_H = 30

    # Draw flows first (behind elements)
    svg.append('  <!-- Data Flows -->')
    for flow in flows:
        fe = el_map.get(flow.from_element)
        te = el_map.get(flow.to_element)
        if not fe or not te:
            continue

        dx = te.x - fe.x
        dy = te.y - fe.y
        dist = math.sqrt(dx*dx + dy*dy)
        if dist < 1:
            continue
        nx, ny = dx/dist, dy/dist

        # Start/end offsets based on element type
        def edge_offset(el, toward_x, toward_y):
            if el.element_type == "process":
                return BUBBLE_R
            elif el.element_type == "external":
                return RECT_W / 2
            elif el.element_type == "store":
                return STORE_W / 2
            return 30

        r1 = edge_offset(fe, te.x, te.y)
        r2 = edge_offset(te, fe.x, fe.y)

        x1 = fe.x + nx * r1
        y1 = fe.y + ny * r1
        x2 = te.x - nx * r2
        y2 = te.y - ny * r2

        # Curve the arrow slightly to avoid overlapping reverse flows
        perp_x = -ny * 15
        perp_y = nx * 15
        ctrl_x = (x1 + x2) / 2 + perp_x
        ctrl_y = (y1 + y2) / 2 + perp_y

        bpd_attr = f' data-bpd-line="{flow.bpd_line}"' if flow.bpd_line else ''

        svg.append(f'  <path d="M {x1},{y1} Q {ctrl_x},{ctrl_y} {x2},{y2}"')
        svg.append(f'        fill="none" stroke="#8b949e" stroke-width="1.2"')
        svg.append(f'        marker-end="url(#dfd-arrow)"')
        svg.append(f'        data-element-type="flow"{bpd_attr} />')

        # Flow label
        lx = ctrl_x + perp_x * 0.5
        ly = ctrl_y + perp_y * 0.5
        label_lines = flow.label.split('\n')
        for li, lt in enumerate(label_lines):
            svg.append(f'  <text x="{lx}" y="{ly + li * 11}" text-anchor="middle"')
            svg.append(f'        fill="#8b949e" font-size="9">{escape_xml(lt)}</text>')

    # Draw elements
    svg.append('')
    svg.append('  <!-- Elements -->')
    for el in elements:
        bpd_attr = f' data-bpd-line="{el.bpd_line}"' if el.bpd_line else ''

        if el.element_type == "external":
            # Rectangle (Yourdon external entity)
            svg.append(f'  <g data-element-type="external" data-name="{escape_xml(el.name)}"{bpd_attr}>')
            svg.append(f'    <rect x="{el.x - RECT_W/2}" y="{el.y - RECT_H/2}"')
            svg.append(f'          width="{RECT_W}" height="{RECT_H}"')
            svg.append(f'          fill="#1a2332" stroke="#58a6ff" stroke-width="2" />')
            label_lines = el.label.split('\n')
            for li, lt in enumerate(label_lines):
                ly = el.y + 4 + (li - len(label_lines)/2) * 14
                svg.append(f'    <text x="{el.x}" y="{ly}" text-anchor="middle"')
                svg.append(f'          fill="#f0f6fc" font-size="12" font-weight="bold">{escape_xml(lt)}</text>')
            svg.append('  </g>')

        elif el.element_type == "process":
            # Circle/bubble (Yourdon process)
            svg.append(f'  <g data-element-type="process" data-name="{escape_xml(el.name)}"{bpd_attr}>')
            svg.append(f'    <circle cx="{el.x}" cy="{el.y}" r="{BUBBLE_R}"')
            svg.append(f'            fill="#1a2332" stroke="#d2a8ff" stroke-width="2" />')
            label_lines = el.label.split('\n')
            for li, lt in enumerate(label_lines):
                ly = el.y + 4 + (li - len(label_lines)/2) * 13
                svg.append(f'    <text x="{el.x}" y="{ly}" text-anchor="middle"')
                svg.append(f'          fill="#f0f6fc" font-size="11">{escape_xml(lt)}</text>')
            svg.append('  </g>')

        elif el.element_type == "store":
            # Parallel lines (Yourdon data store)
            svg.append(f'  <g data-element-type="store" data-name="{escape_xml(el.name)}"{bpd_attr}>')
            svg.append(f'    <line x1="{el.x - STORE_W/2}" y1="{el.y - STORE_H/2}"')
            svg.append(f'          x2="{el.x + STORE_W/2}" y2="{el.y - STORE_H/2}"')
            svg.append(f'          stroke="#7ee787" stroke-width="2" />')
            svg.append(f'    <line x1="{el.x - STORE_W/2}" y1="{el.y + STORE_H/2}"')
            svg.append(f'          x2="{el.x + STORE_W/2}" y2="{el.y + STORE_H/2}"')
            svg.append(f'          stroke="#7ee787" stroke-width="2" />')
            svg.append(f'    <text x="{el.x}" y="{el.y + 4}" text-anchor="middle"')
            svg.append(f'          fill="#7ee787" font-size="11">{escape_xml(el.label)}</text>')
            svg.append('  </g>')

    # Legend
    svg.append('')
    svg.append('  <!-- Legend -->')
    ly = height - 30
    svg.append(f'  <rect x="50" y="{ly-6}" width="16" height="16" fill="#1a2332" stroke="#58a6ff" stroke-width="1.5" />')
    svg.append(f'  <text x="72" y="{ly+5}" fill="#8b949e" font-size="10">External Entity</text>')
    svg.append(f'  <circle cx="208" cy="{ly+2}" r="8" fill="#1a2332" stroke="#d2a8ff" stroke-width="1.5" />')
    svg.append(f'  <text x="222" y="{ly+5}" fill="#8b949e" font-size="10">Process</text>')
    svg.append(f'  <line x1="320" y1="{ly-2}" x2="350" y2="{ly-2}" stroke="#7ee787" stroke-width="1.5" />')
    svg.append(f'  <line x1="320" y1="{ly+8}" x2="350" y2="{ly+8}" stroke="#7ee787" stroke-width="1.5" />')
    svg.append(f'  <text x="356" y="{ly+5}" fill="#8b949e" font-size="10">Data Store</text>')

    svg.append('')
    svg.append('</svg>')

    return '\n'.join(svg)


def generate_yourdon_dfd(pl_paths: list[str], svg_path: str | None = None) -> str:
    """Generate a Yourdon DFD from Prolog IR files."""
    elements, flows = extract_dfd_from_prolog(pl_paths)
    svg = generate_dfd_svg(elements, flows)

    if svg_path:
        Path(svg_path).write_text(svg)

    return svg


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pl_paths = [sys.argv[1]]
        # Load additional IR files from the same directory
        pl_dir = Path(sys.argv[1]).parent
        for extra in ['http_sse_session.pl', 'connection_acceptor.pl', 'process_creation.pl']:
            extra_path = pl_dir / extra
            if extra_path.exists():
                pl_paths.append(str(extra_path))

        svg_path = sys.argv[2] if len(sys.argv) > 2 else None
        svg = generate_yourdon_dfd(pl_paths, svg_path)
        if not svg_path:
            print(svg)
    else:
        print("Usage: python bpd_to_svg_dfd.py <main.pl> [output.svg]")
