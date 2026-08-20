"""The source node of the pipeline: get records out of .data/ and into memory.

Replace `_SAMPLE` and `__call__` with the project's real dataset. Everything
downstream only relies on the node returning a `NodeResult` whose `items` are
dicts, so swapping in a HuggingFace `load_from_disk`, a Parquet read or a
ClickHouse query is a change to this file alone.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from project_name.config import CONFIG, LoaderConfig
from project_name.result import NodeResult

logger = logging.getLogger(__name__)

# Lets `uv run pipeline` work on a fresh clone, before anyone has run `dvc pull`.
# Delete it once the project has real data.
_SAMPLE: list[dict[str, Any]] = [
    {"id": 1, "title": "Wireless over-ear headphones", "label": "audio"},
    {"id": 2, "title": "Mechanical keyboard, brown switches", "label": "input"},
    {"id": 3, "title": "27-inch 4K IPS monitor", "label": "display"},
    {"id": 4, "title": "USB-C docking station, dual HDMI", "label": "accessory"},
    {"id": 5, "title": "Noise-cancelling earbuds", "label": "audio"},
]


class DatasetLoader:
    """Reads a JSONL dataset from `.data/`, falling back to a built-in sample.

    Node configs are held on `self.cfg` and nowhere else. `pipelines/dag.py`
    fingerprints `vars(self)` to decide whether a cached result is still valid,
    so anything stored on the instance must be cheap and JSON-representable —
    load models lazily inside `__call__`, never in `__init__`.
    """

    def __init__(self, cfg: LoaderConfig) -> None:
        self.cfg = cfg

    def __call__(self) -> NodeResult:
        path = CONFIG.paths.data_root / self.cfg.source

        if path.exists():
            with path.open() as f:
                records = [json.loads(line) for line in f if line.strip()]
            logger.info("Loaded %d records from %s", len(records), path)
        else:
            records = list(_SAMPLE)
            logger.warning(
                "%s not found — falling back to the %d-record built-in sample. "
                "Run `make dvc-pull` to fetch the real dataset.",
                path,
                len(records),
            )

        if self.cfg.limit is not None:
            records = records[: self.cfg.limit]

        return NodeResult(items=records, metrics={"n_records": float(len(records))})
