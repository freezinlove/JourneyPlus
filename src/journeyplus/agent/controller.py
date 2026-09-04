from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from journeyplus.agent.contracts import (
    AdjustmentProposal,
    AgentAction,
    AgentCommand,
    AgentInteractionState,
    AgentInteractionStatus,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentWaitGoalView,
    InterpretedTarget,
    InterpretationDecision,
    ResolvedHolding,
    StatusMatcherObservation,
    StrategyDecision,
    StrategyInterpretation,
)
from journeyplus.agent.prompts import (
    INTERPRET_SYSTEM_PROMPT,
    PROMPT_VERSION,
    STRATEGY_SYSTEM_PROMPT,
    interpretation_prompt,
    strategy_prompt,
)
from journeyplus.agent.waiting import WaitGoalError, WaitGoalService
from journeyplus.ai.provider import AIProvider
from journeyplus.membership.normalization import normalize_key, normalize_tier
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.models import AgentInteraction
from journeyplus.product.candidate_routes import CandidateRouteService
from journeyplus.product.contracts import (
    CandidateChallengePolicy,
    CandidateConstraints,
    CandidateCostPolicy,
    CandidateRelativeTier,
    CandidateRoute,
    CandidateRouteQuery,
    CandidateTarget,
    StatusHoldingInput,
)
from journeyplus.product.holdings import StatusHoldingService


class AgentStateError(RuntimeError):
    pass


class AgentProviderError(RuntimeError):
    pass


class ExperienceResearcher(Protocol):
    enabled: bool

    def research(self, route: CandidateRoute) -> StatusMatcherObservation: ...


