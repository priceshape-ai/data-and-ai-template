"""One-time setup: put the dataset and model weights where the cluster can see them.

Kubeflow pods have no access to your laptop's `.data/` and `.models/`, so before
the first submission those trees have to reach the object store the cluster reads.
Run this again whenever they change.

    python -m priceshape_ml.kubeflow.setup --upload-data --upload-models

A project reaches it through a one-line wrapper that supplies its own config:

    from priceshape_ml.kubeflow.setup import main
    from core.config import CONFIG
    raise SystemExit(main(CONFIG))

Credentials come from the environment, the same ones DVC uses:

    export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
    export KUBEFLOW_S3_ENDPOINT=http://localhost:9000   # MinIO

This is deliberately separate from `dvc push`. DVC versions these trees for
humans; this copies them into the bucket the pipeline pods read at run time. If
you would rather have one source of truth, drop this script and run `dvc pull`
in an init container instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from priceshape_ml.kubeflow.storage import ensure_bucket, s3_sync_up

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args(config: Any, argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bucket",
        default=config.kubeflow.s3_bucket,
        help="Target bucket (default: KUBEFLOW_S3_BUCKET).",
    )
    parser.add_argument("--upload-data", action="store_true", help="Sync .data/")
    parser.add_argument("--upload-models", action="store_true", help="Sync .models/")
    return parser.parse_args(argv)


def main(config: Any, argv: list[str] | None = None) -> int:
    args = parse_args(config, argv)
    if not (args.upload_data or args.upload_models):
        print(
            "Nothing to do — pass --upload-data and/or --upload-models.",
            file=sys.stderr,
        )
        return 2

    endpoint = config.kubeflow.s3_endpoint
    ensure_bucket(args.bucket, endpoint_url=endpoint)

    if args.upload_data:
        s3_sync_up(config.paths.data_root, args.bucket, "data", endpoint_url=endpoint)
    if args.upload_models:
        s3_sync_up(config.paths.models_root, args.bucket, "models", endpoint_url=endpoint)
    return 0


if __name__ == "__main__":  # pragma: no cover - needs a project's config
    raise SystemExit(
        "Run this through your project, which supplies the config:\n"
        "    python -c 'from priceshape_ml.kubeflow.setup import main; "
        "from core.config import CONFIG; raise SystemExit(main(CONFIG))' --upload-data"
    )
