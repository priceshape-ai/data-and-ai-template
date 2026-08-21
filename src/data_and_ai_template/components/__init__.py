"""One module per pipeline step.

A component is any callable whose keyword arguments are named after the DAG nodes
it depends on, and which returns a `NodeResult`. `pipelines/build.py` wires them
together; they know nothing about the DAG, MLflow or Kubeflow, which is what makes
them plain unit-testable objects.
"""

from data_and_ai_template.components.featurizer import Featurizer
from data_and_ai_template.components.scorer import Scorer

__all__ = ["Featurizer", "Scorer"]
