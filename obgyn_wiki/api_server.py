"""obgyn_wiki/api_server.py — FastAPI app for OB/GYN Wiki semantic network.

Provides REST endpoints for graph data, node expansion, wiki queries,
and SSE push for real-time updates.  Serves the SPA static files.

Start:
    cd /home/leonard/Projects/obgyn-wiki && python3 -m uvicorn obgyn_wiki.api_server:app --host 0.0.0.0 --port 8765 --reload

Then open http://localhost:8765/
"""

import asyncio
import json
import os
import time
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
import uvicorn

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
SEMANTIC_DB = WIKI_ROOT / "semantic.db"
GRAPH_JSON = WIKI_ROOT / "graph_data.json"
WEB_DIR = Path(__file__).parent.parent / "web"

# ── SSE subscription management ────────────────
_event_queues: set = set()
_graph_mtime: float = 0.0


def _broadcast(kind: str, payload: dict):
    """Push JSON-SSE event to all connected clients."""
    msg = json.dumps({"event": kind, "payload": payload, "ts": time.time()})
    dead = set()
    for q in _event_queues:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.add(q)
    for q in dead:
        _event_queues.discard(q)


def _notify_graph_updated():
    stat = SEMANTIC_DB.stat()
    _broadcast("graph_rebuilt", {"nodes": None, "edges": None, "mtime": stat.st_mtime})

# ── Startup tasks ───────────────────────────────

async def _poll_graph_changes():
    """Background task that watches semantic.db mtime and SSE-notifies."""
    global _graph_mtime
    while True:
        await asyncio.sleep(15)
        if SEMANTIC_DB.exists():
            mtime = SEMANTIC_DB.stat().st_mtime
            if mtime != _graph_mtime:
                _graph_mtime = mtime
                _notify_graph_updated()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if SEMANTIC_DB.exists():
        global _graph_mtime
        _graph_mtime = SEMANTIC_DB.stat().st_mtime
    task = asyncio.create_task(_poll_graph_changes())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="OB/GYN Wiki Semantic Network API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets (vis-network.js, graph_data.json cache)
