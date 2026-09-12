"""Explicit, independently callable business inputs; no conversation state."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from journeyplus.agent.harness.contracts import DTO


class IdentityRef(DTO):
    ref: str = Field(min_length=1, max_length=300)


class IdentityName(DTO):
    program_name: str = Field(min_length=1, max_length=300)
    tier_name: str | None = Field(default=None, min_length=1, max_length=300,
        description='Requested tier only. A tier seen in previous results is not a user constraint; omit for a program-only destination.')
    alternatives: list[str] = Field(default_factory=list, max_length=3)


IdentityInput = IdentityRef | IdentityName


class CatalogInput(DTO):
    query: str = Field(min_length=1, max_length=300)
    kind: Literal['program', 'tier', 'any'] = 'any'
    program: IdentityInput | None = None
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = None


class ActivityQuery(DTO):
    query: str = Field(min_length=1, max_length=500)


class ActivityInput(DTO):
    selector: IdentityRef | ActivityQuery
    view: Literal['overview', 'detail', 'evidence', 'changes'] = 'overview'
    aspects: list[Literal['price', 'eligibility', 'challenge', 'window', 'validity', 'application']] = Field(default_factory=list)
    version_ref: str | None = None
    section_refs: list[str] = Field(default_factory=list)
    cursor: str | None = None
    limit: int = Field(default=5, ge=1, le=10)


class Sources(DTO):
    mode: Literal['explicit', 'saved', 'none']
    identities: list[IdentityInput] = Field(default_factory=list, max_length=20)
    holding_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def check_sources(self):
        count = len(self.identities) + len(self.holding_refs)
        if self.mode == 'explicit' and not 1 <= count <= 20:
            raise ValueError('explicit sources require 1..20 identities or holding_refs')
        if self.mode != 'explicit' and count:
            raise ValueError('saved/none sources cannot include explicit identities')
        return self


class Constraints(DTO):
    free_only: bool = False
    max_amount: str | None = Field(default=None, pattern=r'^\d+(\.\d+)?$')
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    allow_challenge: bool | None = None
    source_acquisition: Literal['EARNED', 'MATCHED', 'UNKNOWN'] = Field(default='UNKNOWN',
        description='How the user ALREADY OBTAINED the starting/held status. MATCHED means that existing card was obtained by a prior match, not that the user wants a status match now. Keep UNKNOWN unless the user states its origin. This does not filter the method of target activities.')
    residency: str | None = None
    prior_participation: str | None = None
    require_proven_eligibility: bool = False

    @model_validator(mode='after')
    def check_amount(self):
        if self.max_amount is not None and (not self.currency or self.free_only):
            raise ValueError('max_amount needs currency and cannot combine with free_only')
        return self


class RouteRequest(DTO):
    sources: Sources
    target: IdentityInput | None = Field(default=None,description='Requested destination; omit for all destinations.')
    category: Literal['AIRLINE', 'HOTEL', 'CRUISE', 'OTHER'] | None = Field(default=None,
        description='Only an explicit destination restriction; omit for all paths.')
    alliance: str | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    preferences: list[Literal['FEWER_STEPS', 'LOWER_KNOWN_FEE', 'LESS_UNCERTAINTY']] = Field(default_factory=list, max_length=3)


class QueryPatch(DTO):
    sources: Sources | None = None
    target: IdentityInput | None = None
    category: Literal['AIRLINE', 'HOTEL', 'CRUISE', 'OTHER'] | None = None
    alliance: str | None = None
    constraints: dict | None = None
    preferences: list[Literal['FEWER_STEPS', 'LOWER_KNOWN_FEE', 'LESS_UNCERTAINTY']] | None = None


class RoutesInput(DTO):
    operation: Literal['search', 'inspect', 'compare']
    query: RouteRequest | None = None
    query_ref: str | None = Field(default=None,description='QUERY ref: replay unchanged, use cursor for pages or patch for changes.')
    patch: QueryPatch | None = Field(default=None,description='RFC7396 RouteRequest patch with query_ref. sources/target replace whole objects. Null clears, omission inherits.')
    route_refs: list[str] = Field(default_factory=list, max_length=12)
    cursor: str | None = Field(default=None,description='Continue returned next_cursor with operation="search" and the same query_ref; omit query and patch. There is no next_page operation.')
    limit: int = Field(default=8, ge=1, le=20)

    @model_validator(mode='after')
    def check_operation(self):
        if self.operation == 'search':
            full = self.query is not None and not self.query_ref and self.patch is None and not self.cursor
            patched = self.query is None and bool(self.query_ref) and not self.cursor
            paged = self.query is None and bool(self.query_ref) and self.patch is None and bool(self.cursor)
            if not (full or patched or paged) or self.route_refs:
                raise ValueError('search requires query OR query_ref with optional patch OR query_ref+cursor')
        elif not self.route_refs or any(x is not None for x in (self.query, self.query_ref, self.patch, self.cursor)):
            raise ValueError('inspect/compare require only route_refs')
        return self


class HoldingsReadInput(DTO):
    query: str | None = None
    holding_refs: list[str] = Field(default_factory=list)
    include_expired: bool = False


class HoldingsWriteInput(DTO):
    operation: Literal['create', 'update', 'delete']
    holding_ref: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    identity: IdentityInput | None = None
    valid_until: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')

    @model_validator(mode='after')
    def check_operation(self):
        if self.operation == 'create' and (self.identity is None or self.holding_ref is not None):
            raise ValueError('create requires identity, not holding_ref')
        if self.operation == 'create' and self.expected_revision is not None:
            raise ValueError('expected_revision applies only to update/delete')
        if self.operation != 'create' and (not self.holding_ref or self.expected_revision is None):
            raise ValueError('update/delete require holding_ref and expected_revision')
        if self.operation == 'delete' and {'identity','valid_until'} & self.model_fields_set:
            raise ValueError('delete cannot include identity or valid_until')
        if self.operation == 'update' and not ({'identity','valid_until'} & self.model_fields_set):
            raise ValueError('update requires identity or valid_until')
        if 'identity' in self.model_fields_set and self.identity is None:
            raise ValueError('identity cannot be cleared; omit it to keep the identity')
        if self.valid_until is not None:
            from datetime import date
            date.fromisoformat(self.valid_until)
        return self


class WorkspaceReadInput(DTO):
    kind: Literal['history', 'artifact', 'presentations', 'notes']
    query: str | None = None
    refs: list[str] = Field(default_factory=list)
    cursor: str | None = None
    limit: int = Field(default=10, ge=1, le=30)


class NoteInput(DTO):
    expected_revision: int = Field(ge=0)
    content: str = Field(max_length=8000)

    @model_validator(mode='after')
    def check_note_budget(self):
        from journeyplus.agent.harness.budget import estimate
        if estimate(self.model_dump(mode='json')) > 2000:
            raise ValueError('Task note exceeds 2000 estimated tokens; keep a concise note with source references')
        return self


class SearchInput(DTO):
    query: str = Field(min_length=1, max_length=500)
    scope: Literal['statusmatcher', 'web'] = 'statusmatcher'
    domains: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=5, ge=1, le=10)
    cursor: str | None = None


class WebReadInput(DTO):
    url: str = Field(pattern=r'^https://', max_length=4096)
    sections: list[str] = Field(default_factory=list)
    refresh: bool = False
    max_chars: int = Field(default=12000, ge=1000, le=30000)
    include_controls: bool = Field(default=False,description='Include form option text when needed; choices in a form are not article/report evidence.')
    cursor: str | None = Field(default=None,description='Continue the same URL and sections from next_cursor; no refetch. Cannot combine with refresh.')

    @model_validator(mode='after')
    def cursor_without_refresh(self):
        if self.cursor and self.refresh:raise ValueError('A page cursor cannot refresh its immutable snapshot')
        return self


class ResearchSubject(DTO):
    source: IdentityInput | None = None
    target: IdentityInput | None = None


class ResearchInput(DTO):
    page_refs: list[str] = Field(min_length=1, max_length=8)
    subject: ResearchSubject | None = None
    method: Literal['MATCH', 'CHALLENGE'] | None = None


class SelectionRole(DTO):
    ref: str
    role: Literal['primary', 'alternative']


class BlockSelection(DTO):
    type: Literal['activity_card', 'route_graph', 'comparison', 'evidence', 'experience']
    object_refs: list[str] = Field(min_length=1, max_length=20)
    title: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=500)
    roles: list[SelectionRole] = Field(default_factory=list,description='Optional; at most one primary, all others alternative.')
    columns: list[Literal['cost', 'steps', 'challenge', 'eligibility', 'window', 'validity', 'conditions']] = Field(default_factory=list, max_length=7, description='Comparison only: conditions is verbatim rule text; eligibility is PASS/FAIL/UNKNOWN; window and validity are per-step facts.')
    research_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def check_selection(self):
        if any(r.ref not in self.object_refs for r in self.roles) or sum(r.role == 'primary' for r in self.roles) > 1:
            raise ValueError('roles must select displayed objects and at most one primary')
        if self.columns and self.type != 'comparison':
            raise ValueError('columns apply only to comparison')
        return self


class NextStep(DTO):
    label: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=500)
    subject_refs: list[str] = Field(default_factory=list, max_length=12)


class DisplayInput(DTO):
    blocks: list[BlockSelection] = Field(max_length=6)
    next_steps: list[NextStep] = Field(default_factory=list, max_length=3)
    replace_presentation_ref: str | None = None

    @model_validator(mode='after')
    def check_content(self):
        if not self.blocks and not self.next_steps:
            raise ValueError('presentation requires blocks or next_steps')
        return self


class WaitingInput(DTO):
    operation: Literal['list', 'create', 'update', 'cancel']
    goal_ref: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
    query_ref: str | None = None
    query: RouteRequest | None = None
    limit: int = Field(default=10,ge=1,le=20,description='Maximum waiting goals per list page.')
    cursor: str | None = Field(default=None,description='Continue list with its returned cursor.')

    @model_validator(mode='after')
    def check_operation(self):
        if self.operation == 'list' and self.model_fields_set - {'operation','limit','cursor'}:
            raise ValueError('list accepts only operation, limit and cursor; no write fields are used')
        if self.operation != 'list' and {'limit','cursor'} & self.model_fields_set:
            raise ValueError('limit/cursor apply only to list')
        if self.operation == 'create' and {'goal_ref','expected_revision'} & self.model_fields_set:
            raise ValueError('create cannot include goal_ref or expected_revision')
        if self.operation == 'cancel' and {'query','query_ref'} & self.model_fields_set:
            raise ValueError('cancel cannot include a replacement query')
        if self.operation in {'update', 'cancel'} and (not self.goal_ref or self.expected_revision is None):
            raise ValueError('update/cancel require goal_ref and expected_revision')
        if self.operation in {'create', 'update'} and (bool(self.query) == bool(self.query_ref)):
            raise ValueError('create/update require exactly one query or query_ref')
        return self


INPUTS = {
    'catalog.lookup': CatalogInput, 'activity.read': ActivityInput, 'routes.evaluate': RoutesInput,
    'holdings.read': HoldingsReadInput, 'holdings.write': HoldingsWriteInput,
    'workspace.read': WorkspaceReadInput, 'workspace.note': NoteInput,
    'web.search': SearchInput, 'web.read': WebReadInput, 'research.parse': ResearchInput,
    'display.present': DisplayInput, 'waiting.manage': WaitingInput,
}
