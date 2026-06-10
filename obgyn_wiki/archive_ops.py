"""obgyn_wiki/archive_ops.py — Append new markdown sources to Parquet + DuckDB.

Used by ingest_daily.py to keep the Parquet archive in sync with new .md files.
"""

import re
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import duckdb

WIKI_ROOT = Path("/home/leonard/Projects/obgyn-wiki/wiki")
RAW_DIR = WIKI_ROOT / "raw"
ARCHIVE_DIR = WIKI_ROOT / "raw_archive"

# Mirror the parsing helpers from archive_to_parquet.py

def _extract_frontmatter(text: str):
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
    if 'title' not in fm:
        h1_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        if h1_match:
            fm['title'] = h1_match.group(1).strip()
    return fm, body

def _parse_tags(raw):
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith('[') and raw.endswith(']'):
        inner = raw[1:-1].replace("'", "").replace('"', "")
        return [t.strip() for t in inner.split(',') if t.strip()]
    return [raw]

def _parse_mesh(raw):
    if not raw:
        return []
    return [t.strip() for t in raw.split(',') if t.strip()]

def _parse_pmid(raw):
    try:
        return int(raw.replace('"', '').replace("'", '').strip())
    except (ValueError, TypeError):
        return None

def _parse_year(raw):
    try:
        return int(raw.replace('"', '').replace("'", '').strip())
    except (ValueError, TypeError):
        return None

def _parse_date(raw):
    if not raw:
        return None
    return raw.replace('"', '').replace("'", '').strip()

def _row_from_article(md: Path) -> dict:
    text = md.read_text("utf-8")
    fm, body = _extract_frontmatter(text)
    return {
        "pmid": _parse_pmid(fm.get("pmid", "")),
        "title": fm.get("title", "").strip().strip('"\'\n'),
        "body": body.strip(),
        "abstract": body.strip()[:5000],
        "journal": fm.get("journal", "").strip().strip('"\'\n'),
        "doi": fm.get("doi", "").strip().strip('"\'\n'),
        "pmcid": fm.get("pmcid", "").strip().strip('N/A').strip('"\'\n'),
        "pub_date": _parse_date(fm.get("pub_date", "")),
        "ingest_date": _parse_date(fm.get("ingested", "")),
        "sha256": fm.get("sha256", ""),
        "source_url": fm.get("source_url", ""),
        "mesh_terms": _parse_mesh(fm.get("mesh_terms", "")),
        "topic": None,
        "source_type": "pubmed_oa",
        "evidence_level": None,
        "source": f"raw/articles/{md.name}",
        "file_name": md.name,
    }

def _row_from_textbook(md: Path) -> dict:
    text = md.read_text("utf-8")
    fm, body = _extract_frontmatter(text)
    tags = _parse_tags(fm.get("tags", ""))
    topic = None
    if tags:
        for t in tags:
            if t not in ("condition", "ultrasound", "diagnostic", "screening"):
                topic = t
                break
    src_type = "textbook_other"
    if "callens" in md.name.lower():
        src_type = "textbook_callens"
    elif "gabbe" in md.name.lower():
        src_type = "textbook_gabbe"
    elif "evans" in md.name.lower():
        src_type = "textbook_evans"
    elif "practical" in md.name.lower():
        src_type = "textbook_practical"
    return {
        "pmid": None,
        "title": fm.get("title", "").strip().strip('"\'\n'),
        "body": body.strip(),
        "abstract": body.strip()[:5000],
        "journal": fm.get("source", "").strip().strip('"\'\n'),
        "doi": None,
        "pmcid": None,
        "pub_date": str(_parse_year(fm.get("year", "")) or ""),
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

def append_article(md: Path) -> None:
    """Append a single article markdown to the monthly Parquet archive."""
    article_file = ARCHIVE_DIR / "articles_2026-06.parquet"
    combined_file = ARCHIVE_DIR / "sources_all.parquet"
    
    if not article_file.exists():
        raise FileNotFoundError(f"Base archive missing: {article_file}")
    
    new_row = _row_from_article(md)
    existing = pd.read_parquet(article_file)
    
    # Deduplicate by file_name
    if new_row["file_name"] in existing["file_name"].values:
        # Overwrite existing row with same file_name
        existing = existing[existing["file_name"] != new_row["file_name"]]
    
    updated = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
    updated.to_parquet(article_file, index=False)
    
    # Rebuild combined
    tb_file = ARCHIVE_DIR / "textbooks.parquet"
    if tb_file.exists():
        tb_df = pd.read_parquet(tb_file)
        combined = pd.concat([updated, tb_df], ignore_index=True)
    else:
        combined = updated
    combined.to_parquet(combined_file, index=False)
    
    # Rebuild DuckDB
    rebuild_duckdb()

def append_textbook(md: Path) -> None:
    """Append a single textbook excerpt to the Parquet archive."""
    tb_file = ARCHIVE_DIR / "textbooks.parquet"
    combined_file = ARCHIVE_DIR / "sources_all.parquet"
    
    if not tb_file.exists():
        raise FileNotFoundError(f"Base archive missing: {tb_file}")
    
    new_row = _row_from_textbook(md)
    existing = pd.read_parquet(tb_file)
    
    if new_row["file_name"] in existing["file_name"].values:
        existing = existing[existing["file_name"] != new_row["file_name"]]
    
    updated = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
    updated.to_parquet(tb_file, index=False)
    
    # Rebuild combined
    art_file = ARCHIVE_DIR / "articles_2026-06.parquet"
    if art_file.exists():
        art_df = pd.read_parquet(art_file)
        combined = pd.concat([art_df, updated], ignore_index=True)
    else:
        combined = updated
    combined.to_parquet(combined_file, index=False)
    
    rebuild_duckdb()

def rebuild_duckdb() -> None:
    """Rebuild the DuckDB index from the combined Parquet."""
    combined_file = ARCHIVE_DIR / "sources_all.parquet"
    db_file = ARCHIVE_DIR / "sources_index.duckdb"
    
    con = duckdb.connect(str(db_file))
    con.execute(f"CREATE OR REPLACE TABLE sources AS SELECT * FROM read_parquet('{combined_file}')")
    con.execute("CREATE INDEX idx_pmid ON sources(pmid)")
    con.execute("CREATE INDEX idx_topic ON sources(topic)")
    con.execute("CREATE INDEX idx_source_type ON sources(source_type)")
    con.execute("CREATE INDEX idx_evidence ON sources(evidence_level)")
    con.close()

# Convenience: sync all raw markdown files (e.g., after manual edits)
def full_resync() -> dict:
    """Rebuild all Parquet + DuckDB from scratch from raw markdown."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("archive_to_parquet", str(WIKI_ROOT.parent / "scripts" / "archive_to_parquet.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    return {"message": "Full resync complete"}