_static_mounted = False
if (WEB_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets"), check_dir=False), name="assets")  # fixed
# old: directory=str(WEB_DIR)), name="assets")
    _static_mounted = True

# ── Helpers ────────────────────────────────────

def _load_graph():
    if GRAPH_JSON.exists():
        return json.loads(GRAPH_JSON.read_text("utf-8"))
    raise HTTPException(503, detail="Graph data not exported yet. Run refresh first.")


def _ensure_db():
    if not SEMANTIC_DB.exists():
        raise HTTPException(503, detail="Semantic graph DB not initialized.")
    from obgyn_wiki.semantic_graph import SemanticGraph
    return SemanticGraph(str(SEMANTIC_DB))


# ── API endpoints ────────────────────────────────

@app.get("/api/health")
def health():
    from obgyn_wiki.semantic_graph import SemanticGraph
    db_ok = SEMANTIC_DB.exists()
    node_count = 0
    edge_count = 0
    if db_ok:
        try:
            g = SemanticGraph(str(SEMANTIC_DB))
            c = g.count()
            node_count, edge_count = c["nodes"], c["edges"]
            g.close()
        except Exception:
            db_ok = False
    return {
        "status": "ok",
        "db_exists": db_ok,
        "node_count": node_count,
        "edge_count": edge_count,
        "graph_json_exists": GRAPH_JSON.exists(),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/graph")
def get_graph():
    """Return full graph JSON (nodes + edges)."""
    data = _load_graph()
    return _load_graph()


@app.get("/api/stats")
def get_stats():
    """Quick graph stats without full payload."""
    g = _ensure_db()
    return g.count()


@app.get("/api/node/{node_id}")
def get_node(node_id: str, relation: Optional[str] = None):
    """Return node details + forward/backward edges."""
    g = _ensure_db()
    node = g.get_node(node_id)
    if not node:
        raise HTTPException(404, detail=f"Node '{node_id}' not found.")
    # Get edges with labels
    forward = g.query_related(node_id, relation=relation)
    backward = g.query_backward(node_id, relation=relation)
    # Resolve labels in edges
    node_ids = {r["node_id"] for r in forward + backward}
    node_ids.add(node_id)
    labels = {}
    for nid in node_ids:
        n = g.get_node(nid)
        labels[nid] = n[1] if n else nid
    g.close()
    return {
        "node": dict(zip(["node_id", "label", "node_type", "canonical", "page_path", "mesh_id"], node)),
        "forward": [{**r, "label": labels.get(r["node_id"], r["node_id"])} for r in forward],
        "backward": [{**r, "label": labels.get(r["node_id"], r["node_id"])} for r in backward],
    }


@app.get("/api/search")
def search_nodes(q: str = Query(..., min_length=1), type_filter: Optional[str] = None):
    """Text search across node labels, returning matching IDs."""
    g = _ensure_db()
    q_lower = q.lower()
    rows = g.list_nodes()
    results = []
    for r in rows:
        if q_lower in r["label"].lower() or q_lower in r["node_id"]:
            if not type_filter or r["node_type"] == type_filter:
                results.append(r)
    g.close()
    return {"count": len(results), "results": results}


@app.post("/api/refresh")
def refresh_graph():
    """Re-export graph_data.json from DuckDB and notify clients."""
    import json as _json
    g = _ensure_db()
    nodes = g.list_nodes()
    edges_raw = g.list_edges()
    g.close()
    edge_data = []
    for e in edges_raw:
        edge_data.append({
            "from": e["from_node"],
            "to": e["to_node"],
            "relation": e["relation"],
            "evidence": e["evidence"],
            "source": e["source"],
        })
    payload = {
        "nodes": [{"id": n["node_id"], "label": n["label"], "group": n["node_type"],
                   "canonical": n["canonical"], "page": n["page_path"], "mesh": n["mesh_id"]} for n in nodes],
        "edges": edge_data,
    }
    GRAPH_JSON.write_text(_json.dumps(payload, indent=2), "utf-8")
    _notify_graph_updated()
    return {"status": "refreshed", "nodes": len(nodes), "edges": len(edge_data)}


@app.get("/api/query")
def run_query(question: str = Query(..., min_length=2), mode: str = "auto"):
    """Run orchestrator_v2 query and return structured result."""
    from obgyn_wiki.orchestrator_v2 import query_wiki_v2
    result = query_wiki_v2(question, mode=mode, use_llm=False)
    return result


@app.get("/api/events")
async def events():
    """Server-sent events endpoint for live graph updates."""
    q: asyncio.Queue = asyncio.Queue(maxsize=32)
    _event_queues.add(q)

    async def generator():
        try:
            while True:
                msg = await q.get()
                yield f"data: {msg}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            _event_queues.discard(q)

    return StreamingResponse(generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ── Graph Expansion (extract edges from raw sources) ──────────

EXPANSION_RELATIONS = {
    "treats": ["used", "administered", "treatment", "therapy", "managed with"],
    "prevents": ["prevention", "prophylactic", "reduces risk"],
    "causes": ["associated with", "caused by", "results in", "leads to", "risk factor"],
    "mechanism_of": ["mechanism", "pathophysiology", "underlying", "etiology"],
    "diagnoses": ["diagnosis", "diagnosed by", "imaging", "ultrasound", "screening"],
    "assesses": ["assessment", "monitoring", "evaluation", "surveillance"],
}


def _extract_edges_from_text(text: str, node_id: str, label: str) -> List[dict]:
    """Naive rule-based edge extraction from markdown text."""
    found = []
    lower = text.lower()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for sent in sentences:
        sent_lower = sent.lower()
        for rel, phrases in EXPANSION_RELATIONS.items():
            for phrase in phrases:
                if label.lower() in sent_lower and phrase in sent_lower:
                    # Try to find what other known node is mentioned
                    found.append({
                        "relation": rel,
                        "context": sent.strip()[:200],
                        "extracted_by": "rule_expansion",
                    })
                    break
    return found


@app.post("/api/nodes/{node_id}/expand")
def expand_node(node_id: str, background: bool = False):
    """Extract new edges for a node from raw wiki/PubMed sources.

    If background=True, return immediately and enqueue an async task.
    Otherwise run synchronously (slow).
    """
    g = _ensure_db()
    node = g.get_node(node_id)
    if not node:
        g.close()
        raise HTTPException(404, detail="Node not found")
    label = node[1]
    page_path = node[4]
    g.close()

    # Read wiki page text if present
    text = ""
    if page_path:
        wiki_page = (WIKI_ROOT / page_path).with_suffix(".md")
        if wiki_page.exists():
            text = wiki_page.read_text("utf-8")

    # Build a list of all known labels so we can link newly-found concepts
    g = _ensure_db()
    known = {n["node_id"]: n["label"] for n in g.list_nodes()}
    g.close()

    # Simple rule-based extraction
    new_edges = _extract_edges_from_text(text, node_id, label)

    # Try to find co-mentioned known entities (loose matching)
    co_mentioned = {}
    if text:
        for kid, klabel in known.items():
            if kid == node_id:
                continue
            if klabel.lower() in text.lower():
                parts = _extract_edges_from_text(text, node_id, klabel)
                if parts:
                    co_mentioned[kid] = {
                        "label": klabel,
                        "relations": parts,
                    }

    # Persist newly discovered edges to DB (upsert)
    from obgyn_wiki.semantic_graph import SemanticGraph
    g = SemanticGraph(str(SEMANTIC_DB))
    added = []
    for target_id, info in co_mentioned.items():
        for r in info["relations"]:
            edge_id = f"exp_{node_id}_{target_id}_{hash(r['context']) & 0xFFFFFFFF}"
            try:
                g.add_edge(
                    edge_id, node_id, target_id,
                    relation=r["relation"],
                    evidence="2C",
                    source="auto_expansion",
                    extracted_by="rule_expansion"
                )
                added.append(edge_id)
            except ValueError:
                pass  # node missing
    new_count = len(added)
    g.close()

    # Re-export graph if we added edges
    if new_count:
        refresh_graph()

    return {
        "node_id": node_id,
        "edges_extracted": new_count,
        "details": co_mentioned,
        "graph_refreshed": bool(new_count),
    }


# ── Static SPA fallback ──────────────────────────

@app.get("/{catchall:path}")
async def spa_fallback(catchall: str):
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    raise HTTPException(404, detail="index.html not built")


# ── Entrypoint for direct run ──────────────────

if __name__ == "__main__":
    uvicorn.run(
        "obgyn_wiki.api_server:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
    )
