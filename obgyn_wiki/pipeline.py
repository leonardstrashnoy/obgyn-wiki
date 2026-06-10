"""Ingestion pipeline: raw articles → structured wiki pages.

Orchestrates PubMed fetch, medical LLM synthesis, and wiki page generation.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.table import Table

from obgyn_wiki.medical_llm import call_medical_llm, generate_concept_page, synthesize_article
from obgyn_wiki.pubmed_fetcher import fetch_article_details, ingest_mesh_topic, search_pubmed

console = Console()
WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))


def update_log(action: str, subject: str, details: list[str]) -> None:
    """Append to wiki/log.md."""
    log_path = WIKI_ROOT / "log.md"
    lines = [
        f"",
        f"## [{date.today().isoformat()}] {action} | {subject}",
    ]
    for d in details:
        lines.append(f"- {d}")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def update_index(page_type: str, page_name: str, summary: str) -> None:
    """Add or update an entry in index.md."""
    index_path = WIKI_ROOT / "index.md"
    content = index_path.read_text(encoding="utf-8")
    entry = f"- [[{page_name}]] — {summary}"
    section_map = {
        "conditions": "## Conditions",
        "interventions": "## Interventions",
        "drug-interactions": "## Drug-Safety Profiles",
        "guidelines": "## Guidelines \u0026 Summaries",
        "queries": "## Queries \u0026 Deep Dives",
    }
    section_marker = section_map.get(page_type, "## Conditions")
    if entry not in content:
        # Add entry after the section marker
        content = content.replace(
            section_marker,
            f"{section_marker}\n{entry}",
        )
        # Update page count
        content = re.sub(
            r"Total pages:\s*\d+",
            lambda m: f"Total pages: {int(m.group().split(':')[1].strip()) + 1}",
            content,
        )
        content = re.sub(
            r"Last updated: \d{4}-\d{2}-\d{2}",
            f"Last updated: {date.today().isoformat()}",
            content,
        )
        index_path.write_text(content, encoding="utf-8")


def find_existing_pages_for(topic: str) -> list[Path]:
    """Search wiki for relevant existing pages."""
    results = []
    slug = topic.replace(" ", "-").lower()
    for subdir in [WIKI_ROOT / "conditions", WIKI_ROOT / "interventions", WIKI_ROOT / "drug-interactions"]:
        for f in subdir.glob("*.md"):
            if slug in f.stem.lower() or any(word in f.stem.lower() for word in topic.lower().split()):
                results.append(f)
    return results


def process_raw_article(raw_path: Path, dry_run: bool = False) -> dict:
    """Read a raw article, run medical LLM synthesis, return structured extraction."""
    text = raw_path.read_text(encoding="utf-8")
    # Strip frontmatter
    body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL)
    if len(body) < 200:
        console.print(f"[yellow]Skipping short file: {raw_path.name}[/yellow]")
        return {}

    console.print(f"  Synthesizing: {raw_path.name[:60]}...")
    result = synthesize_article(body[:18000])
    if "error" in result:
        console.print(f"  [red]Synthesis failed: {result['error']}[/red]")
        return result

    # Attach filename for provenance
    result["_source_file"] = str(raw_path.relative_to(WIKI_ROOT))

    if not dry_run:
        # Note: actual wiki page creation is done by a higher-level coordinator
        # that groups by condition/intervention. This function just does extraction.
        pass

    return result


def create_condition_page(
    condition_name: str,
    raw_sources: list[Path],
    model: str | None = None,
) -> Path | None:
    """Create or update a condition wiki page from multiple raw sources."""
    slug = condition_name.replace(" ", "-").lower()
    page_path = WIKI_ROOT / "conditions" / f"{slug}.md"

    # Collect source texts
    texts = []
    for src in raw_sources:
        text = src.read_text(encoding="utf-8")
        body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL)
        texts.append(body[:12000])

    if not texts:
        return None

    console.print(f"[green]Generating condition page: {condition_name} ...[/green]")
    evidence_level = "2B"  # default; could be upgraded by a human reviewer
    tags = ["condition", "needs-review"]
    source_refs = [str(s.relative_to(WIKI_ROOT)) for s in raw_sources]

    page_md = generate_concept_page(
        topic=condition_name,
        source_texts=texts,
        evidence_level=evidence_level,
        tags=tags,
        sources=source_refs,
        model=model,
    )

    page_path.write_text(page_md, encoding="utf-8")
    update_index("conditions", slug, f"Evidence summary for {condition_name}")
    update_log(
        "create",
        f"Condition page: {condition_name}",
        [f"Page: conditions/{slug}.md", f"Sources: {len(raw_sources)}"],
    )
    return page_path


def ingest_batch(
    mesh_terms: list[str] | None = None,
    limit_per_topic: int = 5,
    create_pages: bool = False,
    dry_run: bool = False,
) -> dict:
    """Fetch from PubMed and optionally create wiki pages."""
    if mesh_terms is None:
        # Default starter set
        mesh_terms = ["Preeclampsia", "Gestational Diabetes", "Ectopic Pregnancy", "Preterm Labor"]

    total_fetched = 0
    total_saved = []
    article_extractions: list[dict] = []

    for mesh in mesh_terms:
        console.rule(f"[bold cyan]Fetching: {mesh}[/bold cyan]")
        raw_paths = ingest_mesh_topic(mesh, limit=limit_per_topic)
        total_saved.extend(raw_paths)

        for raw_path in raw_paths:
            extraction = process_raw_article(raw_path, dry_run=dry_run)
            if extraction and "error" not in extraction:
                article_extractions.append(extraction)

    console.print(f"\n[green]Total articles saved: {len(total_saved)}[/green]")
    if create_pages and not dry_run:
        # Simple grouping: create pages for the MeSH topics we queried
        for mesh in mesh_terms:
            raw_files = list(WIKI_ROOT / "raw" / "articles" / "*.md")
            # Find articles matching this mesh (naive: check metadata for now)
            # In practice you'd parse the MeSH terms from the raw markdown
            console.print(f"[blue]Would create/update page for: {mesh}[/blue]")

    return {
        "saved": total_saved,
        "extractions": article_extractions,
    }


if __name__ == "__main__":
    # Test
    result = ingest_batch(["Preeclampsia"], limit_per_topic=2, dry_run=False)
    print(f"Saved {len(result['saved'])} articles.")