_OUT_OF_SCOPE_RISK = re.compile(
    r"(?:休息室|贵宾室|行李|早餐|升房|退款|refund|申诉|客服)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _TurnBudget:
    limit: int
    calls: int = 0

    def take(self) -> None:
        if self.calls >= self.limit:
            raise AgentStateError("本回合模型调用已达到上限，请开始一个新请求。")
        self.calls += 1


class AgentController:
    def __init__(
        self,
        session: Session,
        provider: AIProvider,
        *,
        interaction_ttl: timedelta = timedelta(hours=24),
        max_model_calls: int = 3,
        experience_researcher: ExperienceResearcher | None = None,
        degrade_provider_errors: bool = True,
    ) -> None:
        if not 1 <= max_model_calls <= 3:
            raise ValueError("max_model_calls must be between 1 and 3")
        self._session = session
        self._provider = provider
        self._interaction_ttl = interaction_ttl
        self._max_model_calls = max_model_calls
        self._experience_researcher = experience_researcher
        self._degrade_provider_errors = degrade_provider_errors

    def turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        budget = _TurnBudget(self._max_model_calls)
        if request.command in {AgentCommand.CANCEL_WAIT, AgentCommand.FINISH_WAIT}:
            service = WaitGoalService(self._session)
            goal = (
                service.cancel()
                if request.command == AgentCommand.CANCEL_WAIT
                else service.finish()
            )
            return AgentTurnResponse(
                action=AgentAction.COMPLETE,
                message=(
                    "已取消持续跟进。"
                    if request.command == AgentCommand.CANCEL_WAIT
                    else "已结束持续跟进。"
                ),
                wait_goal=goal,
            )
        if request.interaction_id is None:
            if request.command != AgentCommand.MESSAGE:
                raise AgentStateError("新请求必须先提供自然语言目标。")
            return self._start(request.message or "", budget)

        record, state = self._load(request.interaction_id)
        if request.command == AgentCommand.MESSAGE:
            return self._reinterpret(record, state, request.message or "", budget)
        if request.command == AgentCommand.CONFIRM:
            return self._confirm(record, state, budget)
        if request.command == AgentCommand.REJECT:
            return self._reject(record, state, budget)
        raise AgentStateError("不支持的 Agent 命令。")

    def resume_wait_goal(
        self,
        goal: AgentWaitGoalView,
        result,
    ) -> AgentTurnResponse:
        budget = _TurnBudget(self._max_model_calls)
        target = goal.query.target
        interpretation = StrategyInterpretation(
            holdings=[],
            target=InterpretedTarget(
                program=target.program_key,
                tier=target.tier_key,
                alliance=target.alliance,
                relative_level=target.relative_tier,
            ),
            constraints=goal.query.constraints,
            preferences=goal.preferences,
            research_statusmatcher=goal.research_statusmatcher,
        )
        state = AgentInteractionState(
            status=AgentInteractionStatus.COMPLETED,
            interpretation=interpretation,
            query=goal.query,
            candidate_result=result,
            adjustment_attempted=True,
        )
        record = AgentInteraction(
            status=state.status,
            state=state.model_dump(mode="json"),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            prompt_version=PROMPT_VERSION,
            schema_version=state.schema_version,
            expires_at=datetime.now(UTC) + self._interaction_ttl,
        )
        self._session.add(record)
        self._session.flush()
        allowed = [AgentAction.RECOMMEND]
        if (
            self._experience_researcher is not None
            and self._experience_researcher.enabled
            and goal.research_statusmatcher
        ):
            allowed = [AgentAction.RESEARCH_EXPERIENCE]
        return self._strategy(record, state, allowed, budget)

    def latest_response(self) -> AgentTurnResponse | None:
        record = self._session.scalar(
            select(AgentInteraction)
            .order_by(AgentInteraction.updated_at.desc(), AgentInteraction.id.desc())
            .limit(1)
        )
        if record is None or record.last_response is None:
            return None
        return AgentTurnResponse.model_validate(record.last_response)

    def _start(self, message: str, budget: _TurnBudget) -> AgentTurnResponse:
        state, decision = self._interpret(message, None, budget)
        record = AgentInteraction(
            status=state.status,
            state=state.model_dump(mode="json"),
            provider=self._provider.metadata.provider,
            model=self._provider.metadata.model,
            prompt_version=PROMPT_VERSION,
            schema_version=state.schema_version,
            expires_at=datetime.now(UTC) + self._interaction_ttl,
        )
        self._session.add(record)
        self._session.flush()
        return self._after_interpretation(record, state, decision, budget)

    def _reinterpret(
        self,
        record: AgentInteraction,
        previous: AgentInteractionState,
        message: str,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        if previous.status in {AgentInteractionStatus.COMPLETED, AgentInteractionStatus.FAILED}:
            raise AgentStateError("该交互已经结束，请开始一个新请求。")
        state, decision = self._interpret(message, previous, budget)
        state = state.model_copy(
            update={
                "question_count": previous.question_count,
                "model_calls": previous.model_calls + state.model_calls,
                "action_audit": previous.action_audit,
            }
        )
        return self._after_interpretation(record, state, decision, budget)

    def _interpret(
        self,
        message: str,
        previous: AgentInteractionState | None,
        budget: _TurnBudget,
    ) -> tuple[AgentInteractionState, InterpretationDecision]:
        holdings = StatusHoldingService(self._session).list()
        catalog = UnifiedMembershipTreeService(self._session).catalog()
        catalog_lines = [
            f"{node.program} | {node.tier} | {node.program_key}::{node.tier_key}"
            + (f" | {node.alliance}" if node.alliance else "")
            for node in catalog.nodes[:300]
        ]
        decision = self._generate(
            budget,
            system_prompt=INTERPRET_SYSTEM_PROMPT,
            user_prompt=interpretation_prompt(
                message, holdings=holdings, catalog_lines=catalog_lines, previous=previous
            ),
            output_model=InterpretationDecision,
        )
        resolved, unresolved = self._resolve_holdings(decision.interpretation)
        query, target_error = self._resolve_query(decision.interpretation)
        question_count = previous.question_count if previous else 0
        question = decision.question
        if unresolved or target_error:
            if question_count >= 1:
                raise AgentStateError(
                    "一次关键确认后仍无法唯一识别会籍或目标，请开始新请求并使用目录中的项目和等级名称。"
                )
            question = target_error or unresolved[0]
            decision = decision.model_copy(
                update={
                    "action": AgentAction.ASK_CLARIFICATION,
                    "question": question,
                    "message": question,
                }
            )
        elif decision.action == AgentAction.ASK_CLARIFICATION and question_count >= 1:
            raise AgentStateError("每次交互最多提出一个关键问题。")
        state = AgentInteractionState(
            status=(
                AgentInteractionStatus.AWAITING_CLARIFICATION
                if decision.action == AgentAction.ASK_CLARIFICATION
                else AgentInteractionStatus.AWAITING_HOLDING_CONFIRMATION
            ),
            interpretation=decision.interpretation,
            resolved_holdings=resolved,
            query=query,
            question_count=question_count
            + int(decision.action == AgentAction.ASK_CLARIFICATION),
            model_calls=1,
        )
        return state, decision

    def _after_interpretation(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        decision: InterpretationDecision,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        if decision.action == AgentAction.ASK_CLARIFICATION:
            state = _audit(state, AgentAction.ASK_CLARIFICATION)
            response = AgentTurnResponse(
                interaction_id=record.id,
                status=state.status,
                action=AgentAction.ASK_CLARIFICATION,
                message=decision.question or decision.message,
                allowed_commands=[AgentCommand.MESSAGE, AgentCommand.REJECT],
                interpreted_request=state.interpretation,
            )
            return self._save(record, state, response)

        existing = {item.node_id for item in StatusHoldingService(self._session).list()}
        pending = [
            item
            for item in state.resolved_holdings
            if f"{item.program_key}::{item.tier_key}" not in existing
        ]
        if pending:
            state = state.model_copy(
                update={
                    "status": AgentInteractionStatus.AWAITING_HOLDING_CONFIRMATION,
                    "resolved_holdings": pending,
                }
            )
            state = _audit(state, AgentAction.CONFIRM_HOLDINGS)
            labels = "、".join(
                f"{item.program_display_name} {item.tier_display_name}" for item in pending
            )
            response = AgentTurnResponse(
                interaction_id=record.id,
                status=state.status,
                action=AgentAction.CONFIRM_HOLDINGS,
                message=f"我理解你目前持有：{labels}。确认后会保存并据此查询；也可以直接改正。",
                allowed_commands=[
                    AgentCommand.CONFIRM,
                    AgentCommand.MESSAGE,
                    AgentCommand.REJECT,
                ],
                interpreted_request=state.interpretation,
            )
            return self._save(record, state, response)

        if not StatusHoldingService(self._session).list():
            state = state.model_copy(
                update={"status": AgentInteractionStatus.AWAITING_CLARIFICATION}
            )
            state = _audit(state, AgentAction.ASK_CLARIFICATION)
            response = AgentTurnResponse(
                interaction_id=record.id,
                status=state.status,
                action=AgentAction.ASK_CLARIFICATION,
                message="还需要知道你目前持有的具体会籍项目和等级。",
                allowed_commands=[AgentCommand.MESSAGE, AgentCommand.REJECT],
                interpreted_request=state.interpretation,
            )
            return self._save(record, state, response)
        return self._query_and_decide(record, state, budget)

    def _confirm(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        if state.status == AgentInteractionStatus.AWAITING_HOLDING_CONFIRMATION:
            for holding in state.resolved_holdings:
                StatusHoldingService(self._session).upsert(
                    StatusHoldingInput(
                        program_key=holding.program_key,
                        tier_key=holding.tier_key,
                        valid_until=holding.valid_until,
                    )
                )
            return self._query_and_decide(record, state, budget)
        if state.status == AgentInteractionStatus.AWAITING_ADJUSTMENT_CONFIRMATION:
            if state.query is None or state.proposed_adjustment is None:
                raise AgentStateError("当前没有可确认的条件调整。")
            query = _apply_adjustment(state.query, state.proposed_adjustment)
            state = state.model_copy(
                update={
                    "query": query,
                    "proposed_adjustment": None,
                    "adjustment_attempted": True,
                }
            )
            return self._query_and_decide(record, state, budget)
        if state.status == AgentInteractionStatus.AWAITING_WAIT_CONFIRMATION:
            try:
                goal = WaitGoalService(self._session).create_from_confirmed_interaction(
                    state,
                    interaction_id=record.id,
                )
            except WaitGoalError as exc:
                raise AgentStateError(str(exc)) from exc
            state = state.model_copy(update={"status": AgentInteractionStatus.COMPLETED})
            state = _audit(state, AgentAction.COMPLETE)
            return self._save(
                record,
                state,
                AgentTurnResponse(
                    interaction_id=record.id,
                    status=state.status,
                    action=AgentAction.COMPLETE,
                    message="已按你确认的目标和条件开始持续跟进。没有新路线时不会调用 Agent 或打扰你。",
                    interpreted_request=state.interpretation,
                    candidate_result=state.candidate_result,
                    wait_goal=goal,
                ),
            )
        raise AgentStateError("当前状态没有可确认的操作。")

    def _reject(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        if state.status == AgentInteractionStatus.AWAITING_ADJUSTMENT_CONFIRMATION:
            state = state.model_copy(update={"adjustment_attempted": True})
            return self._offer_waiting(record, state, budget)
        if state.status == AgentInteractionStatus.AWAITING_WAIT_CONFIRMATION:
            return self._complete(record, state, "已保留当前条件，不建立持续跟进目标。")
        return self._complete(record, state, "已结束本次请求，未执行未确认的写入。")

    def _query_and_decide(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        if state.query is None:
            raise AgentStateError("缺少可执行的候选路线查询。")
        result = CandidateRouteService(self._session).query(state.query)
        state = state.model_copy(update={"candidate_result": result})
        state = _audit(state, AgentAction.QUERY_CANDIDATES)
        if result.matching_routes:
            allowed = [AgentAction.RECOMMEND]
            researcher = self._experience_researcher
            if (
                researcher is not None
                and researcher.enabled
                and state.interpretation is not None
                and state.interpretation.research_statusmatcher
            ):
                allowed = [AgentAction.RESEARCH_EXPERIENCE]
            return self._strategy_or_degrade(record, state, allowed, budget)
        if result.nearby_routes and not state.adjustment_attempted:
            return self._strategy_or_degrade(
                record,
                state,
                [AgentAction.PROPOSE_ADJUSTMENT],
                budget,
            )
        if state.adjustment_attempted:
            return self._offer_waiting(record, state, budget)
        if result.unknown_routes:
            return self._strategy_or_degrade(
                record,
                state,
                [AgentAction.COMPLETE],
                budget,
            )
        return self._complete(
            record,
            state,
            "当前没有符合条件的路线，也没有只改变一个条件即可成立的近似路线。你可以修改目标或取舍后再查询。",
        )

    def _strategy(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        allowed: list[AgentAction],
        budget: _TurnBudget,
        *,
        experience: list[StatusMatcherObservation] | None = None,
    ) -> AgentTurnResponse:
        decision = self._generate(
            budget,
            system_prompt=STRATEGY_SYSTEM_PROMPT,
            user_prompt=strategy_prompt(
                state,
                allowed_actions=allowed,
                experience=[item.model_dump(mode="json") for item in experience or []],
            ),
            output_model=StrategyDecision,
        )
        state = state.model_copy(update={"model_calls": state.model_calls + 1})
        if decision.action not in allowed:
            raise AgentStateError(f"模型请求了当前不允许的动作：{decision.action}")
        if decision.action == AgentAction.RESEARCH_EXPERIENCE:
            return self._research(record, state, decision, budget)
        if decision.action == AgentAction.RECOMMEND:
            return self._recommend(record, state, decision, experience or [])
        if decision.action == AgentAction.PROPOSE_ADJUSTMENT:
            return self._propose_adjustment(record, state, decision)
        if decision.action == AgentAction.OFFER_WAITING:
            state = state.model_copy(
                update={"status": AgentInteractionStatus.AWAITING_WAIT_CONFIRMATION}
            )
            state = _audit(state, AgentAction.OFFER_WAITING)
            return self._save(
                record,
                state,
                AgentTurnResponse(
                    interaction_id=record.id,
                    status=state.status,
                    action=AgentAction.OFFER_WAITING,
                    message=decision.message,
                    allowed_commands=[
                        AgentCommand.CONFIRM,
                        AgentCommand.MESSAGE,
                        AgentCommand.REJECT,
                    ],
                    interpreted_request=state.interpretation,
                    candidate_result=state.candidate_result,
                    risks=decision.risks,
                ),
            )
        return self._complete(
            record,
            state,
            decision.message,
            risks=decision.risks,
        )

    def _strategy_or_degrade(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        allowed: list[AgentAction],
        budget: _TurnBudget,
        *,
        experience: list[StatusMatcherObservation] | None = None,
    ) -> AgentTurnResponse:
        try:
            return self._strategy(
                record,
                state,
                allowed,
                budget,
                experience=experience,
            )
        except AgentProviderError:
            if not self._degrade_provider_errors:
                raise
            failed_state = state.model_copy(
                update={"model_calls": state.model_calls + 1}
            )
            return self._degraded(record, failed_state, experience or [])

    def _research(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        decision: StrategyDecision,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        researcher = self._experience_researcher
        if researcher is None or not researcher.enabled:
            raise AgentStateError("实际申请经验调查当前未获授权。")
        matching = _routes_by_id(state)
        route_ids = list(dict.fromkeys(decision.selected_research_route_ids))
        if len(route_ids) > 3 or any(route_id not in matching for route_id in route_ids):
            raise AgentStateError("经验调查只能用于最多三个正式候选。")
        observations = [researcher.research(matching[route_id]) for route_id in route_ids]
        assert state.candidate_result is not None
        focused_result = state.candidate_result.model_copy(
            update={
                "matching_routes": [matching[route_id] for route_id in route_ids],
                "nearby_routes": [],
                "unknown_routes": [],
            }
        )
        state = state.model_copy(update={"candidate_result": focused_result})
        state = _audit(state, AgentAction.RESEARCH_EXPERIENCE)
        return self._strategy_or_degrade(
            record,
            state,
            [AgentAction.RECOMMEND],
            budget,
            experience=observations,
        )

    def _recommend(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        decision: StrategyDecision,
        experience: list[StatusMatcherObservation],
    ) -> AgentTurnResponse:
        matching = _routes_by_id(state)
        if decision.primary_route_id not in matching:
            raise AgentStateError("首选路线不属于程序返回的正式候选。")
        alternative_ids = list(dict.fromkeys(decision.alternative_route_ids))
        if (
            len(alternative_ids) > 2
            or decision.primary_route_id in alternative_ids
            or any(route_id not in matching for route_id in alternative_ids)
        ):
            raise AgentStateError("备选路线必须是最多两个不同的正式候选。")
        selected_routes = [
            matching[decision.primary_route_id],
            *(matching[item] for item in alternative_ids),
        ]
        mandatory_limitations = list(
            dict.fromkeys(
                limitation
                for route in selected_routes
                for limitation in route.limitations
            )
        )
        message = decision.message
        if any("未结构化联盟精英等级等价" in item for item in mandatory_limitations):
            message += (
                "\n\n重要限制：当前数据没有结构化的联盟等级等价关系；"
                "涉及‘高等级’的选择是 Agent 基于候选等级名称作出的比较，"
                "不是官方联盟等级等价结论。"
            )
        state = state.model_copy(update={"status": AgentInteractionStatus.COMPLETED})
        state = _audit(state, AgentAction.RECOMMEND)
        response = AgentTurnResponse(
            interaction_id=record.id,
            status=state.status,
            action=AgentAction.RECOMMEND,
            message=message,
            allowed_commands=[],
            interpreted_request=state.interpretation,
            primary_route=matching[decision.primary_route_id],
            alternative_routes=[matching[item] for item in alternative_ids],
            risks=list(
                dict.fromkeys(
                    [
                        *mandatory_limitations,
                        *(
                            risk
                            for risk in decision.risks
                            if not _OUT_OF_SCOPE_RISK.search(risk)
                        ),
                    ]
                )
            )[:10],
            experience=experience,
        )
        return self._save(record, state, response)

    def _propose_adjustment(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        decision: StrategyDecision,
    ) -> AgentTurnResponse:
        proposal = decision.adjustment
        if proposal is None or state.candidate_result is None:
            raise AgentStateError("调整建议缺少候选依据。")
        nearby = {route.route_id: route for route in state.candidate_result.nearby_routes}
        route = nearby.get(proposal.route_id)
        if route is None or route.violations != [proposal.condition]:
            raise AgentStateError("调整建议必须对应近似路线唯一偏离的条件。")
        _apply_adjustment(state.query, proposal)
        state = state.model_copy(
            update={
                "status": AgentInteractionStatus.AWAITING_ADJUSTMENT_CONFIRMATION,
                "proposed_adjustment": proposal,
            }
        )
        state = _audit(state, AgentAction.PROPOSE_ADJUSTMENT)
        response = AgentTurnResponse(
            interaction_id=record.id,
            status=state.status,
            action=AgentAction.PROPOSE_ADJUSTMENT,
            message=decision.message,
            allowed_commands=[
                AgentCommand.CONFIRM,
                AgentCommand.MESSAGE,
                AgentCommand.REJECT,
            ],
            interpreted_request=state.interpretation,
            candidate_result=state.candidate_result,
            proposed_adjustment=proposal,
            risks=decision.risks,
        )
        return self._save(record, state, response)

    def _offer_waiting(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        budget: _TurnBudget,
    ) -> AgentTurnResponse:
        return self._strategy_or_degrade(
            record,
            state,
            [AgentAction.OFFER_WAITING],
            budget,
        )

    def _complete(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        message: str,
        *,
        risks: list[str] | None = None,
    ) -> AgentTurnResponse:
        state = state.model_copy(update={"status": AgentInteractionStatus.COMPLETED})
        state = _audit(state, AgentAction.COMPLETE)
        return self._save(
            record,
            state,
            AgentTurnResponse(
                interaction_id=record.id,
                status=state.status,
                action=AgentAction.COMPLETE,
                message=message,
                interpreted_request=state.interpretation,
                candidate_result=state.candidate_result,
                risks=risks or [],
            ),
        )

    def _degraded(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        experience: list[StatusMatcherObservation],
    ) -> AgentTurnResponse:
        state = state.model_copy(update={"status": AgentInteractionStatus.FAILED})
        state = _audit(state, AgentAction.COMPLETE)
        return self._save(
            record,
            state,
            AgentTurnResponse(
                interaction_id=record.id,
                status=state.status,
                action=AgentAction.COMPLETE,
                message=(
                    "路线事实已经查询完成，但模型暂时无法完成个性化取舍。"
                    "我没有替你猜选；可以稍后发起新请求。"
                ),
                interpreted_request=state.interpretation,
                candidate_result=state.candidate_result,
                risks=["本次未生成个性化首选，候选列表不代表推荐顺序。"],
                experience=experience,
            ),
        )

    def _resolve_holdings(
        self, interpretation: StrategyInterpretation
    ) -> tuple[list[ResolvedHolding], list[str]]:
        nodes = UnifiedMembershipTreeService(self._session).catalog().nodes
        resolved: list[ResolvedHolding] = []
        unresolved: list[str] = []
        for mention in interpretation.holdings:
            program_key = normalize_key(mention.program)
            tier_key = normalize_tier(mention.tier)
            candidates = [
                node
                for node in nodes
                if (
                    program_key in {node.program_key, normalize_key(node.program)}
                    and tier_key in {node.tier_key, normalize_tier(node.tier)}
                )
            ]
            if len(candidates) != 1:
                unresolved.append(
                    f"请确认“{mention.program} {mention.tier}”对应目录中的哪个具体项目和等级。"
                )
                continue
            node = candidates[0]
            resolved.append(
                ResolvedHolding(
                    program_key=node.program_key,
                    tier_key=node.tier_key,
                    program_display_name=node.program,
                    tier_display_name=node.tier,
                    valid_until=mention.valid_until,
                )
            )
        return resolved, unresolved

    def _resolve_query(
        self, interpretation: StrategyInterpretation
    ) -> tuple[CandidateRouteQuery | None, str | None]:
        target = interpretation.target
        program_key: str | None = None
        tier_key: str | None = None
        if target.program is not None:
            normalized_program = normalize_key(target.program)
            nodes = UnifiedMembershipTreeService(self._session).catalog().nodes
            programs = {
                node.program_key
                for node in nodes
                if normalized_program in {node.program_key, normalize_key(node.program)}
            }
            if len(programs) != 1:
                return None, f"请确认目标“{target.program}”对应目录中的哪个项目。"
            program_key = next(iter(programs))
            if target.tier is not None:
                normalized_tier = normalize_tier(target.tier)
                tiers = {
                    node.tier_key
                    for node in nodes
                    if node.program_key == program_key
                    and normalized_tier in {node.tier_key, normalize_tier(node.tier)}
                }
                if len(tiers) != 1:
                    return None, f"请确认目标项目的具体等级“{target.tier}”。"
                tier_key = next(iter(tiers))
        query = CandidateRouteQuery(
            target=CandidateTarget(
                program_key=program_key,
                tier_key=tier_key,
                alliance=target.alliance,
                relative_tier=CandidateRelativeTier(target.relative_level),
            ),
            constraints=interpretation.constraints,
        )
        return query, None

    def _load(
        self, interaction_id: UUID
    ) -> tuple[AgentInteraction, AgentInteractionState]:
        record = self._session.get(AgentInteraction, interaction_id)
        if record is None:
            raise AgentStateError("Agent 交互不存在。")
        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise AgentStateError("Agent 交互已过期，请开始一个新请求。")
        return record, AgentInteractionState.model_validate(record.state)

    def _generate(self, budget: _TurnBudget, **kwargs):
        budget.take()
        try:
            return self._provider.generate_structured(**kwargs)
        except Exception as exc:
            raise AgentProviderError(
                f"Agent 模型暂时无法返回有效的结构化结果：{type(exc).__name__}"
            ) from exc

    def _save(
        self,
        record: AgentInteraction,
        state: AgentInteractionState,
        response: AgentTurnResponse,
    ) -> AgentTurnResponse:
        record.status = state.status
        record.state = state.model_dump(mode="json")
        record.last_response = response.model_dump(mode="json")
        self._session.flush()
        return response


def cleanup_expired_interactions(
    session: Session,
    *,
    now: datetime | None = None,
) -> int:
    result = session.execute(
        delete(AgentInteraction).where(
            AgentInteraction.expires_at <= (now or datetime.now(UTC))
        )
    )
    return int(result.rowcount or 0)


def _routes_by_id(state: AgentInteractionState) -> dict[str, CandidateRoute]:
    if state.candidate_result is None:
        return {}
    return {route.route_id: route for route in state.candidate_result.matching_routes}


def _audit(state: AgentInteractionState, action: AgentAction) -> AgentInteractionState:
    return state.model_copy(update={"action_audit": [*state.action_audit, action]})


def _apply_adjustment(
    query: CandidateRouteQuery | None,
    proposal: AdjustmentProposal,
) -> CandidateRouteQuery:
    if query is None:
        raise AgentStateError("缺少原始查询，无法应用调整。")
    constraints = query.constraints
    if proposal.condition == "cost_policy":
        if proposal.new_value not in {CandidateCostPolicy.ANY, "ALLOW_FEE"}:
            raise AgentStateError("费用条件当前只允许放宽为 ANY/ALLOW_FEE。")
        updated = constraints.model_copy(
            update={
                "cost_policy": CandidateCostPolicy.ANY,
                "max_amount": None,
                "max_currency": None,
            }
        )
    elif proposal.condition == "challenge_policy":
        if proposal.new_value not in {
            CandidateChallengePolicy.ALLOW,
            "ALLOW_CHALLENGE",
        }:
            raise AgentStateError(
                "挑战条件当前只允许放宽为 ALLOW/ALLOW_CHALLENGE。"
            )
        updated = constraints.model_copy(
            update={"challenge_policy": CandidateChallengePolicy.ALLOW}
        )
    else:
        try:
            amount = Decimal(proposal.new_value)
        except InvalidOperation as exc:
            raise AgentStateError("最高费用调整必须是数字。") from exc
        if constraints.max_currency is None or amount < 0:
            raise AgentStateError("最高费用调整缺少有效币种或金额。")
        updated = constraints.model_copy(update={"max_amount": amount})
    return query.model_copy(update={"constraints": updated})
