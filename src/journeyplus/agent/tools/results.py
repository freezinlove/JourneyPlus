"""Declared tool data envelopes; nested published records retain domain schemas."""
from pydantic import Field, create_model, model_validator
from journeyplus.agent.harness.contracts import DTO, ToolResult


class CatalogData(DTO):
    candidates: list[dict] | None = None
    has_more: bool | None = None


class ActivityData(DTO):
    activities: list[dict] | None = None
    sections: list[dict] | None = None


class RouteData(DTO):
    readiness: dict | None = None
    query_context: dict | None = None
    retrieval_scope: dict | None = None
    steps: list[dict] | None = None
    query_ref: str | None = None
    effective_query: dict | None = None
    resolved_sources: list[dict] | None = None
    resolved_target: dict | None = None
    unresolved_sources: list[dict] | None = None
    candidates: list[dict] | None = None
    route_refs: list[str] | None = None
    step_refs: list[str] | None = None
    comparison_metrics: dict | None = None
    search_metrics: dict | None = None
    metrics: dict | None = None


class HoldingsData(DTO):
    holdings: list[dict] | None = None
    snapshot_ref: str | None = None


class OperationData(DTO):
    operation_ref: str | None = None
    outcome: str | None = None
    before: dict | None = None
    after: dict | None = None
    revision: int | None = None
    current: dict | None = None


class WaitingData(OperationData):
    goals: list[dict] | None = None
    existing: dict | None = None


class WorkspaceData(DTO):
    messages: list[dict] | None = None
    artifacts: list[dict] | None = None
    sections: list[dict] | None = None
    total: int | None = None
    section_count: int | None = None
    next_cursor: str | None = None
    revision: int | None = None


class NoteData(DTO):
    revision: int | None = None
    note_ref: str | None = None


class SearchData(DTO):
    coverage: dict | None = None
    results: list[dict] | None = None
    scope_description: str | None = None
    next_cursor: str | None = None


class PageData(DTO):
    evidence_scope: dict | None = None
    page_ref: str | None = None
    url: str | None = None
    final_url: str | None = None
    title: str | None = None
    text: str | None = None
    links: list[dict] | None = None
    observed_at: str | None = None
    content_hash: str | None = None
    content_hash_scope: str | None = None
    content_length: int | None = None
    truncated: bool | None = None
    raw_truncated: bool | None = None
    retained_raw_bytes: int | None = None
    links_truncated: bool | None = None
    cache_hit: bool | None = None
    sections: list[dict] | None = None
    available_sections: list[dict] | None = None
    missing_sections: list[str] | None = None
    content_scope: str | None = None
    form_controls: list[dict] | None = None


class ResearchData(DTO):
    report_refs: list[str] | None = None
    reports: list[dict] | None = None


class PresentationData(DTO):
    presentation_ref: str | None = None
    revision: int | None = None
    blocks: list[dict] | None = None
    next_steps: list[dict] | None = None
    omissions: list[str] | None = None


DATA_MODELS={'catalog.lookup':CatalogData,'activity.read':ActivityData,'routes.evaluate':RouteData,
             'holdings.read':HoldingsData,'holdings.write':OperationData,'waiting.manage':WaitingData,
             'workspace.read':WorkspaceData,'workspace.note':NoteData,'web.search':SearchData,
             'web.read':PageData,'research.parse':ResearchData,'display.present':PresentationData}
REQUIRED={'catalog.lookup':(('candidates',),),'activity.read':(('activities',),('sections',)),
          'routes.evaluate':(('candidates',),),'holdings.read':(('holdings','snapshot_ref'),),
          'holdings.write':(('operation_ref','outcome'),),'waiting.manage':(('goals',),('operation_ref','outcome')),
          'workspace.read':(('messages',),('artifacts',),('sections',)),
          'workspace.note':(('note_ref','revision'),),'web.search':(('results',),),
          'web.read':(('page_ref','url','text','content_hash'),),'research.parse':(('reports','report_refs'),),
          'display.present':(('presentation_ref','blocks','revision'),)}


def output_model(name,model):
    @model_validator(mode='after')
    def require_success_data(self):
        if self.status in {'OK','PARTIAL','EMPTY'} and not any(
                all(getattr(self.data,key) is not None for key in group) for group in REQUIRED[name]):
            raise ValueError('Successful result is missing its declared data fields')
        return self
    return create_model(model.__name__+'Result',__base__=ToolResult,
                        __validators__={'require_success_data':require_success_data},
                        data=(model,Field(default_factory=model)))


OUTPUTS={name:output_model(name,model) for name,model in DATA_MODELS.items()}
