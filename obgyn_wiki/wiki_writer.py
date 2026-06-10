"""Wiki page writer utilities: markdown generation, link validation, frontmatter helpers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

WIKI_ROOT = Path("/home/leonard/Projects/obgyn-wiki/wiki")


def slugify(text: str) -> str:
    """Convert text to lowercase-hyphen slug."""
    return re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")


def make_frontmatter(
    title: str,
    page_type: str,
    confidence: str = "medium",
    evidence_level: str = "2B",
    contested: bool = False,
    contradictions: list[str] | None = None,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
) -> str:
    """Generate standardized YAML frontmatter."""
    lines = [
        "---",
        f'title: "{title}"',
        f"created: {date.today().isoformat()}",
        f"updated: {date.today().isoformat()}",
        f"type: {page_type}",
        f"confidence: {confidence}",
        f'evidence_level: "{evidence_level}"',
        f"contested: {str(contested).lower()}",
    ]
    if contradictions:
        lines.append(f"contradictions: [{', '.join(contradictions)}]")
    else:
        lines.append("contradictions: []")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    if sources:
        lines.append(f"sources: [{', '.join(sources)}]")
    lines.append("---")
    return "\n".join(lines) + "\n"


def validate_wikilink(page_text: str, all_existing_pages: set[str] | None = None) -> list[dict]:
    """Check for broken wikilinks in a page."""
    links = re.findall(r"\[\[(.*?)\]\]", page_text)
    issues = []
    if all_existing_pages is None:
        all_existing_pages = {p.stem.lower() for p in WIKI_ROOT.rglob("*.md") if p.name not in {"SCHEMA.md", "index.md", "log.md"}}
    for link in links:
        target = slugify(link)
        if target not in all_existing_pages:
            issues.append({"type": "broken_wikilink", "target": link, "suggested_slug": target})
    return issues


def extract_citations(page_text: str) -> list[str]:
    """Find all raw source markers like ^[raw/articles/foo.md] in text."""
    return re.findall(r"\^\[raw/[\w\-/]+\.md\]", page_text)


if __name__ == "__main__":
    # Quick test
    fm = make_frontmatter(
        title="Preeclampsia Management",
        page_type="condition",
        confidence="high",
        evidence_level="1A",
        tags=["condition", "hypertension", "pregnancy"],
        sources=["raw/articles/preeclampsia-magie-trial.md"],
    )
    print(fm)
