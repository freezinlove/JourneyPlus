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


def test_candidate_retrieval_has_no_vector_database_dependency() -> None:
    path = (
        Path(__file__).parents[1]
        / "src"
        / "journeyplus"
        / "clustering"
        / "retrieval.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module]
            if isinstance(node, ast.ImportFrom) and node.module
            else []
        )
    }
    forbidden = ("pinecone", "qdrant", "chromadb", "weaviate", "pgvector")
    assert not any(name.startswith(forbidden) for name in imports)


def test_statusmatch_and_article_workflows_do_not_depend_on_each_other() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus"
    for path in (root / "statusmatch").glob("*.py"):
        imported = imported_journeyplus_modules(path)
        assert "article_pipeline" not in imported, path
        assert "article_operations" not in imported, path
    for path in (root / "article_pipeline").glob("*.py"):
        assert "statusmatch" not in imported_journeyplus_modules(path), path


def test_unified_membership_contracts_are_source_neutral() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus" / "membership"
    for filename in ("contracts.py", "normalization.py", "traversal.py"):
        imported = imported_journeyplus_modules(root / filename)
        assert "statusmatch" not in imported
        assert "article_pipeline" not in imported


def test_only_unified_read_layer_combines_mapping_adapters() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus"
    consumers: list[Path] = []
    for path in root.rglob("*.py"):
        if path.name == "contributions.py":
            continue
        text = path.read_text(encoding="utf-8")
        if (
            "StatusMatchOfficialContributionAdapter" in text
            and "OrdinaryArticleContributionAdapter" in text
        ):
            consumers.append(path.relative_to(root))
    assert consumers == [Path("membership/unified.py")]


def test_buy_points_domain_does_not_import_membership_or_article_business_layers() -> None:
    root = Path(__file__).parents[1] / "src" / "journeyplus" / "buy_points"
    forbidden = {
        "article_operations",
        "article_pipeline",
        "briefs",
        "facts",
        "membership",
        "statusmatch",
        "status_topic",
    }
    for path in root.glob("*.py"):
        assert not (imported_journeyplus_modules(path) & forbidden), path
