from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "gold" / "status_opportunity_phase1_v1.json"
OUTPUT_PATH = ROOT / "gold" / "status_opportunity_phase1_v1_bodies_zh.md"
CACHE_PATH = ROOT / "gold" / "status_opportunity_phase1_v1_zh_cache.json"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
TRANSLATOR_VERSION = "zh-review-v2"

_URL = re.compile(r"https?://[^\s<>]+")
_MARKDOWN_DESTINATION = re.compile(r"\((https?://[^)\n]+)\)")
_CJK = re.compile(r"[\u3400-\u9fff]")
_STRUCTURAL_PREFIX = re.compile(
    r"^(\s*(?:(?:#{1,6}|>|[*+-]|\d+\.)\s+))(.*)$"
)
_TABLE_SEPARATOR = re.compile(r"^\s*:?-{3,}:?\s*$")
_MARKER = "ZXQSEG{index:06d}QXZ"
_AUDIT_URL = re.compile(r"https?://[^\s<>)\"'|]+")

_FFB_COMPANY_NAMES_ZH = {
    "Apple": "苹果",
    "Amazon": "亚马逊",
    "Google": "谷歌",
    "Microsoft": "微软",
    "Meta": "Meta（脸书母公司）",
    "Boeing": "波音",
    "T-Mobile": "T-Mobile",
    "Genentech or Roche": "基因泰克或罗氏",
    "Salesforce": "Salesforce",
    "Deloitte": "德勤",
    "Accenture": "埃森哲",
    "McKinsey": "麦肯锡",
    "KPMG": "毕马威",
    "Nike": "耐克",
    "Zillow": "Zillow",
    "Stripe": "Stripe",
    "Stryker": "史赛克",
    "Comcast": "康卡斯特",
    "Leidos": "雷多斯",
    "Slalom": "Slalom",
    "F5": "F5",
    "REI": "REI",
    "MultiCare": "MultiCare",
    "Micron Technology Inc.": "美光科技",
    "Albertsons": "艾伯森",
    "WinCo": "WinCo",
    "Gilead Sciences": "吉利德科学",
    "Wells Fargo": "富国银行",
    "PWC": "普华永道",
    "University of Washington": "华盛顿大学",
    "HP Inc.": "惠普",
    "EY": "安永",
}

_MANUAL_TRANSLATIONS = {
    (
        "> Elite members who fail to meet the requalification conditions will be "
        "downgraded, but not more than one level down at a time."
    ): "> 未达到重新保级条件的精英会员将被降级，但每次最多只降一级。",
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mostly_chinese(value: str) -> bool:
    letters = sum(character.isalpha() for character in value)
    if not letters:
        return True
    return len(_CJK.findall(value)) / letters >= 0.35


def _protect_urls(value: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace_markdown_destination(match: re.Match[str]) -> str:
        token = f"ZXQMDL{len(replacements):06d}QXZ"
        replacements[token] = match.group(1)
        return f"({token})"

    value = _MARKDOWN_DESTINATION.sub(replace_markdown_destination, value)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,;:!?)]:*":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        token = f"ZXQURL{len(replacements):06d}QXZ"
        replacements[token] = raw
        return token + trailing

    return _URL.sub(replace, value), replacements


def _restore_urls(value: str, replacements: dict[str, str]) -> str:
    for token, url in replacements.items():
        value = value.replace(token, url)
    return value


def _split_long(value: str, limit: int = 2800) -> list[str]:
    if len(value) <= limit:
        return [value]
    pieces: list[str] = []
    remaining = value
    while len(remaining) > limit:
        split_at = max(
            remaining.rfind(mark, 0, limit)
            for mark in ("。", ". ", "; ", ", ", " ")
        )
        if split_at < limit // 2:
            split_at = limit
        else:
            split_at += 1
        pieces.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        pieces.append(remaining)
    return pieces


