# OB/GYN Wiki — Semantic Network, DuckDB, and Parquet Storage

**Date:** 2026-06-01  
**Context:** Current wiki has 8 compiled condition pages, ~84 raw sources (45 OA articles + 39 textbook excerpts), keyword-based orchestrator. Cron fetches 50 articles/day.  
**Goal:** Design a semantic knowledge layer (concept graph) with embedded analytical storage (DuckDB) and compressed raw archive (Parquet).

---

## 1. Problem Statement

### Current Orchestrator Limitations

`orchestrator.py` uses regex keyword matching:

- `find_relevant_pages()` → splits query into words, scores pages by word overlap
- `extract_relevant_sections()` → regex-match paragraphs containing any keyword
- No understanding of **synonyms**, **medical hierarchy**, or **causal relationships**
- Cross-page reasoning is manual (wikilinks like `[[placental-abruption]]` are static)
- Cannot answer relational queries: *"What conditions share placental dysfunction as a mechanism?"*
- Cannot do evidence aggregation: *"Show me all 1A-level recommendations across all pages"*

### Growth Pressure

| Metric | Current | 3 Months (projected) |
|--------|---------|---------------------|
| Raw sources | 84 | ~500 (50/day × 30d × 3mo) |
| Condition pages | 8 | ~20 |
| Total text | ~580 lines / 188 MB | ~2,000 lines / 600 MB |
| Query time | <1s (regex on small corpus) | Will degrade linearly |

---

## 2. Proposed Architecture

### Layer 0: Raw Sources (Parquet Archive)

**Purpose:** Compress and structure the ever-growing raw article/textbook text for efficient bulk processing.

```
wiki/raw_archive/
  articles_2026-06.parquet      # 50 rows × 5 columns
  textbooks.parquet             # 39 rows × 5 columns
  articles_2026-07.parquet      # next month's batch
```

**Schema:**

| Column | Type | Example |
|--------|------|---------|
| `pmid` | BIGINT | 42196264 |
| `title` | VARCHAR | "Understanding preeclampsia..." |
| `abstract` | VARCHAR | full text |
| `mesh_terms` | VARCHAR[] | ["Preeclampsia", "Placenta"] |
| `topic` | VARCHAR | "Preeclampsia" |
| `ingest_date` | DATE | 2026-06-01 |
| `source_type` | VARCHAR | "pubmed_oa" / "textbook_callens" / "textbook_gabbe" |
| `evidence_level` | VARCHAR | "2B" (if known) |

**Why Parquet:**
- Columnar compression: 188 MB markdown → ~15-30 MB Parquet
- Predicate pushdown: query only `topic='Preeclampsia'` without loading all files
- Partition-friendly: split by `ingest_month` for time-travel queries
- DuckDB reads Parquet natively with zero-copy

**Why NOT just keep markdown files:**
- File system glob + `read_text()` is fine at 100 files, painful at 1,000
- No structured metadata queries ("show me all articles from June with evidence_level='1A'")
- No bulk analytics ("trend of preeclampsia RCTs over last 6 months")

---

### Layer 1: Semantic Network (DuckDB Graph)

**Purpose:** A queryable concept graph representing medical entities and their relationships.

**Nodes table:**
```sql
CREATE TABLE concept_nodes (
    node_id      VARCHAR PRIMARY KEY,   -- slug: "preeclampsia"
    label        VARCHAR,               -- "Preeclampsia"
    node_type    VARCHAR,               -- "condition" | "symptom" | "drug" | "procedure" | "mechanism" | "risk_factor"
    canonical    BOOLEAN,                -- is this a wiki page?
    page_path    VARCHAR,               -- "conditions/preeclampsia.md" or NULL
    mesh_id      VARCHAR                -- MeSH CUI link
);
```

**Edges table:**
```sql
CREATE TABLE concept_edges (
    edge_id      VARCHAR PRIMARY KEY,
    from_node    VARCHAR REFERENCES concept_nodes(node_id),
    to_node      VARCHAR REFERENCES concept_nodes(node_id),
    relation     VARCHAR,               -- "causes" | "treats" | "diagnoses" | "contraindicated_with" | "risk_factor_for" | "complication_of"
    evidence     VARCHAR,               -- "1A" | "1B" | "2A" | "2B" | "expert_opinion"
    source       VARCHAR,               -- PMIDs or textbook page refs
    weight       FLOAT,                 -- confidence 0.0-1.0
    extracted_by VARCHAR                -- "manual" | "llm_extract" | "pubmed_mesh"
);
```

**Example graph query:**
```sql
-- "What conditions share placental dysfunction as a mechanism?"
WITH RECURSIVE related AS (
    SELECT to_node AS condition
    FROM concept_edges
    WHERE from_node = 'placental_dysfunction'
      AND relation = 'mechanism_of'
)
SELECT n.label, n.page_path
FROM related r
JOIN concept_nodes n ON r.condition = n.node_id;
```

