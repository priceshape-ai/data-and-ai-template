---
name: add-pipeline-node
description: Add, remove, or rewire a step in this project's pipeline DAG — a loader, featurizer, scorer, ranker, classifier, tagger, or any other node. Use whenever the user wants a new pipeline stage, another ensemble member, a different model or embedding backend tried, a step disabled, or `pipelines/build.py` extended — including vague asks like "try adding X as another step", "can we test a different model here", or "drop that stage".
---

# Adding a node to the pipeline

The DAG engine is generic, so a new node needs **no change to the engine**.
Three files, in this order.

## 1. The component — `src/core/components/<name>.py`

A node is a callable whose keyword parameters are named after the nodes it depends
on, returning a `NodeResult`.

```python
class Ranker:
    def __init__(self, cfg: RankerConfig) -> None:
        self.cfg = cfg  # config only — nothing heavy

    def __call__(self, featurize: NodeResult) -> NodeResult:
        model = _load(self.cfg.model_name)  # lazily, on first call
        ...
        return NodeResult(items=scored, metrics={"mean_score": float(mean)})
```

Two rules the cache imposes, both non-negotiable:

- **Never write to `self`.** The cache key hashes `vars(self)`, so a node that
  mutates itself never hits its cache again.
- **Never load a model in `__init__`.** Instance state is part of the key, and it
  makes graph construction slow for no reason.

## 2. The config — `src/core/config/hyperparameters.py`

Add a frozen dataclass and hang it off `Config`. Use `Literal` for anything with a
fixed set of valid values — a misspelled model name should be a type error, not a
surprise three stages in.

```python
@dataclass(frozen=True)
class RankerConfig:
    model_name: EmbeddingModel = "BAAI/bge-m3"
    top_k: int = 10
    resources: NodeResources = field(
        default_factory=lambda: NodeResources(cpu_request="2", memory_request="8G")
    )
```

`resources` is what lets the same graph run on Kubeflow — locally it is ignored, on
KFP it becomes the pod's request. A GPU node declares that here, not in a manifest.

## 3. The wiring — `pipelines/build.py`

```python
rank = dag.add_node("rank", Ranker(config.ranker), depends_on=featurize)
```

The parameter name in `__call__` must match the upstream node's name.

## Then

```bash
make check                  # types and the import boundary
uv run pipeline             # the new node computes, downstream invalidates
```

Everything downstream of a new or changed node recomputes automatically — nobody
maintains a stage list. If your new node reports `[cache hit: disk]` on its first
run, something is wrong; see the `debug-pipeline-cache` skill.

## Removing a node

Delete the `add_node` line in `build.py` first and run the pipeline to confirm
nothing else depended on it. Then remove the component and its config. Leaving a
config section behind is harmless but misleading.
