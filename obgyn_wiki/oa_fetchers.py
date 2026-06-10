"""Unpaywall and Europe PMC full-text fetchers.

Unpaywall finds OA PDFs from publisher sites.
Europe PMC has broader OA coverage than PMC itself.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path

import requests

UNPAYWALL_EMAIL = "user@obgyn-wiki.local"  # Required by Unpaywall API terms
EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def fetch_unpaywall_pdf(doi: str, dest_dir: Path) -> Path | None:
    """Query Unpaywall for OA PDF URL, download if found."""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        best = data.get("best_oa_location")
        if best and best.get("url_for_pdf"):
            pdf_url = best["url_for_pdf"]
            pdf_resp = requests.get(pdf_url, timeout=60, headers={"User-Agent": "obgyn-wiki-bot/0.1"})
            if pdf_resp.status_code == 200 and pdf_resp.headers.get("content-type", "").startswith("application/pdf"):
                slug = doi.replace("/", "_").replace(".", "_")
                dest = dest_dir / f"unpaywall_{slug}.pdf"
                dest.write_bytes(pdf_resp.content)
                return dest
    except Exception as e:
        print(f"Unpaywall fetch failed for {doi}: {e}")
    return None


def fetch_europe_pmc_text(pmcid: str) -> str | None:
    """Fetch full text from Europe PMC — more reliable than NCBI for OA."""
    if not pmcid:
        return None
    # Try plaintext endpoint first
    url = f"{EUROPE_PMC_API}/{pmcid}/fullText"
    try:
        resp = requests.get(url, timeout=30, headers={"Accept": "text/plain"})
        if resp.status_code == 200 and resp.text:
            text = resp.text
            # Strip XML/HTML if present (Europe PMC returns XML sometimes)
            text = re.sub(r'<[^\u003e]+>', ' ', text)
            text = re.sub(r'\n\s*\n+', '\n\n', text)
            text = re.sub(r'[ \t]+', ' ', text)
            return text.strip()
    except Exception:
        pass

    # Try Provenance / Reference JSON as fallback
    url2 = f"{EUROPE_PMC_API}/{pmcid}?format=json"
    try:
        resp2 = requests.get(url2, timeout=30)
        if resp2.status_code == 200:
            data = resp2.json()
            # extract abstract if available
            result = data.get("resultList", {}).get("result", [{}])[0]
            abstract = result.get("abstractText", "")
            if abstract:
                return abstract
    except Exception:
        pass
    return None


def try_fetch_fulltext(doi: str | None, pmcid: str | None, fallback_abstract: str = "") -> str:
    """Best-effort full text: Europe PMC > Unpaywall > abstract."""
    # Europe PMC tries PMCID first
    if pmcid and pmcid != "N/A":
        text = fetch_europe_pmc_text(pmcid)
        if text and len(text) > 500:
            return f"[Europe PMC full text for {pmcid}:\n\n{text[:10000]}]"

    # Unpaywall tries DOI
    if doi and doi != "N/A":
        # Just return a note for now; actual PDF parsing needs pymupdf
        return f"[OA PDF available via Unpaywall for DOI {doi}. Use pymupdf to extract full text.]\n\n{fallback_abstract}"

    # Fallback
    return fallback_abstract


if __name__ == "__main__":
    # Example: fetch Europe PMC text for a known PMC article
    import sys
    test = fetch_europe_pmc_text("PMC1234567")  # Replace with real PMCID
    print(f"Europe PMC test: {len(test) if test else 0} chars")
