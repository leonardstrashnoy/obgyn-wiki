"""OB/GYN Wiki Medical Assistant - Orchestrator.

Answers clinical questions by querying the compiled markdown wiki.
No patient data. Literature summary only. Safe by design.
"""

import os
import re
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
console = Console()


def find_relevant_pages(question: str) -> list[Path]:
    """Semantic-ish search: scan wiki pages for keywords from the question."""
    keywords = set(re.findall(r'\w+', question.lower()))
    stop = {"what", "is", "the", "a", "an", "for", "in", "of", "and", "or", "to", "with", "are", "how", "does", "did", "do", "evidence", "treatment", "management", "current"}
    keywords -= stop

    matches = []
    for subdir in [WIKI_ROOT / "conditions", WIKI_ROOT / "interventions", WIKI_ROOT / "drug-interactions"]:
        if subdir.exists():
            for f in subdir.glob("*.md"):
                text = f.read_text("utf-8").lower()
                score = sum(1 for kw in keywords if kw in text)
                if score > 0:
                    matches.append((f, score))
    matches.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in matches[:5]]


def extract_relevant_sections(text: str, keywords: set[str], max_chars: int = 2000) -> str:
    """Extract paragraphs/sections containing query keywords."""
    lines = text.split('\n')
    relevant_blocks = []
    current_block = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_block:
                block_text = '\n'.join(current_block)
                if any(kw in block_text.lower() for kw in keywords):
                    relevant_blocks.append(block_text)
                current_block = []
            continue
        current_block.append(stripped)
    
    if current_block and any(kw in '\n'.join(current_block).lower() for kw in keywords):
        relevant_blocks.append('\n'.join(current_block))
    
    # Also extract section headers matching keywords
    for i, line in enumerate(lines):
        lower = line.lower()
        if line.startswith('##') and any(kw in lower for kw in keywords):
            # Collect this section
            section = [line]
            for j in range(i+1, min(i+20, len(lines))):
                if lines[j].startswith('##') or lines[j].startswith('---'):
                    break
                section.append(lines[j])
            relevant_blocks.append('\n'.join(section))
    
    result = '\n\n'.join(relevant_blocks)
    return result[:max_chars]


def query_wiki(question: str, use_llm: bool = False, model: str | None = None) -> dict:
    """Find relevant pages, read them, extract content, and synthesize answer."""
    keywords = set(re.findall(r'\w+', question.lower()))
    stop = {"what", "is", "the", "a", "an", "for", "in", "of", "and", "or", "to", "with", "are", "how", "does", "did", "do", "evidence", "treatment", "management", "current"}
    query_keywords = keywords - stop
    
    relevant = find_relevant_pages(question)
    context = []
    sources = []
    
    for page in relevant:
        text = page.read_text("utf-8")
        body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL)
        excerpt = extract_relevant_sections(body, query_keywords, max_chars=3000)
        if excerpt.strip():
            context.append(f"--- FROM: {page.stem} ---\n{excerpt}")
        sources.append(f"{page.stem}.md")
    
    if not context:
        return {
            "answer": "No relevant content found in wiki for this query. Try ingesting more articles or adding textbook sources.",
            "sources": [],
            "confidence": "none",
        }
    
    # Try local LLM synthesis if requested
    if use_llm:
        try:
            from obgyn_wiki.local_llm import call_local_llm
            context_block = "\n\n".join(context)[:8000]
            prompt = f"""You are an evidence-based OB/GYN specialist assistant.
A doctor asks: "{question}"

Below are excerpts from the medical wiki. Synthesize a concise, evidenced answer.
Include evidence levels inline. If the wiki doesn't contain sufficient evidence, say so.
NEVER make up statistics. Cite the source pages you used.

{context_block}
"""
            result = call_local_llm(prompt, model=model or "medgemma-27b", expect_json=False, temperature=0.1, max_tokens=1024)
            answer = result.get("content", "Synthesis failed.")
            token_info = f" (tokens: {result.get('eval_count', '?')})"
            llm_used = True
        except Exception as e:
            answer = f"LLM synthesis failed: {e}. Showing raw excerpts instead."
            token_info = ""
            llm_used = False
    else:
        # Manual extraction: show relevant sections
        answer_parts = [
            "📚 **Evidence-Based Answer** (from compiled wiki)\n",
            f"Question: *{question}*\n",
            f"Relevant pages: {', '.join(sources)}\n",
            "---",
        ]
        for ctx in context:
            answer_parts.append(ctx)
            answer_parts.append("---")
        
        # Add disclaimer
        answer_parts.append("\n⚠️ **Disclaimer:** This is a literature summary, not patient-specific advice. Always verify with current guidelines.")
        answer = "\n".join(answer_parts)
        token_info = ""
        llm_used = False
    
    return {
        "answer": answer,
        "sources": sources,
        "confidence": "medium",
        "llm_used": llm_used,
        "token_info": token_info,
    }


def interactive_mode():
    """REPL for clinical questions."""
    console.print(Panel("OB/GYN Medical Wiki Assistant", subtitle="Type 'quit' to exit | 'llm' to toggle local LLM synthesis", style="cyan"))
    use_llm = False
    
    while True:
        try:
            q = console.input("\n[bold blue]Question: [/bold blue]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in {"quit", "exit", "q"}:
            break
        if q.lower() == "llm":
            use_llm = not use_llm
            console.print(f"[yellow]LLM synthesis: {'ON' if use_llm else 'OFF'}[/yellow]")
            continue
        
        result = query_wiki(q, use_llm=use_llm, model="medgemma-27b")
        console.print(result["answer"])
        if result.get("token_info"):
            console.print(f"[dim]{result['token_info']}[/dim]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        result = query_wiki(question, use_llm=False)
        print(result["answer"])
    else:
        interactive_mode()