def _translation_plan(markdown: str) -> tuple[list[str], list[str], dict[str, str]]:
    protected, urls = _protect_urls(markdown)
    segments: list[str] = []
    templates: list[str] = []

    def slot(value: str) -> str:
        if not value.strip() or _mostly_chinese(value):
            return value
        placeholders: list[str] = []
        for piece in _split_long(value):
            index = len(segments)
            segments.append(piece)
            placeholders.append(f"{{{{T{index:06d}}}}}")
        return "".join(placeholders)

    for line in protected.splitlines():
        if not line.strip():
            templates.append("")
            continue
        if line.lstrip().startswith("|") and line.rstrip().endswith("|"):
            cells = line.split("|")
            translated_cells = [
                cell if _TABLE_SEPARATOR.fullmatch(cell) else slot(cell)
                for cell in cells
            ]
            templates.append("|".join(translated_cells))
            continue
        match = _STRUCTURAL_PREFIX.match(line)
        if match:
            templates.append(match.group(1) + slot(match.group(2)))
        else:
            templates.append(slot(line))
    return templates, segments, urls


def _translate_batch(client: httpx.Client, segments: list[str]) -> list[str]:
    joined = ""
    for index, segment in enumerate(segments):
        if index:
            joined += f"\n{_MARKER.format(index=index)}\n"
        joined += segment
    response = client.get(
        TRANSLATE_URL,
        params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": joined},
    )
    response.raise_for_status()
    payload = response.json()
    translated = "".join(part[0] for part in payload[0] if part and part[0])
    pieces = [translated]
    for index in range(1, len(segments)):
        marker = _MARKER.format(index=index)
        next_pieces: list[str] = []
        for piece in pieces:
            if marker in piece:
                before, after = piece.split(marker, 1)
                next_pieces.extend((before, after))
            else:
                next_pieces.append(piece)
        pieces = next_pieces
    pieces = [piece.strip(" \n") for piece in pieces]
    if len(pieces) != len(segments):
        raise RuntimeError(
            f"Translation marker mismatch: expected {len(segments)}, got {len(pieces)}"
        )
    return pieces


def _translate_segments(
    client: httpx.Client, segments: list[str], *, batch_limit: int = 3500
) -> list[str]:
    translated: list[str] = []
    cursor = 0
    while cursor < len(segments):
        end = cursor
        size = 0
        while end < len(segments):
            addition = len(segments[end]) + 24
            if end > cursor and size + addition > batch_limit:
                break
            size += addition
            end += 1
        batch = segments[cursor:end]
        for attempt in range(5):
            try:
                translated.extend(_translate_batch(client, batch))
                break
            except (httpx.HTTPError, ValueError, RuntimeError):
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 8))
        cursor = end
        time.sleep(0.12)
    return translated


def translate_markdown(client: httpx.Client, markdown: str) -> str:
    templates, segments, urls = _translation_plan(markdown)
    translated = _translate_segments(client, segments) if segments else []
    result = "\n".join(templates)
    for index, value in enumerate(translated):
        result = result.replace(f"{{{{T{index:06d}}}}}", value)
    return _restore_urls(result, urls)


def _repair_markdown_destinations(original: str, translated: str) -> str:
    original_destinations = [
        match.group(1) for match in _MARKDOWN_DESTINATION.finditer(original)
    ]
    translated_matches = list(_MARKDOWN_DESTINATION.finditer(translated))
    if len(original_destinations) != len(translated_matches):
        return translated
    for destination, match in reversed(
        list(zip(original_destinations, translated_matches, strict=True))
    ):
        start, end = match.span(1)
        translated = translated[:start] + destination + translated[end:]
    return translated


def _repair_ffb_company_names(original: str, translated: str) -> str:
    original_names = re.findall(r"(?m)^\* \*\*([^*]+)\*\*\s*[–-]", original)
    translated_matches = list(
        re.finditer(r"(?m)^\* \*\*([^*]+)\*\*\s*[–-]", translated)
    )
    if len(original_names) != len(translated_matches):
        return translated
    for original_name, match in reversed(
        list(zip(original_names, translated_matches, strict=True))
    ):
        replacement = _FFB_COMPANY_NAMES_ZH.get(original_name.strip(), original_name)
        start, end = match.span(1)
        translated = translated[:start] + replacement + translated[end:]
    return translated


def _append_missing_urls(original: str, translated: str) -> str:
    missing = Counter(_AUDIT_URL.findall(original)) - Counter(
        _AUDIT_URL.findall(translated)
    )
    if not missing:
        return translated
    lines = ["", "> 机器翻译未能嵌回正文位置的原文链接："]
    for url, count in missing.items():
        for _ in range(count):
            lines.append(f"> - [打开原文相关链接]({url})")
    return translated.rstrip() + "\n" + "\n".join(lines)


