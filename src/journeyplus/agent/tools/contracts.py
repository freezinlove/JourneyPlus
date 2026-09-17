"""Explicit, independently callable business inputs; no conversation state."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from journeyplus.agent.harness.contracts import DTO


class IdentityRef(DTO):
    ref: str = Field(min_length=1, max_length=300)


class IdentityName(DTO):
    program_name: str = Field(min_length=1, max_length=300,
        description='Original or official program/carrier/hotel name; registered aliases are normalized by the tool.')
    tier_name: str | None = Field(default=None, min_length=1, max_length=300,
        description='Original or official tier name; no need to translate it. Omit for a program-only destination. A source must resolve to a tier; candidate tiers are not user-provided conditions.')
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
    view: Literal['overview', 'detail', 'evidence', 'original', 'changes', 'mappings'] = Field(default='overview', description='mappings requires one uniquely selected activity version; use a specific activity reference after locating it. A broad query may match zero or multiple activities and cannot select a complete mapping table.')
    aspects: list[Literal['price', 'eligibility', 'challenge', 'window', 'validity', 'application']] = Field(default_factory=list)
    version_ref: str | None = None
    section_refs: list[str] = Field(default_factory=list)
    cursor: str | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode='after')
    def original_document(self):
        if any(ref.startswith('document:') for ref in self.section_refs):
            self.view='original'
        if self.view=='original' and (len(self.section_refs)!=1 or not self.section_refs[0].startswith('document:')):
            raise ValueError('Select one archived document using section_refs=[document:UUID] from the source directory; use view=evidence to list documents')
        return self


class Sources(DTO):
    mode: Literal['explicit', 'saved', 'none']
    saved_program: str | None = Field(default=None, min_length=1, description='Only for mode=saved: select effective saved memberships of this programme by name/alias, resolve the tier and search in one call. Omit to use all saved memberships.')
    identities: list[IdentityInput] = Field(default_factory=list, max_length=20)
    holding_refs: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def check_sources(self):
        if self.saved_program is not None and (self.mode != 'saved' or not self.saved_program.strip()):
            raise ValueError('saved_program requires saved mode and a nonblank programme name')
        count = len(self.identities) + len(self.holding_refs)
        if self.mode == 'explicit' and not 1 <= count <= 20:
            raise ValueError('explicit sources require 1..20 identities or holding_refs')
        if self.mode != 'explicit' and count:
            raise ValueError('saved/none sources cannot include explicit identities')
        return self


class Constraints(DTO):
    free_only: bool = Field(default=False, description='True: free matching only. False: allow both free and paid. Region and exact price are activity details, not search filters.')


class RouteRequest(DTO):
    sources: Sources = Field(description="Required source selection. Use identities grounded in the user conversation or saved holdings when requested. A destination or catalogue candidate does not establish the user source; do not invent tiers to satisfy this parameter.")
    target: IdentityInput | None = Field(default=None,description='Requested destination; omit for all destinations.')
    category: Literal['AIRLINE', 'HOTEL', 'CRUISE', 'OTHER'] | None = Field(default=None,
        description='Only an explicit destination restriction; omit for all paths.')
    alliance: str | None = None
    constraints: Constraints = Field(default_factory=Constraints)


class QueryPatch(DTO):
    sources: Sources | None = None
    target: IdentityInput | None = None
    category: Literal['AIRLINE', 'HOTEL', 'CRUISE', 'OTHER'] | None = None
    alliance: str | None = None
    constraints: dict | None = None


class RoutesInput(DTO):
    operation: Literal['search', 'inspect', 'compare']
    query: RouteRequest | None = None
    query_ref: str | None = Field(default=None,description='QUERY ref: replay unchanged, use cursor for pages or patch for changes.')
    patch: QueryPatch | None = Field(default=None,description='RFC7396 RouteRequest patch with query_ref. sources/target replace whole objects. Null clears, omission inherits.')
    route_refs: list[str] = Field(default_factory=list, max_length=12)
    cursor: str | None = Field(default=None,description='Continue returned next_cursor with operation="search" and the same query_ref; omit query and patch. There is no next_page operation.')
    limit: int | None = Field(default=None, ge=1, description='Omit to return all selected paths. Set only when requesting an explicit smaller page.')

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


class SelectionRole(DTO):
    ref: str
    role: Literal['primary', 'alternative']


class BlockSelection(DTO):
    type: Literal['activity_card', 'route_graph', 'comparison', 'evidence', 'experience', 'mapping_table']
    object_refs: list[str] = Field(min_length=1, max_length=20)
    title: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=500)
    roles: list[SelectionRole] = Field(default_factory=list,description='Optional; at most one primary, all others alternative.')
    research_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='before')
    @classmethod
    def ignore_layout_options(cls, value):
        # Columns are a renderer concern. Old model/history calls may still
        # supply them; ignore only this harmless option, not invalid references.
        if isinstance(value, dict):
            return {key: item for key, item in value.items() if key != 'columns'}
        return value

    @property
    def columns(self):
        return ['cost', 'steps'] if self.type == 'comparison' else []

    @model_validator(mode='after')
    def check_selection(self):
        if any(r.ref not in self.object_refs for r in self.roles) or sum(r.role == 'primary' for r in self.roles) > 1:
            raise ValueError('roles must select displayed objects and at most one primary')
        return self


class NextStep(DTO):
    label: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=500)
    subject_refs: list[str] = Field(default_factory=list, max_length=12)


class DisplayInput(DTO):
    answer: str | None = Field(default=None, description='Optional complete natural-language reply shown above the visuals. Put your final explanation here when this response contains only tool calls; do not duplicate text already spoken in the same response.')
    complete: bool = Field(default=False, description='Set true when your accompanying natural-language answer and this display complete the request. Successful display-only batches then end without another model call. Leave false if you plan to continue; failures and mixed tool batches always return to you.')
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
    'web.search': SearchInput, 'web.read': WebReadInput,
    'display.present': DisplayInput, 'waiting.manage': WaitingInput,
}
