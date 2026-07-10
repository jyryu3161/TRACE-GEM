"""Dependency-light binary classification statistics with uncertainty."""

from __future__ import annotations

import math
from collections.abc import Sequence


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    """Return a two-sided Wilson score interval as ``[lower, upper]``."""
    if total <= 0:
        return [0.0, 1.0]
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = proportion + z * z / (2.0 * total)
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total))
    return [max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)]


def binary_metrics(labels: Sequence[bool], predictions: Sequence[bool]) -> dict[str, object]:
    """Compute confusion counts, point metrics, and Wilson intervals."""
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions must have the same length")
    if not labels:
        raise ValueError("at least one benchmark item is required")

    tp = sum(label and prediction for label, prediction in zip(labels, predictions, strict=True))
    tn = sum(
        not label and not prediction for label, prediction in zip(labels, predictions, strict=True)
    )
    fp = sum(
        not label and prediction for label, prediction in zip(labels, predictions, strict=True)
    )
    fn = sum(
        label and not prediction for label, prediction in zip(labels, predictions, strict=True)
    )

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    sensitivity = ratio(tp, tp + fn)
    specificity = ratio(tn, tn + fp)
    precision = ratio(tp, tp + fp)
    npv = ratio(tn, tn + fn)
    f1 = ratio(2 * tp, 2 * tp + fp + fn)
    balanced = (
        (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None
        else None
    )
    mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = (tp * tn - fp * fn) / mcc_denominator if mcc_denominator else None

    return {
        "n": len(labels),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "sensitivity": sensitivity,
        "sensitivity_ci95": wilson_interval(tp, tp + fn),
        "specificity": specificity,
        "specificity_ci95": wilson_interval(tn, tn + fp),
        "precision": precision,
        "precision_ci95": wilson_interval(tp, tp + fp),
        "negative_predictive_value": npv,
        "f1": f1,
        "balanced_accuracy": balanced,
        "matthews_correlation_coefficient": mcc,
    }


def exact_mcnemar(
    labels: Sequence[bool], first: Sequence[bool], second: Sequence[bool]
) -> dict[str, float | int]:
    """Exact two-sided McNemar comparison of two paired classifiers."""
    if not (len(labels) == len(first) == len(second)):
        raise ValueError("paired arrays must have the same length")
    first_only = 0
    second_only = 0
    for label, a, b in zip(labels, first, second, strict=True):
        a_correct = a == label
        b_correct = b == label
        first_only += int(a_correct and not b_correct)
        second_only += int(b_correct and not a_correct)
    discordant = first_only + second_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(first_only, second_only) + 1)) / (
            2**discordant
        )
        p_value = min(1.0, 2.0 * tail)
    return {
        "first_only_correct": first_only,
        "second_only_correct": second_only,
        "discordant": discordant,
        "p_value_two_sided": p_value,
    }
