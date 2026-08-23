from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select

from journeyplus.ai.provider import AIProvider, AIProviderMetadata
from journeyplus.clustering.relationship import (
    RELATIONSHIP_PROMPT_VERSION,
    RELATIONSHIP_SCHEMA_VERSION,
)
from journeyplus.contracts import RunStatus
from journeyplus.db import create_database_engine, create_session_factory
from journeyplus.evaluation.evaluator import evaluate
from journeyplus.evaluation.schema import (
    GoldCase,
    GoldClassification,
    GoldDataset,
    GoldDocument,
)
from journeyplus.models import (
    AnalysisRun,
    Base,
    DocumentVersion,
    Source,
    SourceItem,
)
from journeyplus.status_topic.analyzer import (
    STATUS_RELEVANCE_PROMPT_VERSION,
    STATUS_RELEVANCE_SCHEMA_VERSION,
)
from journeyplus.status_topic.pipeline import StatusOpportunityPipeline


OutputModel = TypeVar("OutputModel", bound=BaseModel)
ProgressCallback = Callable[[int, int, str, str, int], None]
EVALUATION_CACHE_SCHEMA_VERSION = 1
EVALUATION_RUN_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class FrozenGold:
    dataset: GoldDataset
    sha256: str
    manifest: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BaselineRunResult:
    output_dir: Path
    prediction_path: Path
    report_path: Path
    cache_path: Path
    state_database_path: Path
    processed_documents: int
    total_documents: int
    complete: bool
    model_calls: int
    cache_hits: int
    cached_outputs: int
    analysis_failures: int

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "output_dir": str(self.output_dir),
            "prediction_path": str(self.prediction_path),
            "report_path": str(self.report_path),
            "cache_path": str(self.cache_path),
            "state_database_path": str(self.state_database_path),
        }


class JsonCachingProvider:
    def __init__(
        self,
        delegate: AIProvider,
        cache_path: Path,
        *,
        run_identity: dict[str, Any],
    ) -> None:
        self._delegate = delegate
        self._cache_path = cache_path
        self._run_identity = run_identity
        self.metadata: AIProviderMetadata = delegate.metadata
        self.cache_hits = 0
        self.model_calls = 0
        self._scope: dict[str, str] | None = None
        self._cache = self._load()

    @property
    def cached_output_count(self) -> int:
        return len(self._cache["entries"])

    def set_document_scope(self, case_id: str, document_key: str) -> None:
        self._scope = {
            "case_id": case_id,
            "document_key": document_key,
        }

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
    ) -> OutputModel:
        if self._scope is None:
            raise RuntimeError("Gold cache document scope has not been set")
        key = self._key(system_prompt, user_prompt, output_model)
        cached = self._cache["entries"].get(key)
        if cached is not None:
            self.cache_hits += 1
            return output_model.model_validate(cached["result"])

        self.model_calls += 1
        result = self._delegate.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_model=output_model,
        )
        self._cache["entries"][key] = {
            "output_model": output_model.__name__,
            "created_at": datetime.now(UTC).isoformat(),
            "scope": self._scope,
            "run_identity": self._run_identity,
            "result": result.model_dump(mode="json"),
        }
        self._save()
        return result

    def _key(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[BaseModel],
    ) -> str:
        payload = {
            "run_identity": self._run_identity,
            "scope": self._scope,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "output_schema": output_model.model_json_schema(),
        }
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def _load(self) -> dict[str, Any]:
        if not self._cache_path.exists():
            return {
                "cache_schema_version": EVALUATION_CACHE_SCHEMA_VERSION,
                "entries": {},
            }
        payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        if payload.get("cache_schema_version") != EVALUATION_CACHE_SCHEMA_VERSION:
            raise ValueError("Unsupported gold evaluation cache schema version")
        if not isinstance(payload.get("entries"), dict):
            raise ValueError("Gold evaluation cache entries must be an object")
        return payload

    def _save(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._cache_path)


def load_frozen_gold(gold_path: Path, freeze_path: Path) -> FrozenGold:
    manifest = json.loads(freeze_path.read_text(encoding="utf-8"))
    if manifest.get("freeze_schema_version") != 1:
        raise ValueError("Unsupported gold freeze manifest schema version")
    payload = gold_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != manifest.get("sha256"):
        raise ValueError("Gold dataset SHA-256 does not match the freeze manifest")
    dataset = GoldDataset.model_validate_json(payload)
    if dataset.schema_version != manifest.get("schema_version"):
        raise ValueError("Gold schema version does not match the freeze manifest")
    if dataset.dataset_version != manifest.get("dataset_version"):
        raise ValueError("Gold dataset version does not match the freeze manifest")
    versions = {case.case_id: case.version for case in dataset.cases}
    if versions != manifest.get("case_versions"):
        raise ValueError("Gold case versions do not match the freeze manifest")

    counts = manifest.get("counts", {})
    labels = Counter(
        item.label.value
        for case in dataset.cases
        for item in case.classifications
    )
    expected_counts = {
        "documents": sum(len(case.documents) for case in dataset.cases),
        "status_opportunity": labels["STATUS_OPPORTUNITY"],
        "none": labels["NONE"],
        "uncertain": labels["UNCERTAIN"],
    }
    if expected_counts != {
        name: counts.get(name)
        for name in ("documents", "status_opportunity", "none", "uncertain")
    }:
        raise ValueError("Gold counts do not match the freeze manifest")
    _validate_runtime_shape(dataset)
    return FrozenGold(dataset, digest, manifest)


