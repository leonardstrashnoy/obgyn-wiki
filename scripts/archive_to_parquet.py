#!/usr/bin/env python3
"""archive_to_parquet.py — One-time migration of raw markdown sources to Parquet.

Scans wiki/raw/{articles,textbooks}/*.md, extracts frontmatter + body,
and writes structured Parquet files to wiki/raw_archive/.
"""

import sys, re, os
from pathlib import Path
from datetime import datetime
import duckdb
import pandas as pd

WIKI_ROOT = Path("/home/leonard/Projects/obgyn-wiki/wiki")
RAW_DIR = WIKI_ROOT / "raw"
ARCHIVE_DIR = WIKI_ROOT / "raw_archive"

def extract_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter + extract H1 title if in body but not frontmatter."""
    fm = {}
    body = text
    match = re.match(r'^---\n(.*?)\n---\n+(.*)', text, re.DOTALL)
    if match:
        yaml_block = match.group(1)
        body = match.group(2)
        for line in yaml_block.strip().split('\n'):
            if ':' not in line:
                continue
            colon_idx = line.index(':')
            key = line[:colon_idx].strip()
            raw_val = line[colon_idx+1:].strip()
            fm[key] = raw_val

    # For articles without 'title' in frontmatter, extract from first H1
    if 'title' not in fm:
        h1_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        if h1_match:
            fm['title'] = h1_match.group(1).strip()

    return fm, body

def parse_tags(raw: str) -> list:
    """Parse tags like ['condition', 'ectopic'] into a list."""
    if not raw:
        return []
    # Handle YAML list formats
    raw = raw.strip()
    if raw.startswith('[') and raw.endswith(']'):
        inner = raw[1:-1].replace("'", "").replace('"', "")
        return [t.strip() for t in inner.split(',') if t.strip()]
    return [raw]

def parse_mesh(raw: str) -> list:
    """Parse MeSH terms from article frontmatter."""
    if not raw:
        return []
    # e.g. "Humans, Magnesium Sulfate, Pregnancy, ..."
    return [t.strip() for t in raw.split(',') if t.strip()]

def parse_pmid(raw: str) -> int | None:
    try:
        return int(raw.replace('"', '').replace("'", '').strip())
    except (ValueError, TypeError):
        return None

def parse_year(raw: str) -> int | None:
    try:
        return int(raw.replace('"', '').replace("'", '').strip())
    except (ValueError, TypeError):
        return None

def parse_date(raw: str) -> str | None:
    if not raw:
        return None
    return raw.replace('"', '').replace("'", '').strip()

def ingest_articles(articles_dir: Path) -> pd.DataFrame:
    rows = []
    for md in sorted(articles_dir.glob("*.md")):
        text = md.read_text("utf-8")
        fm, body = extract_frontmatter(text)

        row = {
            "pmid": parse_pmid(fm.get("pmid", "")),
            "title": fm.get("title", "").strip().strip('"\'\n'),
            "body": body.strip(),
            "abstract": body.strip()[:5000],  # preview column
            "journal": fm.get("journal", "").strip().strip('"\'\n'),
            "doi": fm.get("doi", "").strip().strip('"\'\n'),
            "pmcid": fm.get("pmcid", "").strip().strip('N/A').strip('"\'\n'),
            "pub_date": parse_date(fm.get("pub_date", "")),
            "ingest_date": parse_date(fm.get("ingested", "")),
            "sha256": fm.get("sha256", ""),
            "source_url": fm.get("source_url", ""),
            "mesh_terms": parse_mesh(fm.get("mesh_terms", "")),
            "topic": None,  # not available in article frontmatter
            "source_type": "pubmed_oa",
            "evidence_level": None,
            "source": f"raw/articles/{md.name}",
            "file_name": md.name,
        }
        rows.append(row)
    return pd.DataFrame(rows)

def ingest_textbooks(tb_dir: Path) -> pd.DataFrame:
    rows = []
    for md in sorted(tb_dir.glob("*.md")):
        # Skip the .pdf files in textbooks/
        if md.suffix != ".md" or md.name.endswith(".pdf"):
            continue
        text = md.read_text("utf-8")
        fm, body = extract_frontmatter(text)

        # Guess topic from file name or tags
        tags = parse_tags(fm.get("tags", ""))
        topic = None
        if tags:
            # Prefer a tag containing a clinical term
            for t in tags:
                if t not in ("condition", "ultrasound", "diagnostic", "screening"):
                    topic = t
                    break

        # Determine textbook source from filename prefix
        src_type = "textbook_other"
        if "callens" in md.name.lower():
            src_type = "textbook_callens"
        elif "gabbe" in md.name.lower():
            src_type = "textbook_gabbe"
        elif "evans" in md.name.lower():
            src_type = "textbook_evans"
        elif "practical" in md.name.lower():
            src_type = "textbook_practical"

        row = {
            "pmid": None,
            "title": fm.get("title", "").strip().strip('"\'\n'),
            "body": body.strip(),
            "abstract": body.strip()[:5000],
            "journal": fm.get("source", "").strip().strip('"\'\n'),
            "doi": None,
            "pmcid": None,
            "pub_date": str(parse_year(fm.get("year", "")) or ""),
            "ingest_date": None,
            "sha256": None,
            "source_url": None,
            "mesh_terms": [],
            "topic": topic,
            "source_type": src_type,
            "evidence_level": fm.get("evidence_level", "").strip().strip('"\'\n') or None,
            "source": f"raw/textbooks/{md.name}",
            "file_name": md.name,
        }
        rows.append(row)
    return pd.DataFrame(rows)

def main():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    log_entries = []

    print("=== OB/GYN Wiki — Markdown to Parquet Migration ===\n")

    # 1. Articles
    print("1. Ingesting 45 articles...")
    articles_df = ingest_articles(RAW_DIR / "articles")
    articles_file = ARCHIVE_DIR / "articles_2026-06.parquet"
    articles_df.to_parquet(articles_file, index=False)
    print(f"   -> {articles_file} ({len(articles_df)} rows, {articles_file.stat().st_size/1024:.0f} KB)")
    log_entries.append(f"articles: {len(articles_df)} rows -> {articles_file.name}")

    # 2. Textbooks
    print("2. Ingesting textbook excerpts...")
    textbooks_df = ingest_textbooks(RAW_DIR / "textbooks")
    textbooks_file = ARCHIVE_DIR / "textbooks.parquet"
    textbooks_df.to_parquet(textbooks_file, index=False)
    print(f"   -> {textbooks_file} ({len(textbooks_df)} rows, {textbooks_file.stat().st_size/1024:.0f} KB)")
    log_entries.append(f"textbooks: {len(textbooks_df)} rows -> {textbooks_file.name}")

    # 3. Combined (for unified querying)
    combined = pd.concat([articles_df, textbooks_df], ignore_index=True)
    combined_file = ARCHIVE_DIR / "sources_all.parquet"
    combined.to_parquet(combined_file, index=False)
    print(f"3. Combined -> {combined_file} ({len(combined)} rows, {combined_file.stat().st_size/1024:.0f} KB)")
    log_entries.append(f"combined: {len(combined)} rows -> {combined_file.name}")

    # 4. DuckDB validation
    print("\n4. DuckDB validation...")
    con = duckdb.connect(str(ARCHIVE_DIR / "sources_index.duckdb"))
    con.execute("CREATE OR REPLACE TABLE sources AS SELECT * FROM read_parquet('{}')" .format(combined_file))
    con.execute("CREATE INDEX idx_pmid ON sources(pmid)")
    con.execute("CREATE INDEX idx_topic ON sources(topic)")
    con.execute("CREATE INDEX idx_source_type ON sources(source_type)")
    con.execute("CREATE INDEX idx_evidence ON sources(evidence_level)")
    con.close()
    print(f"   -> DuckDB index: {ARCHIVE_DIR / 'sources_index.duckdb'}")
    log_entries.append(f"duckdb index created")

    # 5. Summary stats
    print("\n=== Summary ===")
    print(f"Sources: {len(combined)} total")
    print(f"  Articles: {len(articles_df)}")
    print(f"  Textbooks: {len(textbooks_df)}")
    print(f"Parquet files in: {ARCHIVE_DIR}")
    for f in sorted(ARCHIVE_DIR.glob("*.parquet")):
        print(f"  {f.name}: {f.stat().st_size/1024:.0f} KB")

    # 6. Save migration log
    log_path = ARCHIVE_DIR / "migration_log.txt"
    log_path.write_text(f"Migration date: {datetime.now().isoformat()}\n" + "\n".join(log_entries) + "\n", encoding="utf-8")
    print(f"\nLog: {log_path}")
    print("\n[OK] Phase 1 complete.")

if __name__ == "__main__":
    main()
