"""scripts/build_static.py — Export a GitHub Pages deployable from the live graph.

Usage:
    cd /home/leonard/Projects/obgyn-wiki
    python3 scripts/build_static.py        # creates web/dist/ ready to push

Then: cd web/dist && git init && git add . && git commit -m "static" && gh pages push
Or:  copy contents to your repo's gh-pages branch.
"""

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
SEMANTIC_DB = WIKI_ROOT / "semantic.db"
WEB_DIR = Path(__file__).parent.parent / "web"
DIST_DIR = WEB_DIR / "dist"


def export_graph_json(out_path: Path):
    from obgyn_wiki.semantic_graph import SemanticGraph
    g = SemanticGraph(str(SEMANTIC_DB))
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
        "nodes": [
            {
                "id": n["node_id"],
                "label": n["label"],
                "group": n["node_type"],
                "canonical": n["canonical"],
                "page": n["page_path"],
                "mesh": n["mesh_id"],
            }
            for n in nodes
        ],
        "edges": edge_data,
    }
    out_path.write_text(json.dumps(payload, indent=2), "utf-8")
    return len(nodes), len(edge_data)


def build():
    if not SEMANTIC_DB.exists():
        print(f"ERROR: DB not found: {SEMANTIC_DB}")
        sys.exit(1)

    # Clean + create dist
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    # 1. Export graph data
    graph_json = DIST_DIR / "graph_data.json"
    node_count, edge_count = export_graph_json(graph_json)
    print(f"Exported {node_count} nodes, {edge_count} edges → {graph_json}")

    # 2. Copy vis-network library
    src_vis = WEB_DIR / "vis-network.min.js"
    if not src_vis.exists():
        print(f"ERROR: vis-network.min.js missing at {src_vis}")
        sys.exit(1)
    dst_vis = DIST_DIR / "vis-network.min.js"
    shutil.copy2(src_vis, dst_vis)
    print(f"Copied library → {dst_vis}")

    # 3. Build static index.html (API-free)
    src_html = WEB_DIR / "index.html"
    html = src_html.read_text("utf-8")

    # Strip FastAPI asset paths — make everything relative and flat
    html = html.replace('src="assets/vis-network.min.js"', 'src="vis-network.min.js"')

    # Inject a flag that disables API calls (force static mode)
    # Place it right after the opening body tag
    flag_script = "<script>window._STATIC_MODE=true;</script>\n"
    html = html.replace("<body>", "<body>\n" + flag_script)

    # Patch detectApiUrl() to return "" when in static mode
    old_detect = """function detectApiUrl() {
    if (location.protocol === 'file:') {
        return 'http://localhost:8765';
    }
    return '';
}"""
    new_detect = """function detectApiUrl() {
    if (window._STATIC_MODE || location.protocol === 'file:') {
        return '';
    }
    return '';
}"""
    html = html.replace(old_detect, new_detect)

    # Also clean up the SPA fallback path that references /{catchall:path}
    dist_html = DIST_DIR / "index.html"
    dist_html.write_text(html, "utf-8")
    print(f"Wrote static SPA → {dist_html}")

    # 4. Optional CNAME
    cname = (WEB_DIR / "CNAME")
    if cname.exists():
        shutil.copy2(cname, DIST_DIR / "CNAME")

    # 5. Summary
    print(f"\nBuild complete: {DIST_DIR}")
    print(f"  Files: {len(list(DIST_DIR.iterdir()))}")
    print(f"\nDeploy to GitHub Pages:")
    print(f"  cd {DIST_DIR}")
    print(f"  git init && git add . && git commit -m 'deploy'")
    print(f"  git branch -M main && git remote add origin <repo-url>")
    print(f"  git push origin main:gh-pages --force")


if __name__ == "__main__":
    build()