def _apply_manual_translations(translated: str) -> str:
    for original, replacement in _MANUAL_TRANSLATIONS.items():
        translated = translated.replace(original, replacement)
    return translated


def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    value = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid translation cache: {CACHE_PATH}")
    return {str(key): str(body) for key, body in value.items()}


def _classification_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["document_key"]): item
        for case in data["cases"]
        for item in case["classifications"]
    }


def _display_label(value: str) -> str:
    return {
        "STATUS_OPPORTUNITY": "是：属于会籍机会",
        "NONE": "否：不属于会籍机会",
        "UNCERTAIN": "不确定：需要人工裁决",
    }[value]


def build() -> dict[str, Any]:
    data = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    classifications = _classification_map(data)
    cache = _load_cache()
    active_cache: dict[str, str] = {}
    article_documents = data["cases"][0]["documents"]
    catalog_documents = data["cases"][1]["documents"]
    headers = {"User-Agent": "JourneyPlus/1.0 Chinese-review-translation"}

    with httpx.Client(timeout=45, headers=headers) as client:
        for document in article_documents + catalog_documents:
            body = str(document["normalized_body"])
            key = _digest(f"{TRANSLATOR_VERSION}\0{body}")
            if key in cache:
                translated_body = cache[key]
            elif _digest(body) in cache:
                translated_body = cache[_digest(body)]
            elif str(document["document_key"]).startswith("verylvke_feed:"):
                translated_body = body
            else:
                translated_body = translate_markdown(client, body)
            translated_body = _repair_markdown_destinations(body, translated_body)
            if str(document["document_key"]).endswith(
                "alaska-atmos-corporate-status-challenge-2026"
            ):
                translated_body = _repair_ffb_company_names(body, translated_body)
            translated_body = _append_missing_urls(body, translated_body)
            translated_body = _apply_manual_translations(translated_body)
            active_cache[key] = translated_body

    lines = [
        "# 第一阶段金标中文正文审核稿",
        "",
        "说明：这是供人工审核使用的机器翻译阅读版，不是新的证据正文，也不会写回金标JSON。忠诚度项目名称、会籍等级和网址可能保留原文；事实裁决仍以原始正文及来源链接为准。",
        "",
        "审核方法：检查中文正文是否完整覆盖活动主体、资格、费用、期限和申请方式；如翻译有歧义，请按A/F编号指出。",
        "",
        "## 30篇指定文章",
        "",
    ]
    for index, document in enumerate(article_documents, 1):
        document_key = str(document["document_key"])
        classification = classifications[document_key]
        body = active_cache[
            _digest(f"{TRANSLATOR_VERSION}\0{document['normalized_body']}")
        ]
        title = body.splitlines()[0].lstrip("# ").strip() or f"文章{index}"
        lines.extend(
            (
                f"### A{index:02d} {title}",
                "",
                f"- 判定：{_display_label(str(classification['label']))}",
                f"- 活动数量：{len(classification['event_keys'])}",
                f"- [打开原始来源]({document['source_url']})",
                "",
                body,
                "",
                "---",
                "",
            )
        )
    lines.extend(("## FFB列表35个顶层条目", ""))
    for index, document in enumerate(catalog_documents, 1):
        document_key = str(document["document_key"])
        classification = classifications[document_key]
        body = active_cache[
            _digest(f"{TRANSLATOR_VERSION}\0{document['normalized_body']}")
        ]
        title = body.splitlines()[0].strip() or f"FFB条目{index}"
        lines.extend(
            (
                f"### F{index:02d} {title}",
                "",
                f"- 判定：{_display_label(str(classification['label']))}",
                f"- 活动数量：{len(classification['event_keys'])}",
                f"- [打开FFB列表来源]({document['source_url']})",
                "",
                body,
                "",
                "---",
                "",
            )
        )

    CACHE_PATH.write_text(
        json.dumps(active_cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return {
        "output_path": str(OUTPUT_PATH),
        "cache_path": str(CACHE_PATH),
        "documents": len(article_documents) + len(catalog_documents),
        "translated_documents": len(active_cache),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成第一阶段金标中文正文审核稿")
    parser.parse_args()
    print(json.dumps(build(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
