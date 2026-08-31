"""Streamlit explorer for pipeline runs.

    make viz            # newest run
    make viz RUN=2026-08-20T09-14-02

Reads only what `priceshape_ml` wrote under `runs/<timestamp>/` — the graph,
each node's cache status, and the per-item JSONL traces. It never imports the DAG
or re-executes anything, so it stays usable while a pipeline is running and cannot
corrupt a run by being opened.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import streamlit as st

from core.config import CONFIG

RUNS_ROOT = CONFIG.paths.runs_root

# Fill colour per cache status. Deliberately not red/green: the distinction is
# "did this node do work", not "did it succeed", and colour-blind-safe hues keep
# that readable.
_STATUS_FILL = {
    "computed": "#cfe3f7",  # blue — actually ran
    "disk": "#e8e2d0",  # sand — reused from .dag_cache/
    "memory": "#ded9ef",  # lilac — reused within the process
}
_STATUS_LABEL = {
    "computed": "computed",
    "disk": "disk cache",
    "memory": "memory cache",
}


def list_runs() -> list[str]:
    """Run timestamps, newest first."""
    if not RUNS_ROOT.is_dir():
        return []
    return sorted((p.name for p in RUNS_ROOT.iterdir() if p.is_dir()), reverse=True)


@st.cache_data(show_spinner=False)
def load_json(path: str) -> Any:
    file = Path(path)
    if not file.is_file():
        return None
    return json.loads(file.read_text())


@st.cache_data(show_spinner=False)
def load_trace(path: str, limit: int = 2000) -> list[dict[str, Any]]:
    """Read a JSONL trace. Capped, because a trace can be millions of rows."""
    rows: list[dict[str, Any]] = []
    with Path(path).open() as f:
        for line in f:
            if len(rows) >= limit:
                break
            if line.strip():
                rows.append(json.loads(line))
    return rows


def to_dot(graph: dict[str, Any], status: dict[str, str]) -> str:
    """Render the DAG as Graphviz DOT, coloured by cache status.

    DOT rather than Mermaid because `st.graphviz_chart` accepts a DOT string and
    draws it in the browser, with no local Graphviz binary needed. Streamlit has no
    Mermaid renderer, so a Mermaid diagram could only ever be shown as source.
    """
    lines = [
        "digraph pipeline {",
        "  rankdir=LR;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11];',
        '  edge [color="#8a8a8a", arrowsize=0.7];',
    ]
    for node in graph.get("nodes", []):
        state = status.get(node, "")
        fill = _STATUS_FILL.get(state, "#eeeeee")
        label = _STATUS_LABEL.get(state, "unknown")
        lines.append(
            f'  {_ident(node)} [label="{node}\\n({label})", fillcolor="{fill}", color="#5a5a5a"];'
        )
    for edge in graph.get("edges", []):
        lines.append(f"  {_ident(edge['from'])} -> {_ident(edge['to'])};")
    lines.append("}")
    return "\n".join(lines)


def _ident(name: str) -> str:
    """DOT identifiers cannot contain punctuation."""
    return "n_" + "".join(c if c.isalnum() else "_" for c in name)


def main() -> None:
    st.set_page_config(page_title="Pipeline runs", layout="wide")
    st.title("Pipeline runs")

    runs = list_runs()
    if not runs:
        st.info(
            f"No runs found under `{RUNS_ROOT}`. Run the pipeline first:\n\n"
            "```\nuv run pipeline\n```"
        )
        return

    # A run passed on the command line (`make viz RUN=...`) preselects the picker.
    requested = sys.argv[1] if len(sys.argv) > 1 else None
    index = runs.index(requested) if requested in runs else 0
    run = st.sidebar.selectbox("Run", runs, index=index)
    run_dir = RUNS_ROOT / run

    graph = load_json(str(run_dir / "graph.json")) or {}
    status = load_json(str(run_dir / "cache_status.json")) or {}
    keys = load_json(str(run_dir / "cache_keys.json")) or {}

    computed = sum(1 for v in status.values() if v == "computed")
    cols = st.columns(3)
    cols[0].metric("Nodes", len(graph.get("nodes", [])))
    cols[1].metric("Computed", computed)
    cols[2].metric("From cache", len(status) - computed)

    st.subheader("Graph")
    if graph.get("nodes"):
        st.graphviz_chart(to_dot(graph, status), use_container_width=True)
    else:
        st.warning("No graph.json in this run.")

    st.subheader("Nodes")
    st.dataframe(
        [
            {
                "node": node,
                "status": status.get(node, "?"),
                "cache key": keys.get(node, ""),
            }
            for node in graph.get("nodes", [])
        ],
        width="stretch",
        hide_index=True,
    )

    traces = sorted(run_dir.glob("*_trace.jsonl"))
    if not traces:
        st.info("This run wrote no per-item traces.")
        return

    st.subheader("Traces")
    choice = st.selectbox("Trace", [p.name for p in traces])
    rows = load_trace(str(run_dir / choice))
    st.caption(f"Showing {len(rows)} rows (capped).")
    st.dataframe(rows, width="stretch")

    if rows:
        with st.expander("Inspect a single record"):
            idx = st.number_input("Row", min_value=0, max_value=len(rows) - 1, value=0, step=1)
            st.json(rows[int(idx)])


# Streamlit execs the script in a module it names "__main__", so this guard fires
# under `streamlit run` — and keeps `from viz.app import to_dot` in the tests from
# trying to render a page outside a Streamlit runtime.
if __name__ == "__main__":
    main()
