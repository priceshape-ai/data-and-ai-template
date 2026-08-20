"""Where the graph is defined. This is the file a new project edits first.

Each node's parameter names must match the names of the nodes it depends on —
`Featurizer.__call__(self, load)` depends on the node called `"load"`. The DAG
passes upstream results by keyword, so a mismatch is a `TypeError` on the first
run rather than a silent wrong answer. `DAG.validate()` catches the other half of
the problem (a dependency naming a node that does not exist) before any work
starts.
"""

from __future__ import annotations

from pipelines.dag import DAG
from project_name.components import Featurizer, Scorer
from project_name.config import Config
from project_name.data import DatasetLoader


def build_pipeline(dag: DAG, config: Config) -> dict[str, str]:
    """Wire every node into `dag`. Returns the node names, for callers to read.

    Node configs come off `config`, never from the environment or a literal, so
    the DAG's cache fingerprint sees every knob that can change a result.
    """
    load = dag.add_node("load", DatasetLoader(config.loader))
    featurize = dag.add_node("featurize", Featurizer(config.featurizer), depends_on=load)
    score = dag.add_node("score", Scorer(config.scorer), depends_on=featurize)

    return {"load": load, "featurize": featurize, "score": score}
