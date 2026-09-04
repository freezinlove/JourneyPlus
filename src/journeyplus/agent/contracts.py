from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from journeyplus.contracts import StrictModel
from journeyplus.membership.contracts import AirlineAlliance
from journeyplus.product.contracts import (
    CandidateConstraints,
    CandidateRoute,
    CandidateRouteQuery,
    CandidateRouteResult,
    CandidateTarget,
)


class AgentInteractionStatus(StrEnum):
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    AWAITING_HOLDING_CONFIRMATION = "AWAITING_HOLDING_CONFIRMATION"
    AWAITING_ADJUSTMENT_CONFIRMATION = "AWAITING_ADJUSTMENT_CONFIRMATION"
    AWAITING_WAIT_CONFIRMATION = "AWAITING_WAIT_CONFIRMATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentCommand(StrEnum):
    MESSAGE = "MESSAGE"
    CONFIRM = "CONFIRM"
    REJECT = "REJECT"
    CANCEL_WAIT = "CANCEL_WAIT"
    FINISH_WAIT = "FINISH_WAIT"


class AgentAction(StrEnum):
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    CONFIRM_HOLDINGS = "CONFIRM_HOLDINGS"
    QUERY_CANDIDATES = "QUERY_CANDIDATES"
    RESEARCH_EXPERIENCE = "RESEARCH_EXPERIENCE"
    RECOMMEND = "RECOMMEND"
    PROPOSE_ADJUSTMENT = "PROPOSE_ADJUSTMENT"
    OFFER_WAITING = "OFFER_WAITING"
    COMPLETE = "COMPLETE"


class HoldingMention(StrictModel):
    program: str = Field(min_length=1, max_length=300)
    tier: str = Field(min_length=1, max_length=300)
    valid_until: date | None = None


class ResolvedHolding(StrictModel):
    program_key: str = Field(min_length=1, max_length=300)
    tier_key: str = Field(min_length=1, max_length=300)
    program_display_name: str = Field(min_length=1, max_length=300)
    tier_display_name: str = Field(min_length=1, max_length=300)
    valid_until: date | None = None


class InterpretedTarget(StrictModel):
    program: str | None = Field(default=None, min_length=1, max_length=300)
    tier: str | None = Field(default=None, min_length=1, max_length=300)
    alliance: AirlineAlliance | None = None
    relative_level: Literal["ANY", "HIGH"] = "ANY"

    @model_validator(mode="after")
    def has_scope(self) -> "InterpretedTarget":
        if self.program is None and self.alliance is None:
            raise ValueError("interpreted target requires a program or alliance")
        return self


class StrategyInterpretation(StrictModel):
    holdings: list[HoldingMention] = Field(default_factory=list, max_length=20)
    target: InterpretedTarget
    constraints: CandidateConstraints = Field(default_factory=CandidateConstraints)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    research_statusmatcher: bool = False

    @field_validator("holdings", "preferences", mode="before")
    @classmethod
    def null_collections_are_empty(cls, value):
        return [] if value is None else value


class InterpretationDecision(StrictModel):
    action: Literal[
        AgentAction.ASK_CLARIFICATION,
        AgentAction.CONFIRM_HOLDINGS,
        AgentAction.QUERY_CANDIDATES,
    ]
    interpretation: StrategyInterpretation
    question: str | None = Field(default=None, max_length=500)
    message: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def question_matches_action(self) -> "InterpretationDecision":
        if (self.action == AgentAction.ASK_CLARIFICATION) != (self.question is not None):
            raise ValueError("clarification action requires exactly one question")
        return self


class AdjustmentProposal(StrictModel):
    condition: Literal["cost_policy", "max_amount", "challenge_policy"]
    new_value: str = Field(min_length=1, max_length=100)
    route_id: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=1000)


class StrategyDecision(StrictModel):
    action: Literal[
        AgentAction.RESEARCH_EXPERIENCE,
        AgentAction.RECOMMEND,
        AgentAction.PROPOSE_ADJUSTMENT,
        AgentAction.OFFER_WAITING,
        AgentAction.COMPLETE,
    ]
    primary_route_id: str | None = Field(default=None, max_length=100)
    alternative_route_ids: list[str] = Field(default_factory=list, max_length=2)
    selected_research_route_ids: list[str] = Field(default_factory=list, max_length=3)
    adjustment: AdjustmentProposal | None = None
    message: str = Field(min_length=1, max_length=3000)
    risks: list[str] = Field(default_factory=list, max_length=10)

    @field_validator(
        "alternative_route_ids",
        "selected_research_route_ids",
        "risks",
        mode="before",
    )
    @classmethod
    def null_collections_are_empty(cls, value):
        return [] if value is None else value

    @model_validator(mode="after")
    def fields_match_action(self) -> "StrategyDecision":
        if self.action == AgentAction.RECOMMEND and self.primary_route_id is None:
            raise ValueError("recommendation requires a primary route")
        if self.action == AgentAction.RESEARCH_EXPERIENCE and not self.selected_research_route_ids:
            raise ValueError("research requires route ids")
        if (self.action == AgentAction.PROPOSE_ADJUSTMENT) != (self.adjustment is not None):
            raise ValueError("adjustment fields do not match action")
        return self


