"""Shared read-time fee policy; never changes stored extraction facts."""
from dataclasses import dataclass
import re

from journeyplus.contracts import RoutePrice
from journeyplus.membership.normalization import program_tier_key
from journeyplus.opportunity_shaping import parse_route_prices

FREE = re.compile(r"^(?:(?:基础)?申请(?:费)?(?:为|是)?\s*)?(?:免费|无费用|无需付费|free(?: of charge)?)(?:$|[，。；,. ;])", re.I)
PAID = re.compile(r"^(?:申请费(?:为|是)?\s*)?(?:收费|付费|paid|fees? apply)(?:$|[，。；,. ;])", re.I)
OPTIONAL = re.compile(r"可选|额外|另付|升级|optional|additional|upgrade", re.I)


@dataclass
class RouteFees:
    text: str
    prices: list[tuple[int, RoutePrice]]
    states: list[str]
    conditional: bool
    conflict: bool
    free_basis: str | None = None

    @property
    def free(self):
        return bool(self.states) and set(self.states) == {'FREE'}


def route_fees(facts, route=None, *, target_tier=None, program_aliases=()):
    text = ((route.cost if route else None) or facts.cost.value or '').strip()
    prices = list(route.prices) if route else []
    if not prices and text:
        parsed = parse_route_prices(text, evidence=[])
        # Optional prose amounts are supplementary, never a mandatory base fee.
        prices = [p.model_copy(update={'availability':'CONDITIONAL'})
                  if OPTIONAL.search(p.raw_text) else p for p in parsed]
    selected = [(i,p) for i,p in enumerate(prices) if target_tier is None or not p.target_tier
                or program_tier_key(p.target_tier, program_aliases) == program_tier_key(target_tier, program_aliases)]
    conditional = any(p.availability == 'CONDITIONAL' and p.amount is not None and p.amount > 0 for _,p in selected)
    conflict = bool(facts.cost.conflict or route and route.conflict)
    base = [p for _,p in selected if p.availability not in {'CONDITIONAL','UNAVAILABLE'}]
    free_basis = None
    if conflict:
        states = ['UNKNOWN']
    elif base:
        states = ['UNKNOWN' if p.amount is None or p.availability == 'UNKNOWN'
                  else 'FREE' if p.amount == 0 else 'PAID' for p in base]
    elif selected and all(p.availability == 'UNAVAILABLE' for _,p in selected):
        states = []
    elif FREE.search(text):
        states, free_basis = ['FREE'], 'EXPLICIT_FREE'
    elif PAID.search(text):
        states = ['PAID']
    elif not text and not selected:
        # Missing information is not evidence of a free application.
        states = ['UNKNOWN']
    elif OPTIONAL.match(text) and conditional:
        states = ['UNKNOWN']
    else:
        states = ['UNKNOWN']
    return RouteFees(text, selected, states, conditional, conflict, free_basis)