---

### Layer 2: Orchestrator Upgrade

The orchestrator becomes a **hybrid retriever**:

1. **Keyword fallback** (fast, current behavior) — for simple term lookups
2. **Semantic graph query** (structured) — for relational/cross-page questions
3. **Parquet full-text** (analytical) — for evidence aggregation, trend queries
4. **LLM synthesis** (cloud/local) — for complex multi-source synthesis, unchanged

```python
def query_wiki_v2(question: str, mode: str = "auto") -> dict:
    """Multi-modal query routing."""
    
    if mode == "auto":
        # Heuristic: does question contain relational words?
        relational = any(w in question.lower() for w in 
            ["what conditions", "which drugs", "relationship", "causes", "risk factors for", "complications of"])
        if relational:
            mode = "graph"
        elif "evidence level" in question.lower() or "recommendations" in question.lower():
            mode = "analytical"
    
    if mode == "graph":
        return query_semantic_graph(question)
    elif mode == "analytical":
        return query_parquet_analytics(question)
    else:
        return query_keyword(question)  # current behavior
```

---

## 3. Implementation Phases

### Phase 1: Parquet Archive (Day 1-2)

**Files:**
- `scripts/archive_to_parquet.py` — batch-convert existing raw markdown to Parquet
- `scripts/ingest_daily.py` — modified to write new articles directly to Parquet (append)
- `obgyn_wiki/parquet_store.py` — read/write abstraction

**Steps:**
1. Install `pyarrow`, `duckdb`
2. Create `wiki/raw_archive/` directory
3. Write migration script: glob all `raw/articles/*.md` + `raw/textbooks/*.md` → single Parquet file with metadata extracted from frontmatter
4. Update `ingest_daily.py`: instead of writing `.md` files, append rows to `articles_YYYY-MM.parquet`
5. Keep `.md` files as human-readable mirrors (optional — could deprecate)

**Validation:**
```bash
python scripts/archive_to_parquet.py
# Verify: duckdb -c "SELECT topic, COUNT(*) FROM 'wiki/raw_archive/articles_2026-06.parquet' GROUP BY topic"
```

---

### Phase 2: Semantic Network Bootstrap (Day 3-5)

**Files:**
- `obgyn_wiki/semantic_graph.py` — graph CRUD, queries
- `scripts/bootstrap_graph.py` — extract nodes/edges from existing wiki pages
- `wiki/semantic.db` — DuckDB file (single file, no server)

**Steps:**
1. Manually seed **core nodes** from existing condition pages:
   - 8 conditions → 8 nodes
   - Symptoms mentioned in pages → symptom nodes
   - Drugs mentioned → drug nodes
   - Procedures → procedure nodes
2. Extract **edges** from compiled pages using simple NLP rules:
   - "Magnesium sulfate **prevents** eclampsia" → `magnesium_sulfate -treats-> eclampsia`
   - "Preeclampsia **causes** placental abruption" → `preeclampsia -causes-> placental_abruption`
   - "Low-dose aspirin **reduces risk of** preeclampsia" → `low_dose_aspirin -prevents-> preeclampsia`
3. Store in DuckDB: `semantic.db`

**Extraction approach:**
- **Option A:** Regex + medical keyword lists (fast, deterministic, limited coverage)
- **Option B:** Local LLM (MedGemma/OpenBioLLM) extracts triples from each page (better coverage, LLM-dependent)
- **Recommendation:** Start with A, augment with B for gaps

**Validation:**
```bash
python scripts/bootstrap_graph.py
# Verify: duckdb wiki/semantic.db "SELECT * FROM concept_edges WHERE relation='treats'"
```

---

### Phase 3: Orchestrator V2 (Day 6-7)

**Files:**
- `obgyn_wiki/orchestrator_v2.py` — new query router
- `obgyn_wiki/query_modes.py` — graph, analytical, keyword implementations

**Steps:**
1. Implement `query_semantic_graph()` using DuckDB recursive CTEs
2. Implement `query_parquet_analytics()` for aggregation queries
3. Wire into CLI with `--mode graph` / `--mode analytical` flags
4. Add interactive commands: `/graph`, `/analytics`, `/keyword`

**Validation:**
```bash
python -m obgyn_wiki.orchestrator_v2 "what conditions share placental dysfunction as mechanism?" --mode graph
python -m obgyn_wiki.orchestrator_v2 "show all 1A recommendations" --mode analytical
```

---

### Phase 4: Auto-Expansion (Day 8-10)

**Goal:** The graph grows automatically with each ingestion.

**Files:**
- `obgyn_wiki/graph_ingest.py` — extract concepts from new PubMed abstracts

