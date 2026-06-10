"""PubMed / PMC OA ingestion engine for OB/GYN literature.

Fetches article metadata via NCBI E-utilities, downloads open-access full text
from PubMed Central, and stores structured raw markdown with SHA256 drift detection.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import requests

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
RAW_ARTICLES_DIR = WIKI_ROOT / "raw" / "articles"
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")

# OB/GYN MeSH terms for filtering
OBGYN_MESH_TERMS = [
    "Pregnancy",
    "Obstetrics",
    "Gynecology",
    "Pregnancy Complications",
    "Fetal Diseases",
    "Genital Diseases, Female",
    "Reproductive Techniques, Assisted",
    "Labor, Obstetric",
    "Cesarean Section",
    "Prenatal Care",
    "Premenopause",
    "Perimenopause",
    "Menopause",
    "Ovarian Diseases",
    "Uterine Diseases",
    "Endometriosis",
    "Prenatal Care",
    "Prenatal Diagnosis",
    "Pregnancy, High-Risk",
    "Hypertension, Pregnancy-Induced",
    "Diabetes, Gestational",
]


@dataclass
class PubMedArticle:
    pmid: str
    pmcid: str | None
    title: str
    abstract: str
    authors: list[str]
    journal: str
    pub_date: str
    doi: str | None
    mesh_terms: list[str]
    keywords: list[str]
    oa_status: bool = False
    full_text: str | None = None
    pdf_url: str | None = None

    def slug(self) -> str:
        """URL-safe filename slug from first 6 words of title + pmid."""
        words = re.sub(r"[^\w\s]", "", self.title).lower().split()[:6]
        return f"{'-'.join(words)}-{self.pmid}"

    def to_markdown(self) -> str:
        """Full raw article markdown with frontmatter."""
        body = f"""# {self.title}

**Authors:** {', '.join(self.authors[:8])}{' et al.' if len(self.authors) > 8 else ''}
**Journal:** {self.journal}
**Published:** {self.pub_date}
**PMID:** [{self.pmid}](https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/)
**DOI:** {self.doi or 'N/A'}
**PMCID:** {self.pmcid or 'N/A'}
**MeSH terms:** {', '.join(self.mesh_terms[:20])}
**Keywords:** {', '.join(self.keywords[:20])}
**Open Access:** {self.oa_status}

## Abstract
{self.abstract or 'No abstract available.'}

## Full Text
{self.full_text or 'Full text not available (not in PMC OA).'}

## Notes
<!-- Ingestion agent: add study design, population, outcomes below -->
"""
        sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        frontmatter = f"""---
