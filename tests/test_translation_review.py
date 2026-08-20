from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_phase1_gold_zh_review.py"
SPEC = importlib.util.spec_from_file_location("build_phase1_gold_zh_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_protect_urls = MODULE._protect_urls
_restore_urls = MODULE._restore_urls
_translation_plan = MODULE._translation_plan
_repair_markdown_destinations = MODULE._repair_markdown_destinations
_repair_ffb_company_names = MODULE._repair_ffb_company_names
_append_missing_urls = MODULE._append_missing_urls
_apply_manual_translations = MODULE._apply_manual_translations


def test_translation_review_protects_markdown_destinations_and_bare_urls() -> None:
    source = (
        '[value](https://example.com/path?a=1 "English title") '
        "and <https://example.net/apply>."
    )
    protected, replacements = _protect_urls(source)

    assert "https://" not in protected
    assert _restore_urls(protected, replacements) == source


def test_translation_plan_preserves_markdown_table_structure() -> None:
    markdown = """## Offer

| Program | Apply |
| --- | --- |
| Example Air | [Register](https://example.com/apply) |
"""
    templates, segments, urls = _translation_plan(markdown)

    assert templates[0].startswith("## {{T")
    assert templates[2].count("|") == 3
    assert templates[3] == "| --- | --- |"
    assert "https://" not in "\n".join(templates)
    assert any("Offer" in segment for segment in segments)
    assert any("https://example.com/apply" == value for value in urls.values())


def test_translation_review_restores_original_markdown_destination() -> None:
    original = '[Value](https://example.com/path "English title")'
    translated = '[价值](https://example.com/path“中文标题”)'

    assert _repair_markdown_destinations(original, translated) == (
        '[价值](https://example.com/path "English title")'
    )


def test_translation_review_repairs_ffb_company_names() -> None:
    original = (
        "* **Meta** – [Register](https://example.com/meta)\n"
        "* **Stripe** - [Register](https://example.com/stripe)"
    )
    translated = (
        "* **元** – [注册](https://example.com/meta)\n"
        "* **条纹** - [注册](https://example.com/stripe)"
    )

    repaired = _repair_ffb_company_names(original, translated)
    assert "**Meta（脸书母公司）**" in repaired
    assert "**Stripe**" in repaired


def test_translation_review_appends_link_dropped_by_machine_translation() -> None:
    original = "Read [details](https://example.com/details)."
    translated = "阅读详情。"

    repaired = _append_missing_urls(original, translated)
    assert "[打开原文相关链接](https://example.com/details)" in repaired


def test_translation_review_translates_english_quote_inside_chinese_source() -> None:
    original = (
        "> Elite members who fail to meet the requalification conditions will be "
        "downgraded, but not more than one level down at a time."
    )

    assert _apply_manual_translations(original).startswith("> 未达到重新保级条件")
