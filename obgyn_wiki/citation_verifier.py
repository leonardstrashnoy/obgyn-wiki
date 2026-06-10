"""Citation verifier: ensure generated claims trace back to retrieved sources.

Uses a lightweight LLM call or rule-based matching to check faithfulness.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

from obgyn_wiki.medical_llm import call_medical_llm


CITATION_VERIFY_PROMPT = """You are a medical citation verifier. Your job is to check if every
claim in the ANSWER is supported by the provided SOURCES.

For each numbered claim, respond:
- "SUPPORTED" if the claim is clearly backed by a source
- "UNVERIFIED" if the claim is plausible but not explicitly in the sources
- "CONTRADICTS" if the claim conflicts with the sources
- "HALLUCINATED" if the claim has no basis in the sources

Return your response as a JSON array:
[
  {"claim": "...", "assessment": "SUPPORTED|UNVERIFIED|CONTRADICTS|HALLUCINATED", "source_ref": "..."}
]

ANSWER:
---
{answer}
---

SOURCES:
---
{sources}
---
"""


def verify_answer_faithfulness(answer: str, source_texts: list[str]) -> list[dict]:
    """Send answer + sources to LLM for faithfulness check."""
    sources_block = "\n---\n".join(source_texts[:3])
    prompt = CITATION_VERIFY_PROMPT.format(answer=answer[:5000], sources=sources_block[:15000])
    result = call_medical_llm(prompt, expect_json=True, temperature=0.0)
    if "error" in result:
        return [{"claim": "Verification failed", "assessment": "ERROR", "detail": result.get("error")}]
    # Ensure array shape
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        # Sometimes LLM wraps array in a dict key
        for key in result:
            if isinstance(result[key], list):
                return result[key]
    return [{"claim": "Unclear structure", "assessment": "UNVERIFIED"}]


def extract_numerical_claims(text: str) -> list[dict]:
    """Rule-based: find stats, percentages, p-values in text for fact-checking."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*%",
        r"\brolder?\s*(?:r|risk ratio)\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"\bhazard ratio\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"\bodd?s ratio\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"\bp[- ]?value\s*[<(]?\s*(\d+(?:\.\d+)?)",
        r"\bn\s*=\s*(\d+(?:,\d+)?)",
    ]
    claims = []
    for pat in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            claims.append({
                "text": match.group(0),
                "value": match.group(1),
                "position": match.start(),
            })
    return claims


def check_source_contains_claim(source_text: str, claim_text: str) -> bool:
    """Simple fuzzy check if a claim string appears in source text."""
    # Normalize: lower, remove punctuation for fuzzy match
    source_norm = re.sub(r"[^\w\s]", "", source_text.lower())
    claim_norm = re.sub(r"[^\w\s]", "", claim_text.lower())
    if len(claim_norm) < 5:
        return False
    # Allow partial match of claim fragments
    fragments = claim_norm.split()
    if len(fragments) <= 3:
        return claim_norm in source_norm
    # For longer claims, check all 3-grams
    ngrams = set()
    for i in range(len(fragments) - 2):
        ngrams.add(" ".join(fragments[i:i+3]))
    source_words = source_norm.split()
    source_ngrams = set()
    for i in range(len(source_words) - 2):
        source_ngrams.add(" ".join(source_words[i:i+3]))
    if ngrams:
        overlap = len(ngrams & source_ngrams) / len(ngrams)
        return overlap > 0.3
    return False


if __name__ == "__main__":
    # Test
    claims = extract_numerical_claims("The trial showed a 32% risk reduction (RR 0.68, 95% CI 0.52-0.89, p<0.01) in n=1,230 participants.")
    print(f"Found {len(claims)} numerical claims")
    for c in claims:
        print(f"  {c['text']} → value: {c['value']}")
