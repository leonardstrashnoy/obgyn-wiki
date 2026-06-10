"""Medical LLM subagent — unifies cloud (OpenRouter) and local (Ollama) backends.

Backend selection (via USE_LOCAL_LLM env var):
  auto  → use local Ollama if models available, else cloud
  always→ force local Ollama
  never → force OpenRouter cloud

Local models (Ollama):
  - openbiollm-70b: hf.co/mradermacher/OpenBioLLM-Llama3-70B-GGUF:Q4_K_M (42GB)
  - medgemma-27b:   hf.co/unsloth/medgemma-27b-text-it-GGUF:Q4_K_M (16GB)
  - medgemma-4b:    hf.co/unsloth/medgemma-4b-it-GGUF:Q4_K_M (3GB)

Cloud models (OpenRouter):
  - mistralai/mistral-large-latest (default)
  - anthropic/claude-3.5-sonnet
  - etc.
"""

from __future__ import annotations

import json
import os
import re
import time

import requests
from rich.console import Console

console = Console()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_MEDICAL_MODEL = os.getenv("DEFAULT_MEDICAL_MODEL", "mistralai/mistral-large-latest")
USE_LOCAL = os.getenv("USE_LOCAL_LLM", "auto").lower()


# ==================== Prompt Templates ====================

CLINICAL_SYNTHESIS_PROMPT = """You are a medical evidence synthesis specialist in obstetrics and gynecology.
Read the following article and extract structured information.

Return your answer as a JSON object with these exact keys:
- study_design: string (RCT, cohort, case-control, systematic review, meta-analysis, narrative review, etc.)
- population: string (sample size, demographics, inclusion/exclusion criteria summary)
- intervention: string or null
- comparison: string or null
- primary_outcome: string with effect size if reported
- secondary_outcomes: list of strings
- adverse_events: string or null
- limitations: string
- clinical_bottom_line: string (1-2 sentences)
- evidence_level: one of "1A", "1B", "2A", "2B", "3", "4"
- conditions_mentioned: list of condition names (for wiki linking)
- interventions_mentioned: list of drug/procedure names (for wiki linking)

Article:
---
{article_text}
---

Output ONLY valid JSON. No markdown code fences. No extra commentary."""

CONTRADICTION_PROMPT = """You are a medical evidence monitoring specialist.
Below is an EXISTING wiki page summary, followed by a NEW source.

Determine if the new source CONTRADICTS, SUPPORTS, or ADDS to the existing page.
If CONTRADICTS: identify the specific contradictory claims and explain why.
If SUPPORTS: summarize how.
If ADDS: summarize the new information.

Return JSON: {"assessment": "contradicts|supports|adds", "details": "...", "flag_contested": true/false}

EXISTING page summary:
---
{existing_summary}
---

NEW source:
---
{new_source}
---
"""

WIKI_PAGE_GENERATION_PROMPT = """You are a medical knowledge base editor building an OB/GNY wiki.
Create a markdown wiki page for the topic: {topic}

Use this exact YAML frontmatter structure:
---
title: "{topic}"
created: {today}
updated: {today}
type: concept
confidence: medium
evidence_level: "{evidence_level}"
contested: false
contradictions: []
tags: [{tags}]
sources: [{sources}]
---

Then write the body:
1. Clinical Definition / what it is
2. Epidemiology (incidence, risk factors if known)
3. Pathophysiology summary
4. Evidence-based Management (with evidence levels cited inline)
5. Complications and prognosis
6. Active research / open questions
7. Related topics (linked as [[topic-name]])

Rules:
- Every clinical claim MUST cite an evidence level in parentheses, e.g., (1A) or (2B)
- Always use lowercase-hyphen wikilinks like [[preeclampsia]] or [[magnesium-sulfate]]
- End with "## Sources" listing the source files
- If uncertain about a claim, say so and mark confidence: low in frontmatter
- Never invent statistics. Only use what is in the provided sources.

Sources to synthesize:
---
{source_texts}
---
"""


# ==================== Backend Selection ====================

def _local_available() -> bool:
    """Check if Ollama is running with at least medgemma-27b."""
    try:
        from obgyn_wiki.local_llm import check_model_available
        return check_model_available("medgemma-27b")
    except Exception:
        return False


def _choose_backend() -> str:
    if USE_LOCAL == "always":
        return "local"
    if USE_LOCAL == "never":
        return "cloud"
    if USE_LOCAL == "auto":
        return "local" if _local_available() else "cloud"
    return "local"


# ==================== Cloud (OpenRouter) ====================

def call_openrouter(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.1,
    max_retries: int = 3,
    timeout: int = 120,
    expect_json: bool = True,
) -> dict:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = model or DEFAULT_MEDICAL_MODEL
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/leonard/obgyn-wiki",
        "X-Title": "OB/GYN Medical Wiki",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a precise medical research assistant. Return only structured output."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4000,
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            meta = {
                "model": model,
                "backend": "openrouter",
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }
            if expect_json:
                text = re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
                match = re.search(r"(\{.*\})", text, re.DOTALL)
                if match:
                    text = match.group(1)
                try:
                    parsed = json.loads(text)
                    parsed["_meta"] = meta
                    return parsed
                except json.JSONDecodeError:
                    if attempt == max_retries - 1:
                        return {"error": "json_parse_failed", "raw": content, "_meta": meta}
                    time.sleep(2 ** attempt)
                    continue
            else:
                return {"content": content, "_meta": meta}
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"OpenRouter failed: {e}")
            time.sleep(2 ** attempt)
    return {"error": "max_retries_exceeded"}


# ==================== Unified Entry Point ====================

def call_medical_llm(
    prompt: str,
    model: str | None = None,
    task: str = "generation",
    temperature: float = 0.1,
    expect_json: bool = True,
) -> dict:
    """Unified call: routes to local Ollama or OpenRouter based on config."""
    backend = _choose_backend()
    if backend == "local":
        from obgyn_wiki.local_llm import call_local_llm
        return call_local_llm(prompt, model=model, task=task, temperature=temperature, expect_json=expect_json)
    else:
        return call_openrouter(prompt, model=model, temperature=temperature, expect_json=expect_json)


def synthesize_article(article_text: str, model: str | None = None) -> dict:
    prompt = CLINICAL_SYNTHESIS_PROMPT.format(article_text=article_text[:20000])
    return call_medical_llm(prompt, model=model, task="synthesis", expect_json=True)


def detect_contradiction(existing_summary: str, new_source: str, model: str | None = None) -> dict:
    prompt = CONTRADICTION_PROMPT.format(
        existing_summary=existing_summary[:8000],
        new_source=new_source[:8000],
    )
    return call_medical_llm(prompt, model=model, task="contradiction", expect_json=True)


def generate_concept_page(
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
    result = call_medical_llm(prompt, model=model, task="generation", expect_json=False, temperature=0.2)
    return result.get("content", "")


if __name__ == "__main__":
    backend = _choose_backend()
    print(f"Medical LLM module. Backend: {backend}")
    if backend == "local":
        from obgyn_wiki.local_llm import list_ollama_models
        models = list_ollama_models()
        print(f"Ollama models: {len(models)}")
    else:
        print(f"Cloud: {DEFAULT_MEDICAL_MODEL}")
        print(f"API key: {'yes' if OPENROUTER_API_KEY else 'no'}")
    print("Set USE_LOCAL_LLM=always|never|auto to control backend")
