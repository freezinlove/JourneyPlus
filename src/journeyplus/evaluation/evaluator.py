from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

from journeyplus.contracts import DocumentLabel
from journeyplus.evaluation.schema import GoldDataset


@dataclass(frozen=True, slots=True)
class Metric:
    correct: int
    total: int

    @property
    def score(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass(frozen=True, slots=True)
class LabelMetric:
    precision: float | None
    recall: float | None
    f1: float | None
    support: int


@dataclass(frozen=True, slots=True)
class PairwiseMetric:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0

    @property
    def f1(self) -> float | None:
        precision = self.precision
        recall = self.recall
        if precision is None or recall is None or precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    label: str
    document_labels: Metric
    event_memberships: Metric
    relationships: Metric
    fact_values: Metric
    fact_evidence: Metric
    confusion_matrix: dict[str, dict[str, int]]
    per_label: dict[str, LabelMetric]
    event_grouping: PairwiseMetric
    errors: tuple[dict[str, Any], ...]

    def as_dict(self):
        data = asdict(self)
        for name in (
            "document_labels",
            "event_memberships",
            "relationships",
            "fact_values",
            "fact_evidence",
        ):
            metric = getattr(self, name)
            data[name]["score"] = metric.score
        data["event_grouping"].update(
            {
                "precision": self.event_grouping.precision,
                "recall": self.event_grouping.recall,
                "f1": self.event_grouping.f1,
            }
        )
        data["thresholds"] = None
        data["temporal_metrics"] = {
            "included": False,
            "reason": "第一期冻结金标不包含活动时效标注。",
        }
        return data


def evaluate(
    gold: GoldDataset, prediction: GoldDataset, *, label: str
) -> EvaluationReport:
    predicted_cases = {case.case_id: case for case in prediction.cases}
    labels_correct = labels_total = 0
    memberships_correct = memberships_total = 0
    relationships_correct = relationships_total = 0
    values_correct = values_total = 0
    evidence_correct = evidence_total = 0
    labels = [item.value for item in DocumentLabel]
    confusion = {
        expected: {actual: 0 for actual in (*labels, "MISSING")}
        for expected in labels
    }
    errors: list[dict[str, Any]] = []
    event_occurrences: list[tuple[str, str, int, str, str]] = []

    for case in gold.cases:
        predicted = predicted_cases.get(case.case_id)
        predicted_classifications = (
            {item.document_key: item for item in predicted.classifications}
            if predicted
            else {}
        )
        for expected in case.classifications:
            labels_total += 1
            actual = predicted_classifications.get(expected.document_key)
            actual_label = actual.label.value if actual else "MISSING"
            confusion[expected.label.value][actual_label] += 1
            label_matches = actual is not None and actual.label == expected.label
            labels_correct += int(label_matches)
            if not label_matches:
                errors.append(
                    {
                        "kind": "document_label",
                        "case_id": case.case_id,
                        "document_key": expected.document_key,
                        "expected": expected.label.value,
                        "actual": actual_label,
                    }
                )

            expected_count = len(expected.event_keys)
            actual_event_keys = actual.event_keys if actual else []
            actual_count = len(actual_event_keys)
            memberships_total += 1
            memberships_correct += int(expected_count == actual_count)
            if expected_count != actual_count:
                errors.append(
                    {
                        "kind": "event_count",
                        "case_id": case.case_id,
                        "document_key": expected.document_key,
                        "expected": expected_count,
                        "actual": actual_count,
                    }
                )
            for index, expected_event_key in enumerate(expected.event_keys):
                predicted_event_key = (
                    actual_event_keys[index]
                    if index < len(actual_event_keys)
                    else f"missing:{case.case_id}:{expected.document_key}:{index}"
                )
                event_occurrences.append(
                    (
                        case.case_id,
                        expected.document_key,
                        index,
                        expected_event_key,
                        predicted_event_key,
                    )
                )

        predicted_relationships = (
            {
                (item.document_key, item.event_key): item
                for item in predicted.relationships
            }
            if predicted
            else {}
        )
        for expected in case.relationships:
            relationships_total += 1
            actual = predicted_relationships.get(
                (expected.document_key, expected.event_key)
            )
            relationships_correct += int(
                actual is not None
                and actual.relationship == expected.relationship
                and actual.candidate_event_key == expected.candidate_event_key
            )

        predicted_facts = (
            {(item.event_key, item.field): item for item in predicted.facts}
            if predicted
            else {}
        )
        for expected in case.facts:
            values_total += 1
            evidence_total += 1
            actual = predicted_facts.get((expected.event_key, expected.field))
            values_correct += int(
                actual is not None
                and actual.value == expected.value
                and actual.conflict == expected.conflict
                and set(actual.alternatives) == set(expected.alternatives)
            )
            expected_evidence = {
                (item.document_key, item.locator) for item in expected.evidence
            }
            actual_evidence = (
                {(item.document_key, item.locator) for item in actual.evidence}
                if actual
                else set()
            )
            evidence_correct += int(actual_evidence == expected_evidence)

    per_label = {
        label_name: _label_metric(confusion, label_name) for label_name in labels
    }
    grouping, grouping_errors = _evaluate_event_grouping(event_occurrences)
    errors.extend(grouping_errors)

    return EvaluationReport(
        label=label,
        document_labels=Metric(labels_correct, labels_total),
        event_memberships=Metric(memberships_correct, memberships_total),
        relationships=Metric(relationships_correct, relationships_total),
        fact_values=Metric(values_correct, values_total),
        fact_evidence=Metric(evidence_correct, evidence_total),
        confusion_matrix=confusion,
        per_label=per_label,
        event_grouping=grouping,
        errors=tuple(errors),
    )


def _label_metric(
    confusion: dict[str, dict[str, int]], label: str
) -> LabelMetric:
    true_positive = confusion[label][label]
    false_positive = sum(
        row[label] for expected, row in confusion.items() if expected != label
    )
    false_negative = sum(
        count for actual, count in confusion[label].items() if actual != label
    )
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = (
        true_positive / precision_denominator if precision_denominator else 0.0
    )
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None
        and recall is not None
        and precision + recall > 0
        else 0.0
    )
    return LabelMetric(precision, recall, f1, recall_denominator)


def _evaluate_event_grouping(
    occurrences: list[tuple[str, str, int, str, str]],
) -> tuple[PairwiseMetric, list[dict[str, Any]]]:
    true_positive = false_positive = false_negative = true_negative = 0
    errors: list[dict[str, Any]] = []
    for left, right in combinations(occurrences, 2):
        expected_same = left[3] == right[3]
        predicted_same = left[4] == right[4]
        if expected_same and predicted_same:
            true_positive += 1
        elif expected_same:
            false_negative += 1
            errors.append(_grouping_error("same_event_split", left, right))
        elif predicted_same:
            false_positive += 1
            errors.append(_grouping_error("different_events_merged", left, right))
        else:
            true_negative += 1
    return (
        PairwiseMetric(
            true_positive,
            false_positive,
            false_negative,
            true_negative,
        ),
        errors,
    )


def _grouping_error(
    kind: str,
    left: tuple[str, str, int, str, str],
    right: tuple[str, str, int, str, str],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "left": {
            "case_id": left[0],
            "document_key": left[1],
            "hint_index": left[2],
            "expected_event_key": left[3],
            "predicted_event_key": left[4],
        },
        "right": {
            "case_id": right[0],
            "document_key": right[1],
            "hint_index": right[2],
            "expected_event_key": right[3],
            "predicted_event_key": right[4],
        },
    }
