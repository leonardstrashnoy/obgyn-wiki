# OB/GYN Medical Wiki

A compounding knowledge base for evidence-based obstetrics and gynecology.
Doctor-facing AI assistant built on the LLM-Wiki pattern: synthesize sources into durable markdown pages, connect them with a DuckDB semantic graph, and query the compiled knowledge rather than raw chunks.

## Current State

- Compiled condition pages: 72
- Drug pages: 17
- Procedure pages: 12
- Concept pages: 13
- Mechanism pages: 4
- Raw PubMed article markdown files: 50
- Raw textbook markdown files: 39
- Semantic graph: 166 nodes / 208 edges
- Graph canonical page mappings: 119
- Live FastAPI + vis.js SPA: supported
- Static GitHub Pages export: supported

## Architecture

- Layer 0: immutable raw sources in `wiki/raw/` plus Parquet archive in `wiki/raw_archive/`
- Layer 1: compiled markdown wiki in `wiki/conditions`, `wiki/drugs`, `wiki/procedures`, `wiki/concepts`, and `wiki/mechanisms`
- Layer 2: DuckDB semantic graph in `wiki/semantic.db`
- Layer 3: hybrid query orchestrator in `obgyn_wiki/orchestrator_v2.py`
- UI: FastAPI backend and vis.js SPA in `obgyn_wiki/api_server.py` and `web/index.html`

## Quick Start

```bash
cd /home/leonard/Projects/obgyn-wiki

# Install dependencies
python -m pip install -r requirements.txt

# Fetch recent PubMed OA papers
python -m obgyn_wiki.cli fetch --mesh "Preeclampsia" --limit 5 --oa-only
python -m obgyn_wiki.cli fetch --mesh "Gestational Diabetes" --limit 5 --oa-only

# Batch ingest topics
python -m obgyn_wiki.cli ingest --topics "Preeclampsia" --limit 5 --create-pages

# Query the compiled wiki
python -m obgyn_wiki.cli query "Risk factors for preeclampsia"
python -m obgyn_wiki.cli query "How many conditions are in the graph?"
python -m obgyn_wiki.cli query "What is postpartum hemorrhage management?"

# Status and quality checks
python -m obgyn_wiki.cli status
python -m obgyn_wiki.cli lint
python -m pytest tests/ -q
```

## Directory Layout

```text
obgyn-wiki/
├── obgyn_wiki/
│   ├── pubmed_fetcher.py
│   ├── pipeline.py
│   ├── medical_llm.py
│   ├── wiki_writer.py
│   ├── citation_verifier.py
│   ├── semantic_graph.py
│   ├── orchestrator_v2.py
│   ├── wiki_lint.py
│   ├── api_server.py
│   └── cli.py
├── scripts/
│   ├── ingest_daily.py
│   ├── archive_to_parquet.py
│   ├── build_static.py
│   └── repair_gaps.py
├── tests/
│   └── test_quality.py
├── wiki/
│   ├── SCHEMA.md
│   ├── index.md
│   ├── log.md
│   ├── coverage-matrix.md
│   ├── semantic.db
│   ├── graph_data.json
│   ├── raw/
│   ├── raw_archive/
│   ├── conditions/
│   ├── drugs/
│   ├── procedures/
│   ├── concepts/
│   └── mechanisms/
└── web/
    ├── index.html
    ├── graph_data.json
    ├── vis-network.min.js
    └── dist/
```

## Evidence Grading

Every substantive clinical page should expose Oxford CEBM evidence metadata:

- 1A: systematic review / meta-analysis of RCTs
- 1B: individual RCT
- 2A: systematic review of cohort studies
- 2B: individual cohort / lower-quality RCT
- 3: case-control / case series
- 4: expert opinion, mechanistic evidence, or scaffolded coverage target pending synthesis

Pages with unresolved contradictions should set `contested: true` and list linked contradiction pages.

## Live API and Web UI

```bash
cd /home/leonard/Projects/obgyn-wiki
python -m uvicorn obgyn_wiki.api_server:app --host 0.0.0.0 --port 8765
```

Open:

```text
http://localhost:8765/
```

Important endpoints:

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health + node/edge counts |
| `GET /api/graph` | Full graph JSON |
| `GET /api/stats` | Lightweight graph counts |
| `GET /api/node/{id}` | Node details with forward/backward edges |
| `GET /api/search?q=...` | Search node labels/IDs |
| `POST /api/refresh` | Re-export graph JSON from DuckDB |
| `GET /api/query?question=...&mode=auto` | Run orchestrator query |
| `POST /api/nodes/{id}/expand` | Rule-based graph expansion from wiki text |
| `GET /api/events` | SSE stream for graph updates |

## Static Export

```bash
cd /home/leonard/Projects/obgyn-wiki
python scripts/build_static.py
```

Outputs:

```text
web/dist/index.html
web/dist/vis-network.min.js
web/dist/graph_data.json
```

The static build disables live API-only features and works as a GitHub Pages bundle.

## Maintenance Workflow

Recommended routine after ingestion or page generation:

```bash
python scripts/repair_gaps.py
python scripts/build_static.py
python -m obgyn_wiki.cli lint
python -m pytest tests/ -q
```

Daily ingestion uses a rolling PubMed date window with both `mindate` and `maxdate` in `scripts/ingest_daily.py`, preventing stale/trending re-fetch loops.

## Safety

This is a literature summary and knowledge-navigation tool, not a clinical advisor. It does not access patient records, generate patient-specific recommendations, or replace clinical judgment. Verify clinical information independently against primary sources and local guidelines.

## License

MIT — for educational and research use.
