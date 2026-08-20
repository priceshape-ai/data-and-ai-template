"""Kubeflow backend for the DAG engine.

Nested under `pipelines/` rather than being its own root because it is a
dependency *of* the DAG engine: `pipelines/dag.py` imports `node_runner` to
compile the graph into KFP tasks.
"""
