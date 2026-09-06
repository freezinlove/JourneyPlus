"""Separate server search state, model disclosure and browser presentation DTOs.

Domain facts retain their validated JSON values. These transport contracts reject
ORM instances and undeclared containers; only the server result owns full caches.
"""
from typing import Literal
from pydantic import Field, JsonValue, ValidationError, model_validator
from journeyplus.contracts import StrictModel

JsonObject=dict[str,JsonValue]


class DecisionData(StrictModel):
    view:Literal['ROUTE_OVERVIEW']|None=None
    material_caveats:dict[str,str]=Field(default_factory=dict)
    temporal_facts:dict[str,JsonObject]=Field(default_factory=dict)
    activities:list[JsonObject]=Field(default_factory=list)
    facts:list[JsonObject]=Field(default_factory=list)
    snippets:list[JsonObject]=Field(default_factory=list)
    changes:list[JsonObject]=Field(default_factory=list)
    catalog:JsonObject|list[JsonObject]|None=None
    cards:list[JsonObject]=Field(default_factory=list)
    routes:list[JsonObject]=Field(default_factory=list)
    steps:dict[str,JsonObject]=Field(default_factory=dict)
    groups:list[JsonObject]=Field(default_factory=list)
    query:JsonObject|None=None
    reason_counts:dict[str,int]=Field(default_factory=dict)
    step_observations:list[JsonObject]=Field(default_factory=list)
    research_steps:list[JsonObject]=Field(default_factory=list)
    official_rechecks:list[JsonObject]=Field(default_factory=list)
    node:JsonObject|None=None


class ModelDecisionPacket(StrictModel):
    schema_version:Literal[1]=1
    status:str
    snapshot_ref:str|None=None
    data:DecisionData=Field(default_factory=DecisionData)
    coverage:JsonObject=Field(default_factory=dict)
    caveats:list[str]=Field(default_factory=list)
    expansions:list[JsonObject]=Field(default_factory=list)
    provenance:list[JsonObject]=Field(default_factory=list)
    next_cursor:str|None=None
    message:str|None=None
    reason:str|None=None
    instruction:str|None=None
    omitted_item_count:int|None=Field(default=None,ge=0)


class ServerRouteResult(ModelDecisionPacket):
    server_routes:dict[str,JsonObject]
    server_steps:dict[str,JsonObject]
    snapshot:dict[str,str]

    @model_validator(mode='after')
    def complete_references(self):
        for ref,route in self.server_routes.items():
            if route.get('ref')!=ref or any(step not in self.server_steps for step in route.get('step_refs',[])):
                raise ValueError('Server route contains an unresolved step')
        return self


class PresentationData(StrictModel):
    routes:list[JsonObject]=Field(default_factory=list)
    steps:dict[str,JsonObject]=Field(default_factory=dict)
    nodes:dict[str,JsonObject]=Field(default_factory=dict)
    activities:list[JsonObject]=Field(default_factory=list)
    materials:list[JsonObject]=Field(default_factory=list)
    research:list[JsonObject]=Field(default_factory=list)
    comparison_rows:list[JsonObject]=Field(default_factory=list)
    evidence_ordering:JsonObject|None=None

    @model_validator(mode='after')
    def complete_references(self):
        for route in self.routes:
            if any(ref not in self.steps for ref in route.get('step_refs',[])):
                raise ValueError('Presentation route contains an unresolved step')
        return self


def validated_packet(value):
    try:return ModelDecisionPacket.model_validate(value).model_dump(mode='json',exclude_unset=True)
    except ValidationError as exc:raise ValueError('Model disclosure contract rejected server data') from exc


def validated_presentation(value):
    try:return PresentationData.model_validate(value).model_dump(mode='json',exclude_unset=True)
    except ValidationError as exc:raise ValueError('Presentation contract rejected server data') from exc
