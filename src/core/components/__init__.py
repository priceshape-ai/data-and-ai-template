"""One module per pipeline step.

A component is any callable whose keyword arguments are named after the DAG nodes
it depends on, and which returns a `NodeResult`. `pipelines/build.py` wires them
together; they know nothing about the DAG or MLflow, which is what makes
them plain unit-testable objects.
"""

from core.components.featurizer import Featurizer
from core.components.scorer import Scorer

__all__ = ["Featurizer", "Scorer"]
