"""The one KFP component that runs every node.

`pipelines/dag.py` pickles each node's callable to object storage and compiles one
task per node, all using this single generic body. So adding a node to the graph
never means writing a new KFP component or rebuilding an image — which is the
reason the same `build_pipeline()` can target local execution and Kubeflow
without being written twice.

Two constraints shape this file, both from KFP lightweight components:

1. **Every import is inside the function.** KFP ships only the function's source
   to the pod, so module-level imports here would not exist at run time. That is
   also why the S3 helpers are inlined rather than imported from
   `pipelines/kubeflow/storage.py` — `pipelines/` is not in any image.

2. **The base image must be able to unpickle the callable.** The pickle references
   `project_name.components...`, so the image needs the package installed. Point
   `KUBEFLOW_BASE_IMAGE` at this project's own production image: it contains
   `src/` and nothing else, which is exactly what is needed. `boto3` arrives via
   the component's `packages_to_install`, so it need not be a production
   dependency.
"""

from __future__ import annotations


def node_runner_body(
    node_name: str,
    fn_key: str,
    upstream_names: str,  # JSON list of dependency node names
    result_prefix: str,  # e.g. "runs/2026-08-20T10-00-00/results"
    s3_bucket: str,
    s3_endpoint: str,
) -> None:
    """Download a node's callable and inputs, run it, upload the result.

    Skips the work entirely if the result object already exists, which makes a
    re-submitted pipeline resume rather than recompute — the object-storage
    equivalent of the local `.dag_cache/`.
    """
    import json
    import os
    import pickle
    import tempfile
    from pathlib import Path

    import boto3
    import botocore.exceptions

    endpoint = s3_endpoint or None
    if endpoint:
        os.environ.setdefault("S3_ENDPOINT_URL", endpoint)
    s3 = boto3.client("s3", endpoint_url=endpoint)

    def exists(key: str) -> bool:
        try:
            s3.head_object(Bucket=s3_bucket, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def download(key: str):
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as handle:
            path = Path(handle.name)
        try:
            s3.download_file(s3_bucket, key, str(path))
            with path.open("rb") as handle:
                return pickle.load(handle)
        finally:
            path.unlink(missing_ok=True)

    def upload(key: str, value) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as handle:
            pickle.dump(value, handle)
            path = Path(handle.name)
        try:
            s3.upload_file(str(path), s3_bucket, key)
        finally:
            path.unlink(missing_ok=True)

    result_key = f"{result_prefix}/{node_name}.pkl"
    if exists(result_key):
        print(f"[{node_name}] result already in object storage — skipping")
        return

    print(f"[{node_name}] loading callable from {fn_key}")
    fn = download(fn_key)

    inputs = {}
    for dep in json.loads(upstream_names):
        print(f"[{node_name}] loading upstream result: {dep}")
        inputs[dep] = download(f"{result_prefix}/{dep}.pkl")

    print(f"[{node_name}] running")
    result = fn(**inputs)

    upload(result_key, result)
    print(f"[{node_name}] wrote s3://{s3_bucket}/{result_key}")