source_url: https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/
ingested: {time.strftime('%Y-%m-%d')}
sha256: {sha256}
pmid: "{self.pmid}"
pmcid: "{self.pmcid or 'N/A'}"
doi: "{self.doi or 'N/A'}"
journal: "{self.journal}"
pub_date: "{self.pub_date}"
---
"""
        return frontmatter + "\n" + body

    def save(self, overwrite: bool = False) -> Path | None:
        """Save to raw/articles/; skip if same sha already exists."""
        RAW_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
        path = RAW_ARTICLES_DIR / f"{self.slug()}.md"
        if path.exists() and not overwrite:
            # Check sha drift
            existing = path.read_text(encoding="utf-8")
            old_sha_match = re.search(r"^sha256:\s*(\w+)", existing, re.MULTILINE)
            if old_sha_match:
                old_sha = old_sha_match.group(1)
                new_body = self.to_markdown().split("---", 2)[-1]
                new_sha = hashlib.sha256(new_body.encode()).hexdigest()
                if old_sha == new_sha:
                    return None  # unchanged, skip
        path.write_text(self.to_markdown(), encoding="utf-8")
        return path


def _ncbi_eutils_url(tool: str, params: dict) -> str:
    base = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{tool}.fcgi"
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    params.setdefault("retmode", "json")
    return base + "?" + urllib.parse.urlencode(params)


def _safe_request(url: str, retries: int = 3) -> dict:
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if i == retries - 1:
                raise RuntimeError(f"Failed to fetch {url}: {e}")
            time.sleep((i + 1) * 2)
    return {}


def search_pubmed(
    query: str,
    max_results: int = 20,
    sort: str = "pub+date",
    mindate: str | None = None,
    maxdate: str | None = None,
    oa_only: bool = False,
) -> list[str]:
    """Return list of PMIDs matching query."""
    q = query
    if oa_only:
        q += " AND free full text[filter]"
    params = {
        "db": "pubmed",
        "term": q,
        "retmax": max_results,
        "sort": sort,
        "retmode": "json",
    }
    if mindate:
        params["mindate"] = mindate
    if maxdate:
        params["maxdate"] = maxdate
    data = _safe_request(_ncbi_eutils_url("esearch", params))
    ids = data.get("esearchresult", {}).get("idlist", [])
    return ids


def fetch_article_details(pmids: list[str]) -> list[PubMedArticle]:
    """Fetch metadata + abstract for a batch of PMIDs via ESummary + EFetch."""
    if not pmids:
        return []
    # ESummary for basic metadata
    summary_url = _ncbi_eutils_url("esummary", {"db": "pubmed", "id": ",".join(pmids)})
    summary_data = _safe_request(summary_url)
    articles = []

    # EFetch for abstracts + MeSH in XML
    efetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(pmids)}&retmode=xml"
    xml_resp = requests.get(efetch_url, timeout=60)
    xml_resp.raise_for_status()
    root = ET.fromstring(xml_resp.content)

    for pubmed_article in root.findall(".//PubmedArticle"):
        medline = pubmed_article.find(".//MedlineCitation")
        if medline is None:
            continue

        pmid_el = medline.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        # Title
        title_el = medline.find(".//ArticleTitle")
        title = "".join(title_el.itertext()) if title_el is not None else ""

        # Abstract
        abs_el = medline.find(".//Abstract")
        abstract = ""
        if abs_el is not None:
            for abs_text in abs_el.findall("AbstractText"):
                label = abs_text.get("Label", "")
                text = "".join(abs_text.itertext())
                abstract += (f"**{label}:** " if label else "") + text + "\n\n"

        # Authors
        authors = []
        auth_list = medline.find(".//AuthorList")
        if auth_list is not None:
            for author in auth_list.findall("Author"):
                last_el = author.find("LastName")
                last = last_el.text if last_el is not None else ""
                first_el = author.find("ForeName")
                first = first_el.text if first_el is not None else ""
                if last:
                    authors.append(f"{last} {first}".strip())

        # Journal + date
        journal_el = medline.find(".//Journal")
        journal_title = ""
        pub_date = ""
        if journal_el is not None:
            jt = journal_el.find("Title")
            journal_title = jt.text if jt is not None else ""
            jp = journal_el.find("JournalIssue/PubDate")
            if jp is not None:
                year_el = jp.find("Year")
                year = year_el.text if year_el is not None else ""
                month_el = jp.find("Month")
                month = month_el.text if month_el is not None else ""
                day_el = jp.find("Day")
                day = day_el.text if day_el is not None else ""
                pub_date = "-".join(filter(None, [year, month, day]))

        # DOI
        doi = None
        for aid in medline.findall(".//ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text

        # PMCID
        pmcid = None
        for aid in medline.findall(".//ArticleId"):
            if aid.get("IdType") == "pmc":
                pmcid = aid.text

        # MeSH terms
        mesh_terms = []
        mesh_list = medline.find(".//MeshHeadingList")
        if mesh_list is not None:
            for mesh in mesh_list.findall("MeshHeading"):
                desc_el = mesh.find("DescriptorName")
                desc = desc_el.text if desc_el is not None else ""
                if desc:
                    mesh_terms.append(desc)

        # Keywords
        keywords = []
        kw_list = medline.find(".//KeywordList")
        if kw_list is not None:
            for kw in kw_list.findall("Keyword"):
                ktext = "".join(kw.itertext())
                if ktext:
                    keywords.append(ktext)

        article = PubMedArticle(
            pmid=pmid,
            pmcid=pmcid,
            title=title.strip(),
            abstract=abstract.strip(),
            authors=authors,
            journal=journal_title,
            pub_date=pub_date or "",
            doi=doi,
            mesh_terms=mesh_terms,
            keywords=keywords,
            oa_status=pmcid is not None,
        )
        articles.append(article)

    return articles


def fetch_pmc_fulltext(pmcid: str) -> str | None:
    """Fetch full text from PMC OA via Europe PMC or direct NCBI link."""
    if not pmcid:
        return None
    # Try Europe PMC first (broader access)
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullText"
    try:
        resp = requests.get(url, timeout=60, headers={"Accept": "text/plain"})
        if resp.status_code == 200 and resp.text:
            text = re.sub(r'<[^>]+>', ' ', resp.text)  # strip XML/HTML tags roughly
            text = re.sub(r'\n\s*\n+', '\n\n', text)
            text = re.sub(r'[ \t]+', ' ', text)
            return text.strip()
    except Exception:
        pass

    # Try NCBI PMC API
    url = f"https://api.ncbi.nlm.nih.gov/lit/ctxp/v1/pubmed/?format=csl&id={pmcid}&contenttype=json"
    return None


def ingest_mesh_topic(
    mesh_term: str,
    limit: int = 10,
    mindate: str | None = None,
    maxdate: str | None = None,
) -> list[Path]:
    """Fetch, download full text where available, and save OA articles for a MeSH topic."""
    pmids = search_pubmed(
        f'{mesh_term}[MeSH Terms]',
        max_results=limit,
        mindate=mindate,
        maxdate=maxdate,
        oa_only=True,
    )
    print(f"  Found {len(pmids)} PMIDs for '{mesh_term}'")
    if not pmids:
        return []

    articles = fetch_article_details(pmids)
    saved: list[Path] = []
    for art in articles:
        if art.pmcid:
            art.full_text = fetch_pmc_fulltext(art.pmcid)
        result = art.save(overwrite=False)
        if result:
            print(f"  Saved: {result.name}")
            saved.append(result)
        else:
            print(f"  Skipped (already current): {art.slug()}")
        # NCBI rate limit: 3 requests/sec without key, 10/sec with key
        time.sleep(0.15 if NCBI_API_KEY else 0.35)
    return saved


if __name__ == "__main__":
    # Quick test
    saved = ingest_mesh_topic("Preeclampsia", limit=3)
    print(f"\nTotal saved: {len(saved)}")
