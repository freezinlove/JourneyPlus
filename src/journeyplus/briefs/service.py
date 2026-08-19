from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from journeyplus.ai.provider import AIProvider
from journeyplus.contracts import AnalysisStage, Brief, FactSet, RunStatus
from journeyplus.models import AnalysisRun, BriefRecord, FactSetRecord, StatusEvent


BRIEF_PROMPT_VERSION = "chinese-brief-v1"
BRIEF_SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """你是中文旅行会籍机会编辑。只能读取输入的版本化 FactSet，用自己的中文重组核心信息，输出短标题、短摘要、要点、限制/不确定性和来源链接。标题、摘要、每个要点和每项限制都要用 fact_keys 声明依据；不得使用 value=null 的字段支持确定性陈述。冲突必须写成不确定性，不可擅自选择。不得添加 FactSet 没有的日期、费用、资格或结论，不得复制长段原文。只输出符合 JSON Schema 的 JSON。"""


@dataclass(frozen=True, slots=True)
class BriefGeneration:
    run: AnalysisRun
    record: BriefRecord
    brief: Brief
    reused: bool


class BriefGenerator:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        prompt_version: str = BRIEF_PROMPT_VERSION,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._prompt_version = prompt_version
        self._max_attempts = max_attempts

    def generate(self, fact_record: FactSetRecord) -> BriefGeneration:
        fact_set = FactSet.model_validate(fact_record.facts)
        key = (
            f"{AnalysisStage.BRIEF_GENERATION}:{fact_record.id}:"
            f"{self._provider.metadata.config_version}:{self._prompt_version}"
        )
        existing = self._session.scalar(
            select(AnalysisRun).where(AnalysisRun.idempotency_key == key)
        )
        event = self._session.get(StatusEvent, fact_record.event_id)
        if event is None:
            raise LookupError("FactSet event was not found")
        if existing and existing.result:
            record = self._session.get(BriefRecord, event.current_brief_id)
            if record is not None and record.fact_set_id != fact_record.id:
                record = None
            if record is None:
                record = next(
                    (
                        item
                        for item in self._session.scalars(
                            select(BriefRecord)
                            .where(BriefRecord.fact_set_id == fact_record.id)
                            .order_by(BriefRecord.version.desc())
                        )
                        if item.content == existing.result
                    ),
                    None,
                )
            if record is not None:
                return BriefGeneration(
                    existing, record, Brief.model_validate(record.content), True
                )
        run = existing or AnalysisRun(
            idempotency_key=key,
            event_id=fact_record.event_id,
            stage=AnalysisStage.BRIEF_GENERATION,
            status=RunStatus.RUNNING,
            input_version=str(fact_record.id),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            model_config_version=self._provider.metadata.config_version,
            prompt_version=self._prompt_version,
            schema_version=BRIEF_SCHEMA_VERSION,
        )
        if existing is None:
            self._session.add(run)

        last_error: Exception | None = None
        brief: Brief | None = None
        for _attempt in range(self._max_attempts):
            try:
                candidate = self._provider.generate_structured(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "fact_set_id": str(fact_record.id),
                            "fact_set": fact_record.facts,
                        },
                        ensure_ascii=False,
                    ),
                    output_model=Brief,
                )
                self._validate(candidate, fact_record, fact_set)
                brief = candidate
                break
            except Exception as exc:
                last_error = exc
        if brief is None:
            run.status = RunStatus.FAILED
            run.error = f"{type(last_error).__name__}: {last_error}"[:2000]
            self._session.flush()
            raise ValueError("Brief generation failed grounding validation") from last_error

        run.status = RunStatus.SUCCEEDED
        run.result = brief.model_dump(mode="json")
        run.error = None
        version = (
            self._session.scalar(
                select(func.max(BriefRecord.version)).where(
                    BriefRecord.fact_set_id == fact_record.id
                )
            )
            or 0
        ) + 1
        record = BriefRecord(
            fact_set_id=fact_record.id,
            version=version,
            schema_version=brief.schema_version,
            content=brief.model_dump(mode="json"),
        )
        self._session.add(record)
        self._session.flush()
        event.current_brief_id = record.id
        self._session.flush()
        return BriefGeneration(run, record, brief, False)

    @staticmethod
    def _validate(brief: Brief, record: FactSetRecord, fact_set: FactSet) -> None:
        if brief.fact_set_id != record.id:
            raise ValueError("Brief fact_set_id does not match its input")
        fields = fact_set.fact_fields()
        referenced_groups = [
            brief.title_fact_keys,
            brief.summary_fact_keys,
            *(point.fact_keys for point in brief.key_points),
            *(point.fact_keys for point in brief.caveats),
        ]
        for keys in referenced_groups:
            for key in keys:
                if key not in fields:
                    raise ValueError(f"Brief references unknown fact key: {key}")
                field = fields[key]
                if field.value is None and not field.conflict:
                    raise ValueError(f"Brief makes a claim from unknown fact: {key}")
        allowed_links = {
            str(evidence.source_url).rstrip("/")
            for field in fields.values()
            for evidence in field.evidence
        }
        if any(str(link).rstrip("/") not in allowed_links for link in brief.source_links):
            raise ValueError("Brief contains an unsupported source link")
        output_text = "\n".join(
            [
                brief.title,
                brief.summary,
                *(point.text for point in brief.key_points),
                *(point.text for point in brief.caveats),
            ]
        )
        for field in fields.values():
            if field.value and len(field.value) >= 160:
                for start in range(0, len(field.value) - 159):
                    if field.value[start : start + 160] in output_text:
                        raise ValueError("Brief repeats a long source-derived passage")
