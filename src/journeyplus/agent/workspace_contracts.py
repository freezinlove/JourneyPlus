from __future__ import annotations

from typing import Annotated, Literal
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


class ReadRequest(StrictModel):
    tool:Literal["query_activity_materials","query_membership_routes","research_statusmatcher"]
    args:dict=Field(default_factory=dict)


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
