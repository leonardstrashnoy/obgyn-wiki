"""Command-line interface for the OB/GYN Medical Wiki."""

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

# Ensure package is discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obgyn_wiki.medical_llm import generate_concept_page
from obgyn_wiki.pipeline import create_condition_page, ingest_batch, process_raw_article, update_index, update_log
from obgyn_wiki.pubmed_fetcher import fetch_article_details, ingest_mesh_topic, search_pubmed

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """OB/GYN Medical Wiki — doctor's assistant with compounding knowledge."""
    pass


@cli.command()
@click.option("--mesh", "-m", required=True, help="MeSH term to search (e.g. 'Preeclampsia')")
@click.option("--limit", "-n", default=10, help="Max results to fetch")
@click.option("--mindate", help="Minimum publication date (YYYY)")
@click.option("--maxdate", help="Maximum publication date (YYYY)")
@click.option("--oa-only/--all", default=True, help="Only open-access papers")
@click.option("--dry-run", is_flag=True, help="Preview without saving")
def fetch(mesh: str, limit: int, mindate: str | None, maxdate: str | None, oa_only: bool, dry_run: bool):
    """Fetch PubMed articles by MeSH term."""
    console.print(Panel(f"Fetching PubMed for: [bold green]{mesh}[/bold green]", style="cyan"))
    if dry_run:
        pmids = search_pubmed(
            f'"{mesh}"[MeSH Terms]',
            max_results=limit,
            mindate=mindate,
            maxdate=maxdate,
            oa_only=oa_only,
        )
        console.print(f"Would fetch {len(pmids)} PMIDs: {','.join(pmids[:5])}{'...' if len(pmids) > 5 else ''}")
        return

    saved = ingest_mesh_topic(mesh, limit=limit, mindate=mindate, maxdate=maxdate)
    console.print(f"[green]Saved {len(saved)} articles to {WIKI_ROOT / 'raw' / 'articles'}[/green]")


@cli.command()
@click.option("--topics", "-t", multiple=True, help="MeSH topics to ingest (default: starter set)")
@click.option("--limit", "-n", default=5, help="Articles per topic")
@click.option("--create-pages", is_flag=True, help="Also generate wiki concept pages")
@click.option("--dry-run", is_flag=True, help="Preview without writing")
def ingest(topics: list[str], limit: int, create_pages: bool, dry_run: bool):
    """Batch ingest articles and optionally create wiki pages."""
    topic_list = list(topics) if topics else None
    result = ingest_batch(
        mesh_terms=topic_list,
        limit_per_topic=limit,
        create_pages=create_pages,
        dry_run=dry_run,
    )
    console.print(f"\n[bold green]Ingestion complete:[/bold green] {len(result['saved'])} articles saved")


@cli.command()
@click.argument("question")
@click.option("--mode", type=click.Choice(["auto", "graph", "analytical", "keyword"]), default="auto")
@click.option("--llm", is_flag=True, help="Add LLM synthesis")
def query(question: str, mode: str, llm: bool):
    """Ask a clinical question against the compiled wiki (V2 orchestrator)."""
    from obgyn_wiki.orchestrator_v2 import query_wiki_v2

    console.print(Panel(f"Question: [bold]{question}[/bold]", style="blue"))
    result = query_wiki_v2(question, mode=mode, use_llm=llm)

    console.print(f"[dim]Mode: {result['mode']} | Found: {result['found']}[/dim]")
    console.print(result["answer"], markup=False)

    if result.get("llm_answer"):
        console.print(Panel(f"[italic]{result['llm_answer']}[/italic]", title="LLM Synthesis", style="green"))


@cli.command()
@click.option("--condition", "-c", required=True, help="Condition name")
@click.option("--sources", "-s", multiple=True, help="Raw source files (relative to wiki/)")
def create_page(condition: str, sources: list[str]):
    """Manually create a condition wiki page from raw sources."""
    raw_paths = [WIKI_ROOT / s for s in sources]
    existing = [p for p in raw_paths if p.exists()]
    if not existing:
        console.print("[red]No valid source files found.[/red]")
        return

    page = create_condition_page(condition, existing)
    if page:
        console.print(f"[green]Created: {page}[/green]")


@cli.command()
def status():
    """Show wiki statistics and recent activity."""
    raw_count = len(list((WIKI_ROOT / "raw" / "articles").glob("*.md")))
    condition_count = len(list((WIKI_ROOT / "conditions").glob("*.md")))
    drug_count = len(list((WIKI_ROOT / "drugs").glob("*.md")))
    procedure_count = len(list((WIKI_ROOT / "procedures").glob("*.md")))
    concept_count = len(list((WIKI_ROOT / "concepts").glob("*.md")))
    mechanism_count = len(list((WIKI_ROOT / "mechanisms").glob("*.md")))

    graph_counts = {"nodes": 0, "edges": 0}
    try:
        from obgyn_wiki.semantic_graph import SemanticGraph
        g = SemanticGraph(str(WIKI_ROOT / "semantic.db"))
        graph_counts = g.count()
        g.close()
    except Exception:
        pass

    console.print(Panel("Wiki Status", style="cyan"))
    console.print(f"  Raw articles:      {raw_count}")
    console.print(f"  Condition pages:   {condition_count}")
    console.print(f"  Drug pages:        {drug_count}")
    console.print(f"  Procedure pages:   {procedure_count}")
    console.print(f"  Concept pages:     {concept_count}")
    console.print(f"  Mechanism pages:   {mechanism_count}")
    console.print(f"  Graph:             {graph_counts['nodes']} nodes / {graph_counts['edges']} edges")
    console.print(f"\n  Wiki root: {WIKI_ROOT}")

@cli.command()
@click.option("--strict/--no-strict", default=False, help="Exit non-zero on warnings/blockers")
def lint(strict: bool):
    """Run wiki health check (broken links, graph drift, malformed pages)."""
    from obgyn_wiki.wiki_lint import format_lint_report, run_lint

    console.print(Panel("Wiki Lint", style="yellow"))
    report = run_lint(WIKI_ROOT, fail_on_warnings=strict)
    console.print(format_lint_report(report))
    if strict and not report["ok"]:
        raise click.ClickException("Wiki lint failed")


if __name__ == "__main__":
    cli()
