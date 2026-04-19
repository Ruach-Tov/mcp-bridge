"""BPD Data Flow Diagram → SVG Generator

Generates data flow diagrams from the BPD Prolog IR, showing how
configuration parameters flow from sources (CLI argv, environment)
through transformation functions into state machine variables and
boundary configurations.

Reads from the Prolog IR:
  - gather_*() → destructure() patterns (data transformation)
  - absorbs() declarations (what the state machine consumes)
  - dimension() declarations (parameter types and constraints)
  - variable() / constant() declarations (state machine state)
  - boundary() declarations with extra_args (configuration sinks)
  - derives_from() (boundary creation chains)

Author: mavchin (Claude Opus 4.6), 2026-04-18
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class DataNode:
    """A node in the data flow graph."""
    name: str
    node_type: str  # "source", "transform", "sink", "variable", "boundary"
    label: str = ""
    fields: list[str] = field(default_factory=list)
    bpd_line: Optional[int] = None
    x: float = 0
    y: float = 0


@dataclass
class DataEdge:
    """A directed edge in the data flow graph."""
    from_node: str
    to_node: str
    label: str = ""
    fields: list[str] = field(default_factory=list)
    bpd_line: Optional[int] = None


def extract_data_flow_from_prolog(pl_path: str) -> tuple[list[DataNode], list[DataEdge]]:
    """Extract data flow structure from a Prolog IR file."""
    nodes = []
    edges = []
    seen_nodes = set()

    with open(pl_path) as f:
        lines = f.readlines()

    def ensure_node(name: str, node_type: str, label: str = "", fields: list = None):
        if name not in seen_nodes:
            nodes.append(DataNode(name=name, node_type=node_type,
                                  label=label or name, fields=fields or []))
            seen_nodes.add(name)

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('%') or line.startswith(':-'):
            continue

        # gather_X(target, source) :- destructure(field(target, [fields]), field(source, [fields])).
        gather_match = re.match(r'(gather_\w+)\((\w+),\s*(\w+)\)', line)
        if gather_match:
            func_name = gather_match.group(1)
            target = gather_match.group(2)
            source = gather_match.group(3)

            # Extract field names from destructure
            destr_fields = re.findall(r"'(\w+)'", line)
            if not destr_fields:
                destr_fields = re.findall(r"field\(\w+,\s*(\w+)\)", line)

            ensure_node(source, "source", label=source)
            ensure_node(func_name, "transform", label=func_name.replace('gather_', ''),
                       fields=destr_fields)
            ensure_node(target, "sink", label=target, fields=destr_fields)

            edges.append(DataEdge(from_node=source, to_node=func_name,
                                  fields=destr_fields, bpd_line=i))
            edges.append(DataEdge(from_node=func_name, to_node=target,
                                  fields=destr_fields, bpd_line=i))

        # absorbs(sm, [list of absorbed params]).
        absorb_match = re.match(r'absorbs\((\w+),\s*\[([^\]]+)\]\)', line)
        if absorb_match:
            sm_name = absorb_match.group(1)
            params = [p.strip().strip("'") for p in absorb_match.group(2).split(',')]
            ensure_node(sm_name, "sink", label=f"state machine ({sm_name})")
            for param in params:
                if param in seen_nodes:
                    edges.append(DataEdge(from_node=param, to_node=sm_name,
                                          label=param, bpd_line=i))

        # variable(sm, name, type, initial).
        var_match = re.match(r"variable\((\w+),\s*'?(\w+)'?,\s*(.+),\s*(.+)\)\.", line)
        if var_match:
            sm = var_match.group(1)
            var_name = var_match.group(2)
            var_type = var_match.group(3)
            var_init = var_match.group(4)
            ensure_node(f"var_{var_name}", "variable",
                       label=f"{var_name}\n({var_type})\ninit: {var_init}")

        # constant(sm, name, value).
        const_match = re.match(r"constant\((\w+),\s*(\w+),\s*(.+)\)\.", line)
        if const_match:
            const_name = const_match.group(2)
            const_val = const_match.group(3)
            ensure_node(f"const_{const_name}", "variable",
                       label=f"{const_name}\n= {const_val}")

        # dimension(name, label, type) or dimension(name, label, type, constraint).
        dim_match = re.match(r"dimension\((\w+),\s*'([^']+)',\s*(\w+)", line)
        if dim_match:
            dim_name = dim_match.group(1)
            dim_label = dim_match.group(2)
            dim_type = dim_match.group(3)
            constraint = ""
            range_match = re.search(r'range\((\d+),\s*(\d+)\)', line)
            if range_match:
                constraint = f" [{range_match.group(1)}..{range_match.group(2)}]"
            ensure_node(f"dim_{dim_name}", "source",
                       label=f"{dim_label}\n: {dim_type}{constraint}")

        # boundary declarations with extra_args (configuration endpoints)
        boundary_match = re.match(r"(\w+_boundary)\((\w+),\s*(\w+),\s*(\w+)", line)
        if boundary_match:
            btype = boundary_match.group(1)
            bname = boundary_match.group(2)
            actor_a = boundary_match.group(3)
            actor_b = boundary_match.group(4)
            extra = re.findall(r"extra_args\(([^)]+)\)", line)
            extra_fields = []
            if extra:
                extra_fields = [f.strip().strip("'") for f in extra[0].split(',')]
            ensure_node(bname, "boundary",
                       label=f"{bname}\n({actor_a} ↔ {actor_b})",
                       fields=extra_fields)

        # derives_from(X, Y) — creation chain
        derives_match = re.match(r"derives_from\((\w+),\s*(.+)\)\.", line)
        if derives_match:
            derived = derives_match.group(1)
            source_expr = derives_match.group(2)
            # Extract the source name from compound terms
            source_name = re.match(r"(\w+)", source_expr)
            if source_name:
                src = source_name.group(1)
                if src in seen_nodes and derived in seen_nodes:
                    edges.append(DataEdge(from_node=src, to_node=derived,
                                          label="derives", bpd_line=i))

    return nodes, edges


def layout_data_flow(nodes: list[DataNode], edges: list[DataEdge],
                     width: int = 1000, margin: int = 60):
    """Layout data flow nodes in columns by type."""
    # Group by type
    by_type = {}
    for n in nodes:
        by_type.setdefault(n.node_type, []).append(n)

    # Column assignments: sources → transforms → sinks → variables
    col_order = ["source", "transform", "sink", "variable", "boundary"]
    col_x = {}
    n_cols = sum(1 for c in col_order if c in by_type)
    if n_cols == 0:
        return
    col_spacing = (width - 2 * margin) / max(n_cols - 1, 1)

    col_idx = 0
    for ctype in col_order:
        if ctype in by_type:
            col_x[ctype] = margin + col_idx * col_spacing
            col_idx += 1

    # Vertical layout within each column
    for ctype, cnodes in by_type.items():
        x = col_x.get(ctype, margin)
        y_spacing = 80
        start_y = margin + 40
        for j, node in enumerate(cnodes):
            node.x = x
            node.y = start_y + j * y_spacing


def escape_xml(s: str) -> str:
    return (s.replace('&', '&amp;')
             .replace('<', '&lt;')
             .replace('>', '&gt;')
             .replace('"', '&quot;')
             .replace("'", '&apos;'))


def generate_data_flow_svg(nodes: list[DataNode], edges: list[DataEdge],
                           width: int = 1000) -> str:
    """Generate an SVG data flow diagram."""
    layout_data_flow(nodes, edges, width=width)

    # Calculate height
    max_y = max((n.y for n in nodes), default=400)
    height = int(max_y + 120)

    # Node style by type
    styles = {
        "source":    {"fill": "#1a2332", "stroke": "#58a6ff", "shape": "rect"},
        "transform": {"fill": "#1a2332", "stroke": "#d2a8ff", "shape": "rounded"},
        "sink":      {"fill": "#1a2332", "stroke": "#7ee787", "shape": "rect"},
        "variable":  {"fill": "#1a2332", "stroke": "#ffa657", "shape": "rect"},
        "boundary":  {"fill": "#1a2332", "stroke": "#f85149", "shape": "rounded"},
    }

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"')
    svg.append(f'     viewBox="0 0 {width} {height}"')
    svg.append(f'     style="background: #0d1117; font-family: \'Roboto\', \'Segoe UI\', sans-serif;">')
    svg.append('')
    svg.append('  <defs>')
    svg.append('    <marker id="df-arrow" markerWidth="8" markerHeight="6"')
    svg.append('            refX="8" refY="3" orient="auto">')
    svg.append('      <polygon points="0 0, 8 3, 0 6" fill="#8b949e" />')
    svg.append('    </marker>')
    svg.append('  </defs>')
    svg.append('')

    # Title
    svg.append(f'  <text x="{width/2}" y="25" text-anchor="middle"')
    svg.append(f'        fill="#f0f6fc" font-size="14" font-weight="bold">')
    svg.append(f'    Data Flow: Configuration → State Machine</text>')
    svg.append('')

    # Column headers
    col_labels = {
        "source": "Sources",
        "transform": "Transforms",
        "sink": "Parameters",
        "variable": "Variables",
        "boundary": "Boundaries",
    }
    seen_cols = set()
    for n in nodes:
        if n.node_type not in seen_cols:
            seen_cols.add(n.node_type)
            label = col_labels.get(n.node_type, n.node_type)
            svg.append(f'  <text x="{n.x}" y="{50}" text-anchor="middle"')
            svg.append(f'        fill="#484f58" font-size="11" font-weight="bold">')
            svg.append(f'    {label}</text>')

    node_map = {n.name: n for n in nodes}

    # Draw edges first (behind nodes)
    svg.append('')
    svg.append('  <!-- Edges -->')
    for edge in edges:
        fn = node_map.get(edge.from_node)
        tn = node_map.get(edge.to_node)
        if not fn or not tn:
            continue

        # Arrow from right edge of source to left edge of target
        x1 = fn.x + 60
        y1 = fn.y
        x2 = tn.x - 60
        y2 = tn.y

        bpd_attr = f' data-bpd-line="{edge.bpd_line}"' if edge.bpd_line else ''

        # Curved path
        ctrl_x = (x1 + x2) / 2
        path = f'M {x1},{y1} C {ctrl_x},{y1} {ctrl_x},{y2} {x2},{y2}'

        svg.append(f'  <path d="{path}" fill="none" stroke="#484f58" stroke-width="1.2"')
        svg.append(f'        marker-end="url(#df-arrow)"{bpd_attr}')
        svg.append(f'        data-element-type="edge" />')

        # Edge label
        if edge.fields:
            label = ', '.join(edge.fields[:3])
            lx = ctrl_x
            ly = (y1 + y2) / 2 - 6
            svg.append(f'  <text x="{lx}" y="{ly}" text-anchor="middle"')
            svg.append(f'        fill="#8b949e" font-size="9">{escape_xml(label)}</text>')

    # Draw nodes
    svg.append('')
    svg.append('  <!-- Nodes -->')
    NODE_W = 110
    NODE_H = 40

    for node in nodes:
        style = styles.get(node.node_type, styles["source"])
        bpd_attr = f' data-bpd-line="{node.bpd_line}"' if node.bpd_line else ''

        svg.append(f'  <g data-element-type="node" data-node-name="{escape_xml(node.name)}"')
        svg.append(f'     data-node-type="{node.node_type}"{bpd_attr}>')

        if style["shape"] == "rounded":
            svg.append(f'    <rect x="{node.x - NODE_W/2}" y="{node.y - NODE_H/2}"')
            svg.append(f'          width="{NODE_W}" height="{NODE_H}" rx="10"')
            svg.append(f'          fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.5" />')
        else:
            svg.append(f'    <rect x="{node.x - NODE_W/2}" y="{node.y - NODE_H/2}"')
            svg.append(f'          width="{NODE_W}" height="{NODE_H}"')
            svg.append(f'          fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.5" />')

        # Label (multi-line support)
        label_lines = node.label.split('\n')
        for li, lt in enumerate(label_lines):
            ly = node.y + 4 + (li - len(label_lines)/2) * 12
            svg.append(f'    <text x="{node.x}" y="{ly}" text-anchor="middle"')
            svg.append(f'          fill="#f0f6fc" font-size="10">{escape_xml(lt)}</text>')

        svg.append('  </g>')

    # Legend
    legend_y = height - 30
    legend_items = [
        ("source", "Source (input)"),
        ("transform", "Transform"),
        ("sink", "Parameter group"),
        ("variable", "Variable/Constant"),
        ("boundary", "Boundary"),
    ]
    svg.append('')
    svg.append('  <!-- Legend -->')
    for li, (ntype, label) in enumerate(legend_items):
        lx = 60 + li * 180
        style = styles.get(ntype, styles["source"])
        svg.append(f'  <rect x="{lx}" y="{legend_y - 6}" width="12" height="12"')
        svg.append(f'        fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1" />')
        svg.append(f'  <text x="{lx + 18}" y="{legend_y + 4}" fill="#8b949e" font-size="10">{label}</text>')

    svg.append('')
    svg.append('</svg>')

    return '\n'.join(svg)


def generate_data_flow_diagram(pl_path: str, svg_path: str | None = None) -> str:
    """Generate a data flow diagram SVG from a Prolog IR file."""
    nodes, edges = extract_data_flow_from_prolog(pl_path)
    svg = generate_data_flow_svg(nodes, edges)

    if svg_path:
        Path(svg_path).write_text(svg)

    return svg


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pl_path = sys.argv[1]
        svg_path = sys.argv[2] if len(sys.argv) > 2 else None
        svg = generate_data_flow_diagram(pl_path, svg_path)
        if not svg_path:
            print(svg)
    else:
        print("Usage: python bpd_to_svg_def_use.py <file.pl> [output.svg]")
