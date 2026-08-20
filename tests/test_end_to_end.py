from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from journeyplus.ai.provider import AIProviderMetadata
from journeyplus.contracts import DiscoveredItem, RawDocument
from journeyplus.models import BriefRecord, DocumentVersion, FactSetRecord, StatusEvent
from journeyplus.sources.collection import collect_manual
from journeyplus.sources.registry import seed_sources
from journeyplus.workflow import V1Workflow


class AdaptiveProvider:
    metadata = AIProviderMetadata(
        provider="test",
        model="adaptive",
        region="local",
        config_version="adaptive-v1",
    )

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_structured(self, *, system_prompt, user_prompt, output_model):
        self.calls.append(output_model.__name__)
        if output_model.__name__ == "RelevanceResult":
            if "ordinary credit card bonus" in user_prompt:
                payload: dict[str, Any] = {
                    "label": "NONE",
                    "confidence": 1,
                    "reason": "no direct status acquisition result",
                    "event_hints": [],
                }
            else:
                payload = {
                    "label": "STATUS_OPPORTUNITY",
                    "confidence": 0.98,
                    "reason": "direct public status match",
                    "event_hints": [
                        {
                            "program": "Example Air",
                            "opportunity_type": "STATUS_MATCH",
                            "summary": "Example Air matches eligible members to Gold",
                            "target_status": "Gold",
                        }
                    ],
                }
        elif output_model.__name__ == "FactSet":
            request = json.loads(user_prompt)
            material = request["materials"][0]
            evidence = {
                "document_version_id": material["document_version_id"],
                "source_url": material["source_url"],
                "locator": "opening paragraph and application list",
            }
            payload = {
                "event_id": request["event"]["id"],
                "what_happened": {
                    "value": "Example Air 向符合条件的会员开放金卡匹配",
                    "evidence": [evidence],
                },
                "eligibility": {
                    "value": "持有指定合作方会籍的会员",
                    "evidence": [evidence],
                },
                "target_status": {"value": "Gold", "evidence": [evidence]},
                "action_link": {
                    "value": "https://example.com/apply",
                    "evidence": [evidence],
                },
            }
        elif output_model.__name__ == "Brief":
            request = json.loads(user_prompt)
            facts = request["fact_set"]
            source_url = facts["what_happened"]["evidence"][0]["source_url"]
            payload = {
                "fact_set_id": request["fact_set_id"],
                "title": "Example Air 开放金卡会籍匹配",
                "title_fact_keys": ["what_happened", "target_status"],
                "summary": "符合合作方会籍条件的会员可申请匹配至 Example Air 金卡。",
                "summary_fact_keys": ["what_happened", "eligibility", "target_status"],
                "key_points": [
                    {"text": "目标会籍为 Gold。", "fact_keys": ["target_status"]},
                    {"text": "申请入口见来源链接。", "fact_keys": ["action_link"]},
                ],
                "caveats": [],
                "source_links": [source_url],
            }
        else:
            raise AssertionError(output_model)
        return output_model.model_validate(payload)


class FixedAdapter:
    source_id = "ffb_elite_status_feed"

    def __init__(self, external_id: str, body: str) -> None:
        self.external_id = external_id
        self.body = body

    def discover(self):
        url = f"https://example.com/{self.external_id}"
        return [
            DiscoveredItem(
                source_id=self.source_id,
                external_id=self.external_id,
                discovered_url=url,
                canonical_url=url,
                title=self.external_id,
                observed_at=datetime.now(UTC),
            )
        ]

    def fetch(self, item):
        return RawDocument(
            source_id=self.source_id,
            external_id=item.external_id,
            canonical_url=item.canonical_url,
            body=self.body,
            content_type="text/html",
        )


def test_fixed_material_runs_from_discovery_to_original_brief_and_stays_in_scope(
    db_session,
) -> None:
    seed_sources(db_session)
    long_source_wording = (
        "LONG SOURCE WORDING MUST NOT BE REPUBLISHED. "
        "Example Air offers a direct status match to Gold."
    )
    collect_manual(
        db_session,
        FixedAdapter("in-scope", f"<article><p>{long_source_wording}</p></article>"),
        idempotency_key="e2e:in-scope",
    )
    document = db_session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.canonical_url == "https://example.com/in-scope"
        )
    )
    assert document is not None
    provider = AdaptiveProvider()
    result = V1Workflow(db_session, provider).process(document)

    assert len(result.outputs) == 1
    brief = result.outputs[0].brief.brief
    assert brief.title == "Example Air 开放金卡会籍匹配"
    assert "LONG SOURCE WORDING" not in brief.summary
    assert provider.calls == ["RelevanceResult", "FactSet", "Brief"]
    assert db_session.scalar(select(func.count()).select_from(StatusEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(FactSetRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(BriefRecord)) == 1

    collect_manual(
        db_session,
        FixedAdapter("out-of-scope", "<p>An ordinary credit card bonus.</p>"),
        idempotency_key="e2e:out-of-scope",
    )
    out_of_scope = db_session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.canonical_url == "https://example.com/out-of-scope"
        )
    )
    assert out_of_scope is not None
    excluded = V1Workflow(db_session, provider).process(out_of_scope)
    assert excluded.outputs == []
    assert db_session.scalar(select(func.count()).select_from(StatusEvent)) == 1
