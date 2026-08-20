"""Tests for the run explorer's pure rendering helpers.

`to_dot` is tested rather than eyeballed because the graph is the one thing in the
explorer that is easy to get silently wrong: a malformed DOT string renders as an
empty box, not as an error.
"""

from __future__ import annotations

from viz.app import to_dot


def test_emits_a_node_and_an_edge() -> None:
    dot = to_dot(
        {"nodes": ["load", "score"], "edges": [{"from": "load", "to": "score"}]},
        {"load": "computed", "score": "disk"},
    )
    assert dot.startswith("digraph pipeline {")
    assert dot.rstrip().endswith("}")
    assert "n_load -> n_score;" in dot


def test_labels_carry_the_cache_status() -> None:
    dot = to_dot({"nodes": ["load"], "edges": []}, {"load": "memory"})
    assert "memory cache" in dot


def test_unknown_status_still_renders() -> None:
    """A run from an older format must not produce a broken diagram."""
    dot = to_dot({"nodes": ["load"], "edges": []}, {})
    assert "unknown" in dot
    assert "n_load" in dot


def test_punctuated_node_names_become_valid_identifiers() -> None:
    """DOT identifiers cannot contain hyphens or dots; node names can."""
    dot = to_dot({"nodes": ["text-enhancer.v2"], "edges": []}, {})
    assert "n_text_enhancer_v2" in dot
    # The human-readable name survives in the label.
    assert "text-enhancer.v2" in dot


def test_empty_graph_is_valid_dot() -> None:
    dot = to_dot({"nodes": [], "edges": []}, {})
    assert dot.startswith("digraph pipeline {")
    assert dot.rstrip().endswith("}")
