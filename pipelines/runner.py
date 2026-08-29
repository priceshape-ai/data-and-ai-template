"""`uv run pipeline` — this project's entry point.

The run itself lives in `priceshape_ml`, which is the same in every project. All
that belongs here is the wiring: this project's config, and this project's graph.
"""

from __future__ import annotations

from priceshape_ml import run

from core.config import CONFIG
from pipelines.build import build_pipeline


def main(argv: list[str] | None = None) -> int:
    exit_code: int = run(build_pipeline, CONFIG, argv)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
