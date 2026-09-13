"""Derived brief display data, never a second stored knowledge model."""
from dataclasses import dataclass
from datetime import datetime
import re

from journeyplus.contracts import FactSet
from journeyplus.lifecycle.service import BEIJING_TZ
from journeyplus.membership.unified import UnifiedMembershipTreeService
from journeyplus.opportunity_shaping import parse_route_prices
from journeyplus.product.contracts import BriefFee, BriefRelationship
from journeyplus.product.holdings import StatusHoldingService


_FREE = re.compile(r"^(?:(?:基础)?申请(?:费)?(?:为|是)?\s*)?(?:免费|无费用|无需付费|free(?: of charge)?)(?:$|[，。；,. ;])", re.I)
_PAID = re.compile(r"^(?:申请费(?:为|是)?\s*)?(?:收费|付费|paid|fees? apply)(?:$|[，。；,. ;])", re.I)
_OPTIONAL = re.compile(r"可选|额外|另付|升级|optional|additional|upgrade", re.I)


def fee_view(facts: FactSet) -> BriefFee:
    states = []
    conditional = False
    notes = [facts.cost.value] if facts.cost.value else []
    routes = facts.application_routes or [None]
    for route in routes:
        text = (route.cost if route else None) or facts.cost.value or ""
        if route and route.cost:
            notes.append(f"{route.scope}：{route.cost}")
        prices = route.prices if route else []
        optional_text = bool(_OPTIONAL.search(text))
        if not prices and not optional_text:
            prices = parse_route_prices(text, evidence=[]) if text else []
        conditional |= any(p.availability == "CONDITIONAL" and p.amount is not None and p.amount > 0 for p in prices)
        conditional |= optional_text and bool(parse_route_prices(text, evidence=[]))
        if facts.cost.conflict or (route and route.conflict):
            states.append("UNKNOWN")
            notes.append((route.conflict_note if route else None) or "费用信息存在冲突")
            continue
        base = [p for p in prices if p.availability not in {"CONDITIONAL", "UNAVAILABLE"}]
        if base:
            states.extend(
                "UNKNOWN" if p.amount is None or p.availability == "UNKNOWN"
                else "FREE" if p.amount == 0 else "PAID" for p in base
            )
        elif _FREE.search(text.strip()):
            states.append("FREE")
        elif _PAID.search(text.strip()):
            states.append("PAID")
        elif prices and all(p.availability == "UNAVAILABLE" for p in prices):
            continue
        else:
            states.append("UNKNOWN")
    known = set(states) - {"UNKNOWN"}
    incomplete = "UNKNOWN" in states or not states
    if known == {"FREE", "PAID"}:
        status, label = "MIXED", "部分免费／部分付费"
    elif known == {"PAID"}:
        status, label = "PAID", "付费" if not incomplete else "已知方案付费，部分费用待确认"
    elif known == {"FREE"} and not incomplete:
        status, label = "FREE", "免费"
    else:
        status, label = "UNKNOWN", "部分免费，其他费用待确认" if "FREE" in known else "费用待确认"
    if conditional:
        label = "基础申请免费，可选项目付费" if status == "FREE" else label + "；存在条件付费项目"
    return BriefFee(status=status, label=label, has_conditional_fees=conditional,
                    incomplete=incomplete, notes=list(dict.fromkeys(notes)))


def action_links(facts: FactSet) -> list[str]:
    return list(dict.fromkeys(str(link) for link in [
        facts.action_link.value, *(route.action_link for route in facts.application_routes),
    ] if link))


@dataclass
class RelationContext:
    paths: dict
    labels: dict[str, str]
    has_holdings: bool
    has_active_holdings: bool
    truncated: bool

    def for_opportunity(self, opportunity_id) -> BriefRelationship:
        path = self.paths.get(opportunity_id)
        labels = [self.labels.get(node, node.replace("::", " · ")) for node in path or []]
        if not self.has_holdings:
            status, text = "NO_HOLDINGS", "尚未保存会籍，暂时无法计算与你的关系。"
        elif not self.has_active_holdings:
            status, text = "NO_ACTIVE_HOLDINGS", "已保存的会籍均已过期，暂无可用于匹配的会籍。"
        elif path:
            direct = len(path) == 2
            status = "DIRECT" if direct else "INDIRECT"
            text = ("你的会籍存在直接匹配路径：" if direct else "你的会籍可通过中间项目关联：") + " → ".join(labels)
            text += "。仍需满足对应方案的地区和其他申请条件。"
        else:
            status = "INCOMPLETE" if self.truncated else "NO_PATH"
            text = "本次查询未找到路径，检索结果尚不完整。" if self.truncated else "尚未找到与你当前会籍对应的匹配路径，不代表确定无法申请。"
        return BriefRelationship(status=status, text=text, path=path, path_labels=labels)


def relation_context(session) -> RelationContext:
    from journeyplus.product.opportunities import _opportunity_paths
    now = datetime.now(BEIJING_TZ)
    holdings = StatusHoldingService(session).list()
    active = [h for h in holdings if h.valid_until is None or h.valid_until >= now.date()]
    if not active:
        return RelationContext({}, {}, bool(holdings), False, False)
    forest = UnifiedMembershipTreeService(session).reachable_forest([h.node_id for h in active], now=now)
    labels = {}

    def visit(node):
        labels[node.node.id] = f"{node.node.program} · {node.node.tier}"
        for edge in node.children:
            visit(edge.child)

    for root in forest.roots:
        visit(root)
    return RelationContext(_opportunity_paths(forest.roots), labels, True, True, bool(forest.truncated_count))