**Steps:**
1. On each daily ingest, run MeSH term extraction from new articles
2. Auto-add nodes for unknown MeSH terms
3. Link `article → topic` edges with `extracted_by='pubmed_mesh'`
4. Weekly: run LLM extraction on new articles to find `drug-treats-condition` edges

---

## 4. Technology Choices & Tradeoffs

### DuckDB vs SQLite

| Feature | DuckDB | SQLite |
|---------|--------|--------|
| Parquet read | Native, zero-copy | Via extension, slower |
| Analytical queries | Vectorized, fast | Row-oriented, slower |
| Graph CTEs | Recursive CTE supported | Recursive CTE supported |
| Embeddable | Yes (single file) | Yes (single file) |
| Python API | `duckdb` module | `sqlite3` built-in |
| **Verdict** | ✅ Better for analytics + Parquet | Simpler but slower at scale |

### Parquet vs JSON Lines

| Feature | Parquet | JSON Lines |
|---------|---------|------------|
| Compression | Columnar, ~5-10x better | Line-level, moderate |
| Predicate pushdown | ✅ Only read matching columns/rows | ❌ Full scan |
| DuckDB query | Direct | Needs import step |
| Human readable | ❌ Binary | ✅ Text |
| **Verdict** | ✅ For bulk storage | For export/debug only |

### Manual Graph vs LLM-Extracted Graph

| Approach | Coverage | Accuracy | Cost | Speed |
|----------|----------|----------|------|-------|
| Regex/keyword rules | Low | High (deterministic) | Free | Instant |
| Local LLM (MedGemma) | Medium | Medium | Free (local GPU) | ~2s/page |
| Cloud LLM (OpenRouter) | High | High | $0.001-0.01/page | ~1s/page |
| **Recommendation** | Start with manual + local LLM hybrid | | | |

---

## 5. File Layout After Implementation

```
/home/leonard/Projects/obgyn-wiki/
├── obgyn_wiki/
│   ├── __init__.py
│   ├── medical_llm.py          # unchanged
│   ├── pubmed_fetcher.py         # add Parquet writer option
│   ├── parquet_store.py          # NEW: Parquet I/O
│   ├── semantic_graph.py         # NEW: DuckDB graph CRUD
│   ├── query_modes.py            # NEW: graph/analytical/keyword queries
│   ├── orchestrator.py           # keep as v1 fallback
│   └── orchestrator_v2.py        # NEW: hybrid router
├── scripts/
│   ├── ingest_daily.py           # add --parquet flag
│   ├── archive_to_parquet.py     # NEW: one-time migration
│   ├── bootstrap_graph.py        # NEW: seed graph from wiki
│   └── graph_ingest.py           # NEW: auto-grow graph
├── wiki/
│   ├── conditions/               # 8 pages (+ more)
│   ├── raw/                        # keep as human-readable
│   │   ├── articles/               # 45 files
│   │   └── textbooks/              # 39 files
│   ├── raw_archive/                # NEW: Parquet files
│   │   ├── articles_2026-06.parquet
│   │   └── textbooks.parquet
│   ├── semantic.db                 # NEW: DuckDB graph database
│   ├── index.md
│   ├── log.md
│   └── SCHEMA.md
```

---

## 6. Risks & Open Questions

1. **Graph quality:** Auto-extracted edges from LLM will have errors. Need a `confidence` field and manual review workflow.
2. **DuckDB portability:** `semantic.db` is a single file but may have platform-specific compiled extensions. Test on Grace Hopper ARM64.
3. **Parquet schema evolution:** As we add columns (e.g., `embedding` vector), older Parquet files need migration or union views.
4. **Duplication:** Should we keep `.md` mirrors + Parquet? Or migrate fully to Parquet and generate `.md` on demand for human review?
5. **Embeddings:** Should the graph store vector embeddings for semantic similarity (via `duckdb-vss` extension)? This would enable "find similar conditions" queries.

---

## 7. Recommended Priority

Given the current state (84 sources, 8 pages, functional keyword search), the highest-value next step is:

**Phase 1 (Parquet) + Phase 2 (Graph Bootstrap) together** — they are independent and both unlock new capabilities.

- Parquet solves the **storage scaling** problem immediately
- Graph enables **relational queries** that the current system cannot do at all

Phase 3 (Orchestrator V2) depends on both. Phase 4 (Auto-Expansion) is a nice-to-have after the core is solid.

---

## 8. Estimated Effort

| Phase | Days | Complexity |
|-------|------|------------|
| Parquet Archive | 1-2 | Low |
| Semantic Graph Bootstrap | 2-3 | Medium |
| Orchestrator V2 | 1-2 | Medium |
| Auto-Expansion | 2-3 | High |
| **Total** | **6-10 days** | **Medium-High** |

---

*Plan written in plan mode. No code executed. Ready for implementation when approved.*
