"""Ethical evaluation framework (schemas, metrics, runner).

This package computes metrics ONLY from consented, approved, labelled data that
a human supplies. It ships no dataset and produces no accuracy or fairness
claim of its own. See docs/EVALUATION.md.
"""
NOT_VALIDATED_NOTICE = "Not validated on real classroom footage."
NO_RESULTS_NOTICE = "No verified accuracy or fairness result is currently available."


def validation_status() -> dict:
    return {
        "validated": False,
        "headline": NOT_VALIDATED_NOTICE,
        "detail": NO_RESULTS_NOTICE,
        "fairness": "NOT_EVALUATED",
        "how_to_evaluate": "Prepare a consented dataset manifest with ground-truth labels and run scripts/evaluate.py (docs/EVALUATION.md).",
    }
