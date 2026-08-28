"""S3 / MinIO object storage helpers, used from the submitting machine.

The in-pod equivalents are inlined into `node_runner.py` rather than imported
from here — see the note in that file for why.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _client(endpoint_url: str | None = None):
    import boto3

    return boto3.client("s3", endpoint_url=endpoint_url or None)


def ensure_bucket(bucket: str, endpoint_url: str | None = None) -> None:
    """Create `bucket` if it is missing. Idempotent."""
    import botocore.exceptions

    s3 = _client(endpoint_url)
    try:
        s3.head_bucket(Bucket=bucket)
    except botocore.exceptions.ClientError:
        logger.info("Creating bucket %s", bucket)
        s3.create_bucket(Bucket=bucket)


def s3_upload(
    local_path: Path | str, bucket: str, key: str, endpoint_url: str | None = None
) -> None:
    _client(endpoint_url).upload_file(str(local_path), bucket, key)
    logger.debug("Uploaded %s → s3://%s/%s", local_path, bucket, key)


def s3_download(
    bucket: str, key: str, local_path: Path | str, endpoint_url: str | None = None
) -> None:
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    _client(endpoint_url).download_file(bucket, key, str(local_path))
    logger.debug("Downloaded s3://%s/%s → %s", bucket, key, local_path)


def s3_exists(bucket: str, key: str, endpoint_url: str | None = None) -> bool:
    import botocore.exceptions

    try:
        _client(endpoint_url).head_object(Bucket=bucket, Key=key)
        return True
    except botocore.exceptions.ClientError:
        return False


def s3_sync_up(
    local_dir: Path | str,
    bucket: str,
    prefix: str,
    endpoint_url: str | None = None,
) -> int:
    """Upload a directory tree. Returns the number of files sent."""
    root = Path(local_dir)
    if not root.is_dir():
        raise NotADirectoryError(root)
    s3 = _client(endpoint_url)
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            key = f"{prefix.rstrip('/')}/{path.relative_to(root).as_posix()}"
            s3.upload_file(str(path), bucket, key)
            count += 1
    logger.info("Uploaded %d files from %s → s3://%s/%s", count, root, bucket, prefix)
    return count
