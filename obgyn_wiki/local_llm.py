"""Local medical LLM subagent using Ollama HTTP API.

Ollama manages model loading, GPU offloading, and inference.
We just call the API at localhost:11434.

Models (from `ollama list`):
  - hf.co/mradermacher/OpenBioLLM-Llama3-70B-GGUF:Q4_K_M  (42GB, best reasoning)
  - hf.co/unsloth/medgemma-27b-text-it-GGUF:Q4_K_M         (16GB, fast)
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable

import requests
from rich.console import Console

console = Console()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API = f"{OLLAMA_HOST}/api"

# Model name mapping: short_name -> ollama_name
MODEL_REGISTRY = {
    "openbiollm-70b": "hf.co/mradermacher/OpenBioLLM-Llama3-70B-GGUF:Q4_K_M",
    "medgemma-27b": "hf.co/unsloth/medgemma-27b-text-it-GGUF:Q4_K_M",
    "medgemma-4b": "hf.co/unsloth/medgemma-4b-it-GGUF:Q4_K_M",
    "mistral-7b": "mistral:7b-instruct",
}

# Task -> default model
TASK_DEFAULTS = {
    "synthesis": "medgemma-27b",      # Fast + good at structured JSON
    "contradiction": "medgemma-27b",  # Fast comparison
    "verification": "medgemma-27b",   # Fast checks
    "generation": "openbiollm-70b",   # Best prose quality for wiki pages
    "query": "medgemma-27b",          # Fast enough for Q&A
}


def _ollama_post(endpoint: str, payload: dict, timeout: int = 300) -> dict:
    """POST to Ollama API with error handling."""
    url = f"{OLLAMA_API}/{endpoint}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Cannot connect to Ollama at {OLLAMA_HOST}. Is it running?")
    except requests.exceptions.HTTPError as e:
        detail = e.response.text[:500] if hasattr(e, "response") else str(e)
        raise RuntimeError(f"Ollama error: {detail}")


def list_ollama_models() -> list[dict]:
    """List available models from Ollama."""
    try:
        resp = requests.get(f"{OLLAMA_API}/tags", timeout=10)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        console.print(f"[red]Cannot reach Ollama: {e}[/red]")
        return []


def check_model_available(short_name: str) -> bool:
    """Verify a model is pulled and available."""
    ollama_name = MODEL_REGISTRY.get(short_name)
    if not ollama_name:
        return False
    models = list_ollama_models()
    return any(m.get("name") == ollama_name for m in models)


def ensure_model_loaded(short_name: str, timeout: int = 600) -> bool:
    """Pull model if not available. Returns True if ready."""
    if check_model_available(short_name):
        return True
    ollama_name = MODEL_REGISTRY.get(short_name)
    if not ollama_name:
        console.print(f"[red]Unknown model: {short_name}[/red]")
        return False

    console.print(f"[yellow]{short_name} not found. Pulling {ollama_name}...[/yellow]")
    try:
        resp = requests.post(
            f"{OLLAMA_API}/pull",
            json={"name": ollama_name, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        console.print(f"[green]{short_name} pulled successfully.[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Pull failed: {e}[/red]")
        return False


# ---- Prompt Templates ----

CLINICAL_SYNTHESIS_PROMPT = """You are a medical evidence synthesis specialist in obstetrics and gynecology.
Read the following article and extract structured information.

Return your answer as a JSON object with these exact keys:
- study_design: string
- population: string
- intervention: string or null
- comparison: string or null
- primary_outcome: string
- secondary_outcomes: list of strings
- adverse_events: string or null
- limitations: string
- clinical_bottom_line: string
- evidence_level: one of "1A", "1B", "2A", "2B", "3", "4"
- conditions_mentioned: list
- interventions_mentioned: list

Article:
---
{article_text}
---

Output ONLY valid JSON. No markdown code fences. No commentary."""

CONTRADICTION_PROMPT = """Compare EXISTING wiki summary vs NEW source. Return JSON:
{"assessment": "contradicts|supports|adds", "details": "...", "flag_contested": true/false}

EXISTING:
---
{existing_summary}
---

NEW:
---
{new_source}
---
"""

WIKI_PAGE_GENERATION_PROMPT = """Create a markdown wiki page for: {topic}

Frontmatter: title, created, updated, type, confidence, evidence_level, contested, contradictions, tags, sources.

Sections:
1. Clinical Definition
2. Epidemiology
3. Pathophysiology
4. Evidence-based Management (with evidence levels inline like (1A), (2B))
5. Complications and prognosis
6. Active research / open questions
7. Related topics as [[wikilink]]

Rules:
- Every clinical claim MUST cite an evidence level
- Use lowercase-hyphen [[wikilinks]]
- Never invent statistics
- If uncertain, say so and mark confidence: low

