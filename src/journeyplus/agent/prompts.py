from __future__ import annotations

import json

from journeyplus.agent.contracts import AgentAction, AgentInteractionState
from journeyplus.product.contracts import StatusHoldingView


PROMPT_VERSION = "membership-strategy-agent-v1"


INTERPRET_SYSTEM_PROMPT = """你是 JourneyPlus 的单一会籍策略 Agent。
你的任务是理解用户当前持有会籍、目标和费用/挑战取舍，并选择当前下一步。
你不是事实库：不得判断路线是否可达，不得编造项目、价格、联盟等级等价或审批结果。
持有会籍和目标尽量使用目录中的规范名称。只有会改变会籍规范化、持久化或路线查询的关键歧义才 ASK_CLARIFICATION；每次最多一个问题。
用户说“高卡”时把 relative_level 设为 HIGH，不要自行声称某等级等同联盟高级会籍。
用户说“白嫖/免费”时使用 FREE_ONLY；只有明确金额上限才使用 MAX_AMOUNT。用户明确不要挑战时使用 NO_CHALLENGE。
如果用户要求查询真实申请案例，把 research_statusmatcher 设为 true；这不代表工具一定获授权。
动作含义：ASK_CLARIFICATION=需要一个关键答案；CONFIRM_HOLDINGS=出现需要落库的新会籍；QUERY_CANDIDATES=信息足够且无需确认新会籍。
只输出结构化决定，不输出额外文本。"""


STRATEGY_SYSTEM_PROMPT = """你是 JourneyPlus 的单一会籍策略 Agent。
程序已经提供确定性的候选路线观察。你负责按用户取舍选择下一动作和解释，不得修改候选事实。
matching_routes 才是当前可行路线；nearby_routes 只偏离一个硬条件；unknown_routes 缺少关键证明，不能包装成可行。
只能从 allowed_actions 中选择动作。只有 unknown_routes 时应选择 COMPLETE，明确指出缺少哪些事实以及为何不能安全推荐。
有多个 matching_routes 时，选择一个 primary 和最多两个真正有差异的 alternatives；不要把程序顺序称为排名。
StatusMatcher 只能用于程序已给出的正式候选，属于自报经验而非真实审批概率。
没有 matching_routes 时只可从 nearby_routes 提出一个调整，且 condition 必须等于该路线唯一 violation。
调整 cost_policy 时 new_value 只能是 ANY 或语义等价的 ALLOW_FEE；调整 challenge_policy 时只能是 ALLOW 或 ALLOW_CHALLENGE；调整 max_amount 时必须返回可由现有币种解释的非负数字字符串。
只有 allowed_actions 明确包含 OFFER_WAITING 时，才主动询问用户是否按当前条件持续跟进；不得自行保存等待目标。
风险说明必须引用候选中的费用、挑战、期限、冲突、证据或 limitation，不得编造权益、汇率或联盟等级等价。
不得讨论休息室、行李、早餐、升房、退款、申诉或客服处理；这些不在当前数据库和 Agent 范围内。
所有列表字段在没有内容时必须返回空数组 []，不得返回 null。
只输出结构化决定，不输出额外文本。"""


def interpretation_prompt(
    message: str,
    *,
    holdings: list[StatusHoldingView],
    catalog_lines: list[str],
    previous: AgentInteractionState | None = None,
) -> str:
    payload = {
        "user_message": message,
        "confirmed_holdings": [item.model_dump(mode="json") for item in holdings],
        "membership_catalog": catalog_lines,
        "previous_interaction": (
            previous.model_dump(mode="json", exclude_none=True) if previous else None
        ),
        "allowed_actions": [
            AgentAction.ASK_CLARIFICATION,
            AgentAction.CONFIRM_HOLDINGS,
            AgentAction.QUERY_CANDIDATES,
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def strategy_prompt(
    state: AgentInteractionState,
    *,
    allowed_actions: list[AgentAction],
    experience: list[dict] | None = None,
    note: str | None = None,
) -> str:
    payload = {
        "interpreted_request": (
            state.interpretation.model_dump(mode="json")
            if state.interpretation
            else None
        ),
        "candidate_observation": (
            state.candidate_result.model_dump(mode="json")
            if state.candidate_result
            else None
        ),
        "experience_observation": experience or [],
        "adjustment_attempted": state.adjustment_attempted,
        "allowed_actions": allowed_actions,
        "controller_note": note,
    }
    return json.dumps(payload, ensure_ascii=False)
