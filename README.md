# priceshape-ml

The machinery every PriceShape Data & AI project shares: a DAG that runs one graph
definition either locally or on Kubeflow, the reproducibility gate, MLflow run
logging, and the DVC sync.

It knows nothing about any particular project. What the steps are and how they are
configured arrive as arguments, which is what lets one copy serve every repository —
and what makes a bug fix here a version bump rather than a copy-paste into each one.

```bash
uv add "priceshape-ml[tracking,kubeflow,data] @ git+ssh://git@github.com/priceshape-ai/priceshape-ml@v0.1.0"
```

## What a project provides

```python
# pipelines/runner.py — the whole wiring
from core.config import CONFIG
from pipelines.build import build_pipeline
from priceshape_ml import run


def main() -> int:
    return run(build_pipeline, CONFIG)
```

`config` is duck-typed: the engine reads `log_level`, `paths`, `mlflow` and
`kubeflow` off it and ignores everything else, so a project hangs its own
hyperparameters beside those without this package needing to know.

## Extras

| Extra | Brings | Needed for |
| --- | --- | --- |
| `tracking` | `mlflow-skinny` | recording runs |
| `kubeflow` | `kfp` | submitting to the cluster |
| `data` | `dvc[s3]` | `priceshape_ml.dvc_sync` |

The base install is `boto3` and nothing else, so a project that only wants the DAG
does not inherit a cluster SDK to get it.

## Releasing

Tag it. Consumers pin the tag, so nothing moves under them until they bump.

```bash
git tag v0.2.0 && git push --tags
```
