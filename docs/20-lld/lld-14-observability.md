# LLD 14: Observability and Evaluation (M13)

## Summary

Formalize instrumentation, metric tracking, and evaluation runners to ensure translation quality is measurable and regressions are visible.

## Public Interfaces

Python modules:

- `tracking.mlflow.track_run_metadata()`
- `tracking.evaluation.run_benchmark()`
- `tracking.evaluation.score_fidelity()`

Metrics:

- latency
- retry counts
- glossary consistency
- fidelity flag counts
- evaluation scores (fidelity, terminology, readability)

## Data Flow

1. Orchestration emits events for every major transition.
2. `tracking.mlflow` captures these events and logs parameters, metrics, and artifacts to MLflow.
3. For evaluation, the benchmark runner executes translation on a "Golden Set" of difficult paragraphs.
4. Evaluation models score the outputs against the golden-set ground truth.
5. Quality trends are visualized in MLflow or the TUI.

## Validation Ownership

- tracking must not block core workflow execution
- evaluation scores are derived artifacts for inspection, not authority truth

## Resume And Rerun

- evaluation runs are separate from production runs
- metrics are append-only to ensure history is preserved

## Tests

- MLflow logging of metadata and artifacts
- evaluation runner execution on dummy benchmark data
- metric calculation accuracy (e.g., consistency rates)
