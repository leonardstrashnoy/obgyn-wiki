"""Quality checks for the compiled OB/GYN wiki.

The lint layer intentionally checks the filesystem, DuckDB graph, and exported
JSON snapshots together because this project is a compiled knowledge base: a
page, graph node, and static export can drift independently.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def slugify_link(text: str) -> str:
    """Normalize a wikilink target to a kebab-case slug."""
    target = text.split("|", 1)[0].strip()
    target = target.replace("_", "-").replace(" ", "-")
    target = re.sub(r"[^A-Za-z0-9\-]", "", target)
    target = re.sub(r"-+", "-", target).strip("-")
    return target.lower()


def iter_compiled_pages(wiki_root: Path):
    """Yield non-raw compiled markdown pages."""
    for page in sorted(wiki_root.rglob("*.md")):
        rel = page.relative_to(wiki_root)
        if rel.parts and rel.parts[0] == "raw":
            continue
        yield page


def _existing_slugs(wiki_root: Path) -> set[str]:
    slugs: set[str] = set()
    for page in iter_compiled_pages(wiki_root):
        stem = page.stem.lower()
        slugs.add(stem)
        slugs.add(stem.replace("_", "-"))
        slugs.add(stem.replace("-", "_"))
    return slugs


def _graph_counts(wiki_root: Path) -> dict[str, Any]:
    db = wiki_root / "semantic.db"
    if not db.exists():
        return {"db_exists": False}
    try:
        import duckdb

        con = duckdb.connect(str(db), read_only=True)
        try:
            node_count = con.execute("select count(*) from concept_nodes").fetchone()[0]
            edge_count = con.execute("select count(*) from concept_edges").fetchone()[0]
            canonical_count = con.execute(
                "select count(*) from concept_nodes where canonical=true"
            ).fetchone()[0]
        finally:
            con.close()
        return {
            "db_exists": True,
            "nodes": node_count,
            "edges": edge_count,
            "canonical_nodes": canonical_count,
        }
    except Exception as exc:  # pragma: no cover - defensive report path
        return {"db_exists": True, "error": str(exc)}


def _export_counts(wiki_root: Path) -> dict[str, Any]:
    project_root = wiki_root.parent
    paths = [
        wiki_root / "graph_data.json",
        project_root / "web" / "graph_data.json",
        project_root / "web" / "dist" / "graph_data.json",
    ]
    out = {}
    for path in paths:
        key = str(path.relative_to(project_root))
        if not path.exists():
            out[key] = None
            continue
        try:
            payload = json.loads(path.read_text("utf-8"))
            out[key] = {
                "nodes": len(payload.get("nodes", [])),
                "edges": len(payload.get("edges", [])),
            }
        except Exception as exc:
            out[key] = {"error": str(exc)}
    return out


def run_lint(wiki_root: str | Path, fail_on_warnings: bool = True) -> dict[str, Any]:
    """Return a structured wiki health report.

    The report is data-first so CLI, tests, and future CI can consume the same
    checks without scraping console output.
    """
    wiki_root = Path(wiki_root)
    existing = _existing_slugs(wiki_root)
    issues: dict[str, list[dict[str, Any]]] = {
        "missing_frontmatter": [],
        "fenced_frontmatter": [],
        "empty_brackets": [],
        "broken_wikilinks": [],
        "missing_evidence_level": [],
        "missing_sources": [],
        "short_pages": [],
    }

    for page in iter_compiled_pages(wiki_root):
        rel = str(page.relative_to(wiki_root))
        text = page.read_text("utf-8", errors="ignore")
        lines = text.splitlines()
        if text.startswith("```markdown"):
            issues["fenced_frontmatter"].append({"page": rel})
        if not text.startswith("---") and page.name not in {"index.md", "log.md", "SCHEMA.md", "coverage-matrix.md"}:
            issues["missing_frontmatter"].append({"page": rel})
        body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL)
        artifact_count = body.count("[]")
        if artifact_count:
            issues["empty_brackets"].append({"page": rel, "count": artifact_count})
        if "evidence_level:" not in text and page.name not in {"index.md", "log.md", "SCHEMA.md", "coverage-matrix.md"}:
            issues["missing_evidence_level"].append({"page": rel})
        if not any(marker in text for marker in ("sources:", "source:", "## Sources", "## References")) and page.name not in {"index.md", "log.md", "SCHEMA.md", "coverage-matrix.md"}:
            issues["missing_sources"].append({"page": rel})
        if len(lines) < 20 and page.name not in {"index.md", "log.md", "SCHEMA.md", "coverage-matrix.md"}:
            issues["short_pages"].append({"page": rel, "lines": len(lines)})
        if page.name in {"SCHEMA.md", "log.md"}:
            continue
        for raw_link in re.findall(r"\[\[([^\]]+)\]\]", body):
            slug = slugify_link(raw_link)
            if slug and slug not in existing and slug.replace("-", "_") not in existing:
                issues["broken_wikilinks"].append({"page": rel, "target": raw_link, "slug": slug})

    counts = {name: len(items) for name, items in issues.items()}
    counts["compiled_pages"] = sum(1 for _ in iter_compiled_pages(wiki_root))
    counts["graph"] = _graph_counts(wiki_root)
    exports = _export_counts(wiki_root)
    counts["exports"] = exports
    export_pairs = {
        (v.get("nodes"), v.get("edges"))
        for v in exports.values()
        if isinstance(v, dict) and "nodes" in v
    }
    counts["stale_exports"] = 0 if len(export_pairs) <= 1 else len(export_pairs)

    severity_blockers = [
        counts["fenced_frontmatter"],
        counts["empty_brackets"],
        counts["broken_wikilinks"],
        counts["stale_exports"],
    ]
    ok = not any(severity_blockers) if fail_on_warnings else True
    return {"ok": ok, "counts": counts, "issues": issues}


def format_lint_report(report: dict[str, Any]) -> str:
    """Human-readable lint summary for CLI output."""
    counts = report["counts"]
    lines = ["Wiki lint report", "================", f"OK: {report['ok']}", ""]
    for key in [
        "compiled_pages",
        "fenced_frontmatter",
        "empty_brackets",
        "broken_wikilinks",
        "missing_frontmatter",
        "missing_evidence_level",
        "missing_sources",
        "short_pages",
        "stale_exports",
    ]:
        lines.append(f"{key}: {counts.get(key)}")
    lines.append(f"graph: {counts.get('graph')}")
    lines.append(f"exports: {counts.get('exports')}")

    for name, items in report["issues"].items():
        if not items:
            continue
        lines.append("")
        lines.append(f"{name}:")
        for item in items[:20]:
            lines.append(f"  - {item}")
        if len(items) > 20:
            lines.append(f"  ... {len(items) - 20} more")
    return "\n".join(lines)
