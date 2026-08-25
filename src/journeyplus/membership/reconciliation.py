from __future__ import annotations

import re

from journeyplus.contracts import StatusMapping
from journeyplus.membership.contracts import MappingClaimStatus


_SPACE_RE = re.compile(r"\s+")


def compare_with_official_mappings(
    candidate: StatusMapping,
    official_mappings: list[StatusMapping],
) -> tuple[MappingClaimStatus, str]:
    for official in official_mappings:
        if _mapping_key(candidate) == _mapping_key(official):
            return (
                MappingClaimStatus.CORROBORATED,
                "候选关系与当前官方 FactSet 中的会籍对应关系一致。",
            )
    for official in official_mappings:
        if _same_scope(candidate, official):
            return (
                MappingClaimStatus.CONFLICTING,
                "候选关系与当前官方 FactSet 的同作用域关系在目标等级、可用性或条件上不一致。",
            )
    return (
        MappingClaimStatus.CANDIDATE,
        "当前官方 FactSet 中没有等价或同作用域关系，保留为第三方候选。",
    )


def _mapping_key(mapping: StatusMapping) -> tuple:
    return (
        _normalize(mapping.source_program),
        tuple(sorted(_normalize(tier) for tier in mapping.source_tiers)),
        _normalize(mapping.target_tier),
        str(mapping.availability),
        _normalize(mapping.conditions or ""),
    )


def _same_scope(left: StatusMapping, right: StatusMapping) -> bool:
    if _normalize(left.source_program) != _normalize(right.source_program):
        return False
    left_tiers = {_normalize(item) for item in left.source_tiers}
    right_tiers = {_normalize(item) for item in right.source_tiers}
    return not left_tiers or not right_tiers or bool(left_tiers & right_tiers)


def _normalize(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip().casefold()