class ExperienceOutcome(StrEnum):
    MATCH = "MATCH"
    CHALLENGE = "CHALLENGE"
    DENY = "DENY"
    OTHER = "OTHER"


class ExperienceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT = "INSUFFICIENT"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"


class AgentWaitGoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    REPLACED = "REPLACED"


class WaitCheckStatus(StrEnum):
    NO_GOAL = "NO_GOAL"
    NO_HIT = "NO_HIT"
    DUPLICATE = "DUPLICATE"
    HIT = "HIT"
    FAILED = "FAILED"


class ExperienceReport(StrictModel):
    outcome: ExperienceOutcome
    source_program: str = Field(min_length=1, max_length=300)
    target_program: str = Field(min_length=1, max_length=300)
    source_tier: str | None = Field(default=None, max_length=300)
    target_tier: str | None = Field(default=None, max_length=300)
    summary: str = Field(min_length=1, max_length=600)


class StatusMatcherObservation(StrictModel):
    availability: ExperienceAvailability
    route_id: str = Field(min_length=1, max_length=100)
    source_urls: list[str] = Field(default_factory=list, max_length=10)
    observed_at: datetime
    comparable_report_count: int = Field(default=0, ge=0, le=100)
    outcome_counts: dict[ExperienceOutcome, int] = Field(default_factory=dict)
    signal: Literal["较强", "一般", "较弱", "证据不足", "暂不可用"]
    practical_notes: list[str] = Field(default_factory=list, max_length=10)
    reports: list[ExperienceReport] = Field(default_factory=list, max_length=20)
    limitation: str = Field(min_length=1, max_length=1000)


class AgentInteractionState(StrictModel):
    schema_version: str = "1"
    status: AgentInteractionStatus
    interpretation: StrategyInterpretation | None = None
    resolved_holdings: list[ResolvedHolding] = Field(default_factory=list, max_length=20)
    query: CandidateRouteQuery | None = None
    candidate_result: CandidateRouteResult | None = None
    proposed_adjustment: AdjustmentProposal | None = None
    adjustment_attempted: bool = False
    question_count: int = Field(default=0, ge=0, le=1)
    model_calls: int = Field(default=0, ge=0)
    action_audit: list[AgentAction] = Field(default_factory=list, max_length=20)


class AgentWaitGoalView(StrictModel):
    id: UUID
    status: AgentWaitGoalStatus
    query: CandidateRouteQuery
    preferences: list[str] = Field(default_factory=list, max_length=10)
    research_statusmatcher: bool = False
    pending_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WaitCheckSummary(StrictModel):
    status: WaitCheckStatus
    goal_id: UUID | None = None
    matching_count: int = Field(default=0, ge=0)
    agent_called: bool = False
    error: str | None = Field(default=None, max_length=1000)


class AgentTurnRequest(StrictModel):
    interaction_id: UUID | None = None
    command: AgentCommand = AgentCommand.MESSAGE
    message: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def message_is_present_when_needed(self) -> "AgentTurnRequest":
        if self.command == AgentCommand.MESSAGE and not (self.message or "").strip():
            raise ValueError("MESSAGE command requires message")
        return self


class AgentTurnResponse(StrictModel):
    schema_version: str = "1"
    available: bool = True
    interaction_id: UUID | None = None
    status: AgentInteractionStatus | None = None
    action: AgentAction | None = None
    message: str = Field(min_length=1, max_length=5000)
    allowed_commands: list[AgentCommand] = Field(default_factory=list, max_length=5)
    interpreted_request: StrategyInterpretation | None = None
    candidate_result: CandidateRouteResult | None = None
    primary_route: CandidateRoute | None = None
    alternative_routes: list[CandidateRoute] = Field(default_factory=list, max_length=2)
    risks: list[str] = Field(default_factory=list, max_length=10)
    proposed_adjustment: AdjustmentProposal | None = None
    experience: list[StatusMatcherObservation] = Field(default_factory=list, max_length=3)
    wait_goal: AgentWaitGoalView | None = None


class AgentStateResponse(StrictModel):
    schema_version: str = "1"
    available: bool
    interaction: AgentTurnResponse | None = None
    wait_goal: AgentWaitGoalView | None = None
    pending_result: AgentTurnResponse | None = None
