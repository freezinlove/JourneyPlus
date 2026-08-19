from __future__ import annotations

from dataclasses import asdict, dataclass

from journeyplus.evaluation.schema import GoldDataset


@dataclass(frozen=True, slots=True)
class Metric:
    correct: int
    total: int

    @property
    def score(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    label: str
    relevance: Metric
    relationships: Metric
    fact_values: Metric
    fact_evidence: Metric

    def as_dict(self):
        data = asdict(self)
        for name in ("relevance", "relationships", "fact_values", "fact_evidence"):
            metric = getattr(self, name)
            data[name]["score"] = metric.score
        data["thresholds"] = None
        return data


def evaluate(
    gold: GoldDataset, prediction: GoldDataset, *, label: str
) -> EvaluationReport:
    predicted_cases = {case.case_id: case for case in prediction.cases}
    relevance_correct = relevance_total = 0
    relationships_correct = relationships_total = 0
    values_correct = values_total = 0
    evidence_correct = evidence_total = 0

    for case in gold.cases:
        predicted = predicted_cases.get(case.case_id)
        predicted_relevance = (
            {item.document_key: item for item in predicted.relevance} if predicted else {}
        )
        for expected in case.relevance:
            relevance_total += 1
            actual = predicted_relevance.get(expected.document_key)
            relevance_correct += int(
                actual is not None
                and actual.label == expected.label
                and set(actual.event_keys) == set(expected.event_keys)
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

    return EvaluationReport(
        label=label,
        relevance=Metric(relevance_correct, relevance_total),
        relationships=Metric(relationships_correct, relationships_total),
        fact_values=Metric(values_correct, values_total),
        fact_evidence=Metric(evidence_correct, evidence_total),
    )

