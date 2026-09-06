from __future__ import annotations

from typing import Annotated, Literal
from decimal import Decimal
from uuid import UUID

from pydantic import Field, RootModel
from journeyplus.contracts import StrictModel


class ContentSelection(StrictModel):
    type: Literal["activity_card","route_graph","route_comparison","evidence_answer","experience_summary","text"]
    subject_refs:list[str]=Field(default_factory=list,max_length=12)
    fact_refs:list[str]=Field(default_factory=list,max_length=30)
    reason:str=""
    columns:list[str]=Field(default_factory=list,max_length=8)


class NextStep(StrictModel):
    label:str=Field(min_length=1,max_length=60)
    message:str=Field(min_length=1,max_length=500)
    subject_refs:list[str]=Field(default_factory=list,max_length=12)


class AnswerPayload(StrictModel):
    text:str=Field(min_length=1,max_length=6000)
    blocks:list[ContentSelection]=Field(default_factory=list,max_length=6)
    next_steps:list[NextStep]=Field(default_factory=list,max_length=3)
    claim_refs:list[str]=Field(default_factory=list,max_length=50)


class AnswerDecision(StrictModel):
    action:Literal["ANSWER"]
    payload:AnswerPayload


class AskPayload(StrictModel):
    question:str=Field(min_length=1,max_length=500)
    reason:str=Field(default="",max_length=1000)
    choices:list[str]=Field(default_factory=list,max_length=5)


class AskDecision(StrictModel):
    action:Literal["ASK"]
    payload:AskPayload


class ActivitySelector(StrictModel):
    text: str | None = Field(default=None, description="目标活动或项目名称；A到B的路径问题先定位B")
    ref: str | None = Field(default=None, description="已披露的活动、项目或等级短引用")


class ActivityReadArgs(StrictModel):
    selector: ActivitySelector
    question: str = ""
    view: Literal["AUTO","OVERVIEW","DETAIL","EVIDENCE","CHANGES"] = "AUTO"
    aspects: list[Literal["PRICE","ELIGIBILITY","CHALLENGE","WINDOW","VALIDITY","APPLICATION"]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    section_refs: list[str] = Field(default_factory=list)
    version_ref: str | None = None


class RouteToolQuery(StrictModel):
    target_program_id: str | None = Field(default=None,description="目的地项目的program_ref，不是活动ref或起点项目")
    target_tier_id: str | None = Field(default=None,description="目的地等级tier_ref；用户未指定目标等级则留空")
    starting_tier_ids: list[str] = Field(default_factory=list,max_length=20,description="用户本轮提到的起点等级tier_ref；已有会籍默认由服务器读取")
    alliance: str | None = None
    category: str | None = None
    free_only: bool = False
    max_amount: Decimal | None = Field(default=None,ge=0)
    currency: str | None = None
    allow_challenge: bool | None = None
    source_acquisition: Literal["EARNED","MATCHED","UNKNOWN"] = "UNKNOWN"
    residency: str | None = None
    require_proven_eligibility: bool = False


class RouteReadArgs(StrictModel):
    mode: Literal["EXPLORE","COMPARE","INSPECT"] = "EXPLORE"
    query: RouteToolQuery | None = None
    route_refs: list[str] = Field(default_factory=list,max_length=3)


class ResearchReadArgs(StrictModel):
    step_refs: list[str] = Field(default_factory=list,max_length=12)
    question: str = ""
    refresh: bool = False


class ActivityReadRequest(StrictModel):
    tool: Literal["query_activity_materials"]
    args: ActivityReadArgs


class RouteReadRequest(StrictModel):
    tool: Literal["query_membership_routes"]
    args: RouteReadArgs


class ResearchReadRequest(StrictModel):
    tool: Literal["research_statusmatcher"]
    args: ResearchReadArgs


ReadRequest = Annotated[ActivityReadRequest|RouteReadRequest|ResearchReadRequest,Field(discriminator="tool")]


class ReadPayload(StrictModel):
    requests:list[ReadRequest]=Field(min_length=1,max_length=3)


class ReadDecision(StrictModel):
    action:Literal["READ"]
    payload:ReadPayload


class ProposalPayload(StrictModel):
    kind:Literal["HOLDING_SAVE","HOLDING_EDIT","QUERY_ADJUST","WAIT_CREATE","WAIT_CONTINUE"]
    changes:dict
    reason:str=Field(min_length=1,max_length=1000)
    support_refs:list[str]=Field(default_factory=list,max_length=12)


class ProposalDecision(StrictModel):
    action:Literal["PROPOSE"]
    payload:ProposalPayload


class WorkspaceDecision(RootModel[Annotated[AnswerDecision|AskDecision|ReadDecision|ProposalDecision,Field(discriminator="action")]]):
    pass


class MessageRequest(StrictModel):
    text:str=Field(min_length=1,max_length=6000)
    client_message_id:str=Field(min_length=1,max_length=100)
    expected_revision:int=Field(ge=0)
    subject_refs:list[str]=Field(default_factory=list,max_length=12)


class ConfirmRequest(StrictModel):
    pending_action_id:UUID
    expected_revision:int=Field(ge=0)
    client_action_id:str=Field(min_length=1,max_length=100)
    decision:Literal["CONFIRM","REJECT"]
