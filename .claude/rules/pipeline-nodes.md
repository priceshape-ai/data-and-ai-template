---
paths:
  - "pipelines/**/*.py"
  - "src/**/components/**/*.py"
  - "src/**/data/**/*.py"
---

# Writing pipeline nodes

## The node contract

A node is any callable whose keyword parameters are named after the nodes it
depends on. It returns a `NodeResult`. It is registered in `pipelines/build.py`:

```python
score = dag.add_node("score", Scorer(config.scorer), depends_on=featurize)
```

Adding a node requires **no change to `dag.py`**. The engine is generic.

## The cache key, and the two rules that follow from it

A node's key hashes its `__call__` bytecode, its instance state (`vars(self)`), and
its upstream nodes' keys. Nobody maintains a stage list: edit a component, change a
hyperparameter, or invalidate anything upstream, and everything downstream
invalidates transitively.

**A node must not write to `self`.** Incrementing a counter on the instance changes
its own fingerprint, so it never hits its cache again.
`tests/unit/test_dag.py::test_mutating_instance_state_invalidates_own_cache` pins
this down.

**Load models lazily inside `__call__`.** Anything held on the instance is part of
the key, so a model loaded in `__init__` is both slow to construct and wrong to
fingerprint. Hold the config; load on first call.

Keep instance state cheap and JSON-representable for the same reason.

## Debugging "my change did nothing"

Rule out the cache before concluding a change had no effect. If the log says
`[cache hit: disk]` for the node you edited, it did not run. Either the edit did not
change `__call__` or `vars(self)`, or you are looking at the wrong node.
`uv run pipeline --no-cache` forces a full recompute.
