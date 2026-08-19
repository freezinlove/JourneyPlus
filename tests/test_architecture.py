from __future__ import annotations

import ast
from pathlib import Path


BUSINESS_MODULES = {
    "status_topic",
    "clustering",
    "facts",
    "briefs",
    "review",
    "evaluation",
}


def imported_journeyplus_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name.startswith("journeyplus."):
                parts = name.split(".")
                if len(parts) > 1:
                    imported.add(parts[1])
    return imported


def test_sources_and_content_do_not_depend_on_business_modules() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus"
    for module in ("sources", "content"):
        for path in (root / module).glob("*.py"):
            assert not (imported_journeyplus_modules(path) & BUSINESS_MODULES), path


def test_ai_provider_does_not_import_business_modules() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus" / "ai"
    for path in root.glob("*.py"):
        assert not (imported_journeyplus_modules(path) & BUSINESS_MODULES), path

