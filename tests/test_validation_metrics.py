"""Tests for independent benchmark statistics."""

from __future__ import annotations

import pytest

from src.validation.metrics import binary_metrics, exact_mcnemar, wilson_interval


def test_binary_metrics_known_confusion_matrix() -> None:
    metrics = binary_metrics(
        [True, True, False, False],
        [True, False, True, False],
    )
    assert metrics["confusion"] == {"tp": 1, "tn": 1, "fp": 1, "fn": 1}
    assert metrics["sensitivity"] == 0.5
    assert metrics["specificity"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["matthews_correlation_coefficient"] == 0.0


def test_wilson_interval_contains_observed_rate() -> None:
    lower, upper = wilson_interval(8, 10)
    assert lower < 0.8 < upper
    assert 0.0 <= lower <= upper <= 1.0


def test_exact_mcnemar_detects_paired_advantage() -> None:
    labels = [True] * 10
    first = [True] * 10
    second = [False] * 10
    comparison = exact_mcnemar(labels, first, second)
    assert comparison["first_only_correct"] == 10
    assert comparison["second_only_correct"] == 0
    assert comparison["p_value_two_sided"] == pytest.approx(0.001953125)


def test_metrics_reject_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        binary_metrics([True], [])
