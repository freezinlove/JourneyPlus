from __future__ import annotations

from typing import Annotated, Literal
from decimal import Decimal
from uuid import UUID

from pydantic import Field, RootModel, model_validator
from journeyplus.contracts import StrictModel as BaseStrictModel


class StrictModel(BaseStrictModel):
    """Optional empty collections tolerate null; required data remains strict.

    This is local to the workspace protocol, not workflow fact ingestion. A
    model's unused optional list is equivalent to omitting that argument; it
    must not consume a second model call or become an 'unstructured' failure.
    """
    @model_validator(mode='before')
    @classmethod
    def optional_empty_lists(cls, value):
        if not isinstance(value,dict):return value
        return {key:([] if item is None and key in cls.model_fields
                     and cls.model_fields[key].default_factory is list else item)
                for key,item in value.items()}


class ContentSelection(StrictModel):
    type: Literal["activity_card","route_graph","route_comparison","evidence_answer","experience_summary","text"]
    subject_refs:list[str]=Field(default_factory=list,max_length=12)
    fact_refs:list[str]=Field(default_factory=list,max_length=30)
    reason:str=""
    graph_mode:Literal['EXPLORE','RECOMMEND']='EXPLORE'
    columns:list[Literal["cost","steps","challenge","eligibility","window","validity"]]=Field(default_factory=list,max_length=6)


class NextStep(StrictModel):
    label:str=Field(min_length=1,max_length=60)
    message:str=Field(min_length=1,max_length=500)
    subject_refs:list[str]=Field(default_factory=list,max_length=12)


class AnswerPayload(StrictModel):
    text:str=Field(min_length=1,max_length=6000)
    blocks:list[ContentSelection]=Field(default_factory=list,max_length=6)
    next_steps:list[NextStep]=Field(default_factory=list,max_length=3)
    claim_refs:list[str]=Field(default_factory=list,max_length=50)


class TaskUpdate(StrictModel):
    intent: Literal['CHAT','ACTIVITY','ROUTES','PUBLIC_OPPORTUNITIES','HOLDINGS']
    target_scope: Literal['UNSPECIFIED','ANY','SELECTED'] = 'UNSPECIFIED'
    category_scope: Literal['UNSPECIFIED','ANY','SELECTED'] = 'UNSPECIFIED'
    source_text: str | None = Field(default=None,max_length=160,description='本轮合并后实际用于查询的起点项目及等级文字。结合最新用户输入更新；省略句中的新会籍也表示更换起点，不能复制旧起点。目录身份仍由工具核实。')
    source_count: int | None = Field(default=None,ge=1,le=20,description='用户明确提供的起点会籍数量。单个简称或含糊等级仍是 1，不能把身份候选解释成持有多个等级；只有用户明确多张会籍才大于 1。')
    target_changed: bool = Field(default=False,description='只有本轮明确改换或取消目标才为 true；补充起点、回答起点所属项目不改变目标。所有到某项目的路径仍是 SELECTED，不是 ANY。')
    target_text: str | None = Field(default=None,max_length=160,description='用户明确指定的目标原话（项目及等级）；即使起点缺失仍先保留。此文本不是目录 ID，查询前必须定位真实引用。')
    source_changed: bool = Field(default=False,description='用户本轮更换/新增/清空起点或合并已存会籍为 true；包括上下文省略句“另一张会籍呢”。只改目标或当前范围内翻页为 false。先识别最新输入的变化，再继承未改变条件。')


class ContextDecision(StrictModel):
    task_update: TaskUpdate | None = Field(default=None,description='本轮语义状态；不限用 ANY，切换话题更新 intent。临时状态不保存用户会籍。')


class AnswerDecision(ContextDecision):
    action:Literal["ANSWER"]
    payload:AnswerPayload


class AskPayload(StrictModel):
    field: Literal['SOURCE_PROGRAM','SOURCE_TIER','TARGET_IDENTITY','OTHER'] = Field(default='OTHER',description='实际缺失的身份条件；起点等级歧义选 SOURCE_TIER，不能将候选等级全部作为用户会籍。')
    question:str=Field(min_length=1,max_length=500)
    reason:str=Field(default="",max_length=1000)
    choices:list[str]=Field(default_factory=list,max_length=5)