def run_gold_baseline(
    *,
    provider: AIProvider,
    gold_path: Path,
    freeze_path: Path,
    output_dir: Path,
    label: str = "current",
    max_documents: int | None = None,
    progress: ProgressCallback | None = None,
) -> BaselineRunResult:
    if max_documents is not None and max_documents < 1:
        raise ValueError("max_documents must be positive")
    frozen = load_frozen_gold(gold_path, freeze_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.sqlite"
    cache_path = output_dir / "cache.json"
    prediction_path = output_dir / "current-output.json"
    report_path = output_dir / "report.json"
    metadata_path = output_dir / "run.json"

    identity = _run_identity(frozen.sha256, provider.metadata)
    _validate_or_create_run_metadata(metadata_path, identity)
    caching_provider = JsonCachingProvider(
        provider,
        cache_path,
        run_identity=identity,
    )

    engine = create_database_engine(f"sqlite+pysqlite:///{state_path}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    total_documents = sum(len(case.documents) for case in frozen.dataset.cases)
    selected_documents = (
        min(total_documents, max_documents)
        if max_documents is not None
        else total_documents
    )
    processed: dict[tuple[str, str], GoldClassification] = {}
    event_order: dict[str, str] = {}
    document_number = 0

    try:
        for case in frozen.dataset.cases:
            for document in case.documents:
                if document_number >= selected_documents:
                    break
                document_number += 1
                with session_factory.begin() as session:
                    caching_provider.set_document_scope(
                        case.case_id, document.document_key
                    )
                    stored = _ensure_document(session, case.case_id, document)
                    result = StatusOpportunityPipeline(
                        session, caching_provider
                    ).process(stored)
                    predicted_keys: list[str] = []
                    for item in result.events:
                        event_id = str(item.event.id)
                        if event_id not in event_order:
                            event_order[event_id] = (
                                f"predicted-event-{len(event_order) + 1:03d}"
                            )
                        predicted_keys.append(event_order[event_id])
                    classification = GoldClassification(
                        document_key=document.document_key,
                        label=result.relevance.result.label,
                        event_keys=predicted_keys,
                    )
                    processed[(case.case_id, document.document_key)] = classification
                    if progress is not None:
                        progress(
                            document_number,
                            total_documents,
                            document.document_key,
                            classification.label.value,
                            len(classification.event_keys),
                        )
                _write_run_metadata(
                    metadata_path,
                    identity,
                    processed_documents=document_number,
                    total_documents=total_documents,
                    complete=document_number == total_documents,
                )
            if document_number >= selected_documents:
                break

        prediction = _prediction_dataset(frozen.dataset, processed)
        prediction_path.write_text(
            prediction.model_dump_json(indent=2), encoding="utf-8"
        )
        evaluation = evaluate(frozen.dataset, prediction, label=label).as_dict()
        with session_factory() as session:
            failures = list(
                session.scalars(
                    select(AnalysisRun).where(
                        AnalysisRun.status == RunStatus.FAILED
                    )
                )
            )
        report_payload = {
            "run_schema_version": EVALUATION_RUN_SCHEMA_VERSION,
            "gold_dataset_version": frozen.dataset.dataset_version,
            "gold_sha256": frozen.sha256,
            "complete": document_number == total_documents,
            "processed_documents": document_number,
            "total_documents": total_documents,
            "model_calls": caching_provider.model_calls,
            "cache_hits": caching_provider.cache_hits,
            "cached_outputs": caching_provider.cached_output_count,
            "analysis_failures": [
                {
                    "stage": item.stage,
                    "document_version_id": str(item.document_version_id),
                    "error": item.error,
                }
                for item in failures
            ],
            "evaluation": evaluation,
        }
        report_path.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        complete = document_number == total_documents
        _write_run_metadata(
            metadata_path,
            identity,
            processed_documents=document_number,
            total_documents=total_documents,
            complete=complete,
        )
        return BaselineRunResult(
            output_dir=output_dir,
            prediction_path=prediction_path,
            report_path=report_path,
            cache_path=cache_path,
            state_database_path=state_path,
            processed_documents=document_number,
            total_documents=total_documents,
            complete=complete,
            model_calls=caching_provider.model_calls,
            cache_hits=caching_provider.cache_hits,
            cached_outputs=caching_provider.cached_output_count,
            analysis_failures=len(failures),
        )
    finally:
        engine.dispose()


def _run_identity(
    gold_sha256: str, metadata: AIProviderMetadata
) -> dict[str, Any]:
    return {
        "gold_sha256": gold_sha256,
        "provider": asdict(metadata),
        "status_prompt_version": STATUS_RELEVANCE_PROMPT_VERSION,
        "status_schema_version": STATUS_RELEVANCE_SCHEMA_VERSION,
        "relationship_prompt_version": RELATIONSHIP_PROMPT_VERSION,
        "relationship_schema_version": RELATIONSHIP_SCHEMA_VERSION,
    }


def _validate_or_create_run_metadata(
    path: Path, identity: dict[str, Any]
) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("identity") != identity:
            raise ValueError(
                "Output directory belongs to a different gold/model/prompt run"
            )
        return
    _write_run_metadata(
        path,
        identity,
        processed_documents=0,
        total_documents=0,
        complete=False,
    )


def _write_run_metadata(
    path: Path,
    identity: dict[str, Any],
    *,
    processed_documents: int,
    total_documents: int,
    complete: bool,
) -> None:
    payload = {
        "run_schema_version": EVALUATION_RUN_SCHEMA_VERSION,
        "identity": identity,
        "processed_documents": processed_documents,
        "total_documents": total_documents,
        "complete": complete,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _ensure_document(
    session: Any,
    case_id: str,
    document: GoldDocument,
) -> DocumentVersion:
    source_id = "gold-evaluation"
    source = session.get(Source, source_id)
    if source is None:
        session.add(
            Source(
                id=source_id,
                name="Isolated gold evaluation",
                adapter_type="evaluation",
                discovery_config={},
                access_policy={"business_writes": False},
                enabled=False,
            )
        )
        session.flush()
    external_id = f"{case_id}:{document.document_key}"
    item = session.scalar(
        select(SourceItem).where(
            SourceItem.source_id == source_id,
            SourceItem.external_id == external_id,
        )
    )
    if item is None:
        metadata = {"case_id": case_id, "document_key": document.document_key}
        title = document.document_key
        source_prefix = document.document_key.partition(":")[0]
        metadata["source_id"] = source_prefix
        item = SourceItem(
            source_id=source_id,
            external_id=external_id,
            discovered_url=str(document.source_url),
            canonical_url=str(document.source_url),
            title=title,
            observed_at=datetime.now(UTC),
            raw_metadata=metadata,
        )
        session.add(item)
        session.flush()
    existing = session.scalar(
        select(DocumentVersion).where(DocumentVersion.source_item_id == item.id)
    )
    if existing is not None:
        return existing
    digest = hashlib.sha256(document.normalized_body.encode("utf-8")).hexdigest()
    stored = DocumentVersion(
        source_item_id=item.id,
        canonical_url=str(document.source_url),
        raw_body=document.normalized_body,
        normalized_body=document.normalized_body,
        content_type="text/markdown",
        storage_mode="isolated_gold_evaluation",
        raw_hash=digest,
        normalized_hash=digest,
        parser_version="gold-frozen-v1",
        fetched_at=datetime.now(UTC),
    )
    session.add(stored)
    session.flush()
    return stored


def _prediction_dataset(
    gold: GoldDataset,
    processed: dict[tuple[str, str], GoldClassification],
) -> GoldDataset:
    cases: list[GoldCase] = []
    for case in gold.cases:
        documents = [
            document
            for document in case.documents
            if (case.case_id, document.document_key) in processed
        ]
        if not documents:
            continue
        cases.append(
            GoldCase(
                case_id=case.case_id,
                version=case.version,
                notes=(
                    "Prediction from the isolated gold baseline runtime; "
                    "event keys are stable only within this prediction."
                ),
                documents=documents,
                classifications=[
                    processed[(case.case_id, document.document_key)]
                    for document in documents
                ],
                relationships=[],
                facts=[],
            )
        )
    return GoldDataset(
        schema_version=gold.schema_version,
        dataset_version=gold.dataset_version,
        cases=cases,
    )


def _validate_runtime_shape(dataset: GoldDataset) -> None:
    for case in dataset.cases:
        document_keys = [item.document_key for item in case.documents]
        classification_keys = [
            item.document_key for item in case.classifications
        ]
        if len(document_keys) != len(set(document_keys)):
            raise ValueError(f"Duplicate document keys in gold case {case.case_id}")
        if len(classification_keys) != len(set(classification_keys)):
            raise ValueError(
                f"Duplicate classification keys in gold case {case.case_id}"
            )
        if set(document_keys) != set(classification_keys):
            raise ValueError(
                f"Gold documents and classifications differ in case {case.case_id}"
            )