Sources:
---
{source_texts}
---
"""


# ---- Core Inference ----

def call_local_llm(
    prompt: str,
    model: str | None = None,
    task: str = "generation",
    temperature: float = 0.1,
    max_tokens: int = 4000,
    expect_json: bool = True,
) -> dict:
    """Run inference via Ollama generate API."""
    short_name = model or TASK_DEFAULTS.get(task, "medgemma-27b")
    ollama_name = MODEL_REGISTRY.get(short_name, short_name)

    if not check_model_available(short_name):
        if not ensure_model_loaded(short_name):
            raise RuntimeError(f"Model {short_name} not available and could not be pulled.")

    payload = {
        "model": ollama_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "repeat_penalty": 1.1,
            "stop": ["<|user|>", "<|system|>", "<|end|>"],
        },
    }

    start = time.time()
    result = _ollama_post("generate", payload, timeout=600)
    elapsed = time.time() - start

    text = result.get("response", "").strip()
    meta = {
        "model": short_name,
        "ollama_model": ollama_name,
        "elapsed_ms": int(elapsed * 1000),
        "prompt_eval_count": result.get("prompt_eval_count", 0),
        "eval_count": result.get("eval_count", 0),
        "total_tokens": (result.get("prompt_eval_count", 0) + result.get("eval_count", 0)),
    }

    if expect_json:
        text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE)
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            text = match.group(1)
        try:
            parsed = json.loads(text)
            parsed["_meta"] = meta
            return parsed
        except json.JSONDecodeError as e:
            return {"error": "json_parse_failed", "raw": result.get("response", ""), "_meta": meta}

    return {"content": text, "_meta": meta}


# ---- Task-specific wrappers ----

def synthesize_article_local(article_text: str, model: str | None = None) -> dict:
    prompt = CLINICAL_SYNTHESIS_PROMPT.format(article_text=article_text[:20000])
    return call_local_llm(prompt, model=model, task="synthesis", expect_json=True)


def detect_contradiction_local(existing_summary: str, new_source: str, model: str | None = None) -> dict:
    prompt = CONTRADICTION_PROMPT.format(
        existing_summary=existing_summary[:8000],
        new_source=new_source[:8000],
    )
    return call_local_llm(prompt, model=model, task="contradiction", expect_json=True)


def generate_concept_page_local(
    topic: str,
    source_texts: list[str],
    evidence_level: str = "2B",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    model: str | None = None,
) -> str:
    from datetime import date
    tags_str = ", ".join(f'"{t}"' for t in (tags or ["condition", "needs-review"]))
    sources_str = ", ".join(f'"{s}"' for s in (sources or ["raw/articles/TODO.md"]))
    prompt = WIKI_PAGE_GENERATION_PROMPT.format(
        topic=topic,
        today=date.today().isoformat(),
        evidence_level=evidence_level,
        tags=tags_str,
        sources=sources_str,
        source_texts="\n---\n".join(source_texts[:5]),
    )
    result = call_local_llm(prompt, model=model, task="generation", expect_json=False, temperature=0.2)
    return result.get("content", "")


def unload_model(short_name: str) -> None:
    """Ask Ollama to unload a model from memory."""
    ollama_name = MODEL_REGISTRY.get(short_name, short_name)
    try:
        requests.post(f"{OLLAMA_API}/generate", json={"model": ollama_name, "keep_alive": 0}, timeout=10)
        console.print(f"[dim]Unloaded {short_name} from GPU/CPU.[/dim]")
    except Exception as e:
        console.print(f"[dim]Unload signal sent (may still cache): {e}[/dim]")


# ---- Diagnostics ----

def diagnose() -> None:
    """Print system status for local LLMs."""
    console.print("[bold]Local LLM Diagnostics[/bold]\n")

    # Ollama connection
    try:
        resp = requests.get(f"{OLLAMA_API}/tags", timeout=5)
        models = resp.json().get("models", [])
        console.print(f"[green]Ollama reachable at {OLLAMA_HOST}[/green]")
        console.print(f"  Available models: {len(models)}")
        for m in models:
            name = m.get("name", "unknown")
            size_gb = m.get("size", 0) / 1e9
            console.print(f"    - {name} ({size_gb:.1f} GB)")
    except Exception as e:
        console.print(f"[red]Ollama not reachable: {e}[/red]")
        return

    # Check our required models
    console.print("\n[bold]Required Models:[/bold]")
    for short, ollama_name in MODEL_REGISTRY.items():
        found = any(m.get("name") == ollama_name for m in models)
        status = "[green]✓ available[/green]" if found else "[red]✗ missing[/red]"
        console.print(f"  {short}: {status}")


if __name__ == "__main__":
    diagnose()
