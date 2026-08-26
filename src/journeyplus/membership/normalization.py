from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from collections.abc import Callable, Iterable
from typing import TypeVar


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w+]+", re.UNICODE)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AliasResolution:
    label: str
    normalized: str
    candidates: tuple[str, ...]


def distinctive_alias(tokens: list[str]) -> bool:
    return len(tokens) >= 2 or (len(tokens) == 1 and len(tokens[0]) >= 6)


def display_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value).strip()


def display_tier(value: str) -> str:
    displayed = display_text(value)
    tokens = displayed.split()
    if len(tokens) > 1 and tokens[-1].casefold() == "status":
        displayed = " ".join(tokens[:-1])
    return displayed or "UNCERTAIN"


def normalize_key(value: str) -> str:
    return _SPACE_RE.sub(" ", _NON_WORD_RE.sub(" ", value).casefold()).strip()


def normalize_tier(value: str) -> str:
    normalized = normalize_key(value)
    tokens = normalized.split()
    if len(tokens) > 1 and tokens[-1] == "status":
        normalized = " ".join(tokens[:-1])
    return normalized or "uncertain"


def stable_id(prefix: str, *values: str) -> str:
    digest = sha256("\x1f".join(values).encode()).hexdigest()[:24]
    return f"{prefix}:{digest}"


def certainty_rank(value: object) -> int:
    return {"EXACT": 0, "WILDCARD": 1, "UNCERTAIN": 2}[str(value)]


def resolve_alias(
    raw_program: str,
    alias_index: dict[str, set[str]],
) -> AliasResolution:
    """Resolve exact or distinctive suffix aliases without guessing ambiguity."""

    label = display_text(raw_program)
    normalized = normalize_key(label)
    candidates = set(alias_index.get(normalized, set()))
    if not candidates:
        best_score: tuple[int, int] | None = None
        raw_tokens = normalized.split()
        for alias, keys in alias_index.items():
            alias_tokens = alias.split()
            if (
                not distinctive_alias(alias_tokens)
                or len(alias_tokens) > len(raw_tokens)
                or raw_tokens[-len(alias_tokens) :] != alias_tokens
            ):
                continue
            score = (len(alias_tokens), len(alias))
            if best_score is None or score > best_score:
                best_score = score
                candidates = set(keys)
            elif score == best_score:
                candidates.update(keys)
    return AliasResolution(
        label=label,
        normalized=normalized,
        candidates=tuple(sorted(candidates)),
    )


def group_by_source(
    values: Iterable[T],
    source_key: Callable[[T], str],
) -> dict[str, list[T]]:
    """Build the source-node adjacency index shared by graph projections."""

    grouped: dict[str, list[T]] = defaultdict(list)
    for value in values:
        grouped[source_key(value)].append(value)
    return dict(grouped)
