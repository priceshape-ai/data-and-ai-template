---
name: debug-pipeline-cache
description: Diagnose why the pipeline produced unchanged or stale-looking results after an edit. Use whenever the user says results did not change, a node was skipped, metrics are identical between runs, "it is not rerunning", "did it use the cache?", a fix appears to have had no effect — and before concluding that any experiment or ablation "made no difference", since a stale cache is the likeliest explanation.
---

# Why results did not change

Rule out the cache before concluding an edit had no effect.

## First: did the node run at all?

```
INFO pipelines.dag: [cache hit: disk]    featurize    key=3fd5ece5bd40
INFO pipelines.dag: [computed]           featurize    key=8d2e9df5ead9
```

`[cache hit: disk]` means it did not run. If that is the node you edited, the edit
did not change its cache key.

## What the key is made of

A node's key hashes three things:

1. its `__call__` bytecode,
2. its instance state, `vars(self)`,
3. its upstream nodes' keys.

So editing a component, changing a hyperparameter, or invalidating anything upstream
all invalidate it transitively. Nobody maintains a stage list.

## What that misses, and it matters

**Anything not in those three inputs is invisible to the cache.** In particular:

- A file the node reads whose *path* did not change. Editing `.data/raw/x.jsonl` in
  place does not change `LoaderConfig.source`, so the loader keeps its key and
  serves a stale result. Rename the file, or use `--no-cache`.
- A change in a helper module the node imports but does not hold on `self` — the
  bytecode hashed is `__call__`'s own, not its callees'.
- An environment variable read inside `__call__`.

These are the cases where an ablation silently concludes "no difference".

## Forcing a real run

```bash
uv run pipeline --no-cache          # recompute everything
rm -rf .dag_cache                   # or discard the cache entirely
```

## The opposite problem: nothing ever caches

A node that reports `[computed]` on every run despite no edits is mutating itself.
The cache key hashes `vars(self)`, so a node that writes to `self` changes its own
fingerprint and can never hit its cache.
`tests/unit/test_dag.py::test_mutating_instance_state_invalidates_own_cache` pins
this down. Hold the config; load models lazily inside `__call__`.