class AskDecision(ContextDecision):
    action:Literal["ASK"]
    payload:AskPayload


class ActivitySelector(StrictModel):
    text: str | None = Field(default=None, description="CATALOG 时填写所需起点或目标的项目名称，用确定的官方名称检索；其他视图填写所问活动名称。身份定位不要求存在匹配活动。")
    ref: str | None = Field(default=None, description="已披露的活动、项目或等级短引用")
    alternate_names: list[str] = Field(default_factory=list,max_length=3,description="仅 CATALOG：同时提供该项目确定的官方名/英文名/缩写作为检索词，尤其用户使用中文简称时；只做目录检索，不代表身份已确认，不填其他项目或等级。")


class ActivityReadArgs(StrictModel):
    selector: ActivitySelector
    question: str = ""
    view: Literal["AUTO","CATALOG","OVERVIEW","DETAIL","EVIDENCE","CHANGES"] = Field(default="AUTO",description="CATALOG 只定位项目和等级身份，不读取活动正文；其余视图查询活动资料。")
    aspects: list[Literal["PRICE","ELIGIBILITY","CHALLENGE","WINDOW","VALIDITY","APPLICATION"]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    section_refs: list[str] = Field(default_factory=list)
    version_ref: str | None = None


class RouteToolQuery(StrictModel):
    target_program_id: str | None = Field(default=None,description="目的地项目的program_ref，不是活动ref或起点项目")
    target_tier_id: str | None = Field(default=None,description="目的地等级tier_ref；用户未指定目标等级则留空")
    starting_tier_ids: list[str] = Field(default_factory=list,max_length=20,description="用户本轮提到的起点等级tier_ref；已有会籍默认由服务器读取")
    use_saved_holdings: bool | None = Field(default=None,description="默认有显式起点时只用这些起点；没有起点才使用已保存会籍。false 用于假设没有会籍；true 仅用户明确要求合并已保存会籍。")
    alliance: str | None = None
    category: str | None = None
    free_only: bool = False
    max_amount: Decimal | None = Field(default=None,ge=0)
    currency: str | None = None
    allow_challenge: bool | None = Field(default=None,description='只有用户明确拒绝挑战才填 false；用户未提挑战时必须留空，不能把“只差预算”解释成拒绝挑战。')
    source_acquisition: Literal["EARNED","MATCHED","UNKNOWN"] = Field(default="UNKNOWN",description="只有用户明确说明该起点通过住宿/飞行积累取得才填 EARNED，明确通过匹配取得才填 MATCHED。用户只说持有某会籍时必须 UNKNOWN，不能推断正常积累取得。")
    residency: str | None = None
    prior_participation: str | None = None
    preferences: list[Literal['FEWER_STEPS','LOWER_KNOWN_FEE','LESS_UNCERTAINTY']] = Field(default_factory=list,max_length=3)
    require_proven_eligibility: bool = False


class RouteReadArgs(StrictModel):
    mode: Literal["EXPLORE","COMPARE","INSPECT"] = "EXPLORE"
    query: RouteToolQuery | None = None
    route_refs: list[str] = Field(default_factory=list,max_length=3)
    cursor: str | None = Field(default=None,max_length=2048,description='原样使用上次 next_cursor 继续读取同一快照，不能改写')


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


class ReadDecision(ContextDecision):
    action:Literal["READ"]
    payload:ReadPayload


class ProposalPayload(StrictModel):
    kind:Literal["HOLDING_SAVE","HOLDING_EDIT","QUERY_ADJUST","WAIT_CREATE","WAIT_CONTINUE"]
    changes:dict=Field(default_factory=dict)
    query:RouteToolQuery|None=Field(default=None,description='仅 QUERY_ADJUST：需要程序评估的原始查询条件，保留用户原预算；由程序计算最小调整，不要把建议金额填入原查询。')
    reason:str=Field(min_length=1,max_length=1000)
    support_refs:list[str]=Field(default_factory=list,max_length=12)


class ProposalDecision(ContextDecision):
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
