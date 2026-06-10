"""OB/GYN Wiki Orchestrator V2 — Hybrid Query Router.

Routes queries by detected intent:
  - keyword    : simple term lookups (fast, existing behavior)
  - graph      : relational/cross-page questions (uses semantic graph)
  - analytical : evidence aggregation, trend queries (uses DuckDB/Parquet)
  - llm        : complex synthesis (local medical LLM)

Usage:
    from obgyn_wiki.orchestrator_v2 import query_wiki_v2
    result = query_wiki_v2("What conditions share placental dysfunction as a mechanism?")
"""

import re
import os
from pathlib import Path
from typing import Optional

WIKI_ROOT = Path(os.getenv("WIKI_PATH", "/home/leonard/Projects/obgyn-wiki/wiki"))
SEMANTIC_DB = WIKI_ROOT / "semantic.db"

# ── Query classification ──────────────────────────────────────────────

RELATIONAL_KEYWORDS = {
    "what conditions", "which conditions", "what drugs", "which drugs",
    "what treatments", "which treatments",
    "risk factors for", "risk factor for",
    "complications of", "complication of",
    "causes of", "cause of", "caused by",
    "mechanism of", "mechanisms of",
    "associated with", "linked to",
    "drugs for", "medications for",
    "treatments for", "prevention of",
    "symptoms of", "diagnostic criteria for",
    "contraindicated", "interacts with",
    "share", "common", "related to",
    # These two-word phrases should NOT trigger graph on their own:
    # "for", "of", "with" removed — too broad
}

ANALYTICAL_TRIGGERS = {
    "evidence level", "recommendation grade", "recommendation",
    "systematic review", "meta-analysis", "rct",
    "over time", "trends", "distribution",
    "how many", "count of", "number of",
    "total sources", "summary",
}

GRAPH_ALIASES = {
    # conditions (common typos/abbreviations)
    "preeclampsia": "preeclampsia",
    "pre-eclampsia": "preeclampsia",
    "HELLP": "hellp",
    "hellp syndrome": "hellp",
    "gdm": "gestational_diabetes",
    "gestational diabetes": "gestational_diabetes",
    "ptl": "preterm_labor",
    "preterm labor": "preterm_labor",
    "pph": "postpartum_hemorrhage",
    "postpartum haemorrhage": "postpartum_hemorrhage",
    "postpartum hemorrhage": "postpartum_hemorrhage",
    "ectopic": "ectopic_pregnancy",
    "placental abruption": "placental_abruption",
    "abruption": "placental_abruption",
    "chorio": "chorioamnionitis",
    "chorioamionitis": "chorioamnionitis",
    "chorioamnionitis": "chorioamnionitis",
    "fgr": "fetal_growth_restriction",
    "fetal growth restriction": "fetal_growth_restriction",
    "iugr": "fetal_growth_restriction",
    "fetal growth retardation": "fetal_growth_restriction",
    # drugs
    "magnesium sulfate": "magnesium_sulfate",
    "mag sulfate": "magnesium_sulfate",
    "mgso4": "magnesium_sulfate",
    "labetalol": "labetalol",
    "nifedipine": "nifedipine",
    "methyldopa": "methyldopa",
    "aspirin": "low_dose_aspirin",
    "tranexamic acid": "tranexamic_acid",
    "txa": "tranexamic_acid",
    "corticosteroids": "corticosteroids",
    "insulin": "insulin",
    "metformin": "metformin",
    "glyburide": "glyburide",
    "misoprostol": "misoprostol",
    "carboprost": "carboprost",
    "methylergonovine": "methylergonovine",
    "oxytocin": "oxytocin",
    "methotrexate": "methotrexate",
    "rhogam": "rhogam",
    # symptoms
    "hypertension": "hypertension",
    "proteinuria": "proteinuria",
    "edema": "edema",
    "vaginal bleeding": "vaginal_bleeding",
    "abdominal pain": "abdominal_pain",
    "uterine tenderness": "uterine_tenderness",
    "fever": "fever",
    "seizures": "seizures",
    "headache": "headache",
    # mechanisms
    "placental dysfunction": "placental_dysfunction",
    "endothelial dysfunction": "endothelial_dysfunction",
    "angiogenic imbalance": "angiogenic_imbalance",
    "uterine atony": "uterine_atony",
    # risk factors
    "primiparity": "primiparity",
    "advanced maternal age": "advanced_maternal_age",
    "obesity": "obesity",
    "chronic hypertension": "chronic_hypertension",
    "diabetes": "diabetes_mellitus",
    "diabetes mellitus": "diabetes_mellitus",
    "multiple pregnancy": "multiple_pregnancy",
    "smoking": "smoking",
    "previous cesarean": "previous_cesarean",
    "trauma": "trauma",
}


def classify_query(question: str) -> str:
    """Classify query intent: 'graph', 'analytical', or 'keyword'."""
    lower = question.lower()
    for ph in ANALYTICAL_TRIGGERS:
        if ph in lower:
            return "analytical"
    for ph in RELATIONAL_KEYWORDS:
        if ph in lower:
            return "graph"
    return "keyword"


def resolve_node_id(question: str) -> Optional[str]:
    """Try to find which concept node the question is about."""
    lower = question.lower()
    # Try multi-word aliases first (longest match)
    for alias, nid in sorted(GRAPH_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            return nid
    return None


def resolve_target_relation(question: str) -> Optional[str]:
    """Guess the relation type the user is asking about."""
    lower = question.lower()
    for phrase, relation in [
        ("risk factor", "risk_factor_for"),
        ("risk factors", "risk_factor_for"),
        ("cause", "causes"),
        ("causes", "causes"),
        ("treatment", "treats"),
        ("treat", "treats"),
        ("drug", "treats"),
        ("drugs", "treats"),
        ("medication", "treats"),
        ("meds", "treats"),
        ("therapy", "treats"),
        ("mechanism", "mechanism_of"),
        ("diagnose", "diagnoses"),
        ("diagnosis", "diagnoses"),
        ("prevent", "prevents"),
        ("prevention", "prevents"),
        ("symptom", "causes"),         # symptoms are caused BY the condition
        ("symptoms", "causes"),
        ("complication", "causes"),
        ("complications", "causes"),
        ("assess", "assesses"),
        ("monitor", "assesses"),
        ("share", None),                # generic — ask graph for ALL relations
        ("common", None),
        ("related", None),
    ]:
        if phrase in lower:
            return relation
    return None


# ── Graph query engine ────────────────────────────────────────────────

def query_graph(question: str, node_id: Optional[str] = None) -> dict:
    """Answer relational queries using the semantic graph."""
    from obgyn_wiki.semantic_graph import SemanticGraph

    if not SEMANTIC_DB.exists():
        return {
            "mode": "graph",
            "found": False,
            "answer": "Semantic graph not initialized. Run: python -m obgyn_wiki.semantic_graph",
            "structured": None,
        }

    nid = node_id or resolve_node_id(question)
    if not nid:
        return query_keyword(question)  # fall back

    rel = resolve_target_relation(question)

    g = SemanticGraph(str(SEMANTIC_DB))
    try:
        # Get node info
        node = g.get_node(nid)
        if not node:
            return {
                "mode": "graph",
                "found": False,
                "answer": f"Node '{nid}' not found in graph.",
                "structured": None,
            }

        node_label = node[1]
        node_type = node[2]

        # Query forward (what this node does TO others)
        forward = g.query_related(nid, relation=rel)
        # Query backward (what points TO this node)
        backward = g.query_backward(nid, relation=rel)

        # If relation is None (generic query), get all relations
        if rel is None:
            forward = g.query_related(nid)
            backward = g.query_backward(nid)

        # Build structured answer
        lines = [f"📊 **Graph Query Result: {node_label}**\n"]
        lines.append(f"Type: {node_type}")
        lines.append("")

        structured = {
            "node_id": nid,
            "label": node_label,
            "type": node_type,
            "forward": [],
            "backward": [],
        }

        if forward:
            lines.append(f"**{node_label} → affects/relatesto:**")
            for item in forward:
                ev = f" [{item['evidence']}]" if item.get('evidence') else ""
                lines.append(f"  • {item['label']} ({item['type']}) — {item['relation']}{ev}")
                structured["forward"].append(item)
            lines.append("")

        if backward:
            if rel == "risk_factor_for":
                lines.append(f"**Risk factors for {node_label}:**")
            elif rel in ("causes", "mechanism_of"):
                lines.append(f"**Causes / mechanisms of {node_label}:**")
            elif rel == "treats":
                lines.append(f"**Treatments for {node_label}:**")
            elif rel == "prevents":
                lines.append(f"**Preventive measures for {node_label}:**")
            elif rel == "diagnoses":
                lines.append(f"**Diagnostic tools for {node_label}:**")
            else:
                lines.append(f"**Entities related to {node_label}:**")
            for item in backward:
                ev = f" [{item['evidence']}]" if item.get('evidence') else ""
                lines.append(f"  • {item['label']} ({item['type']}) — {item['relation']}{ev}")
                structured["backward"].append(item)
            lines.append("")

        if not forward and not backward:
            lines.append("No graph edges found for this query. The knowledge is still growing.")

        lines.append("\n⚠️ *Graph-based answers reflect compiled edges from wiki pages. Verify with primary sources.*")

        return {
            "mode": "graph",
            "found": True,
            "answer": "\n".join(lines),
            "structured": structured,
        }
    finally:
        g.close()


# ── Analytical queries (Parquet / DuckDB) ────────────────────────────

def query_analytical(question: str) -> dict:
    """Evidence aggregation queries over the Parquet archive and semantic graph."""
    import duckdb

    archive_dir = WIKI_ROOT / "raw_archive"
    con = None
    lower_question = question.lower()

    try:
        # Graph entity counts: answer "How many conditions/drugs/etc. are in the graph?"
        if SEMANTIC_DB.exists() and "graph" in lower_question and any(
            term in lower_question for term in ("how many", "count", "number of")
        ):
            graph_con = duckdb.connect(str(SEMANTIC_DB), read_only=True)
            try:
                rows = graph_con.execute(
                    """
                    SELECT node_type, COUNT(*) AS cnt
                    FROM concept_nodes
                    GROUP BY node_type
                    ORDER BY cnt DESC, node_type
                    """
                ).fetchall()
                edge_count = graph_con.execute("SELECT COUNT(*) FROM concept_edges").fetchone()[0]
            finally:
                graph_con.close()
            structured_counts = [{"node_type": r[0], "count": r[1]} for r in rows]
            lines = ["**Graph node counts:**"]
            for node_type, count in rows:
                lines.append(f"  {node_type}: {count}")
            lines.append(f"\n**Graph edge count:** {edge_count}")
            return {
                "mode": "analytical",
                "found": True,
                "answer": "\n".join(lines),
                "structured": {"graph_node_counts": structured_counts, "graph_edge_count": edge_count},
            }

        # Connect to sources_all.parquet if available
        all_parquet = archive_dir / "sources_all.parquet"
        if not all_parquet.exists():
            return {
                "mode": "analytical",
                "found": False,
                "answer": "Parquet archive not found. Run archive_to_parquet.py first.",
                "structured": None,
            }

        con = duckdb.connect()
        con.execute(f"CREATE OR REPLACE VIEW sources AS SELECT * FROM read_parquet('{all_parquet}')")

        results = []
        structured = {}

        # Evidence level counts
        if any(k in question.lower() for k in ("evidence", "recommendation", "grade", "how many", "count")):
            rows = con.execute("""
                SELECT evidence_level, COUNT(*) as cnt
                FROM sources
                WHERE evidence_level IS NOT NULL
                GROUP BY evidence_level
                ORDER BY cnt DESC
            """).fetchall()
            structured["evidence_levels"] = [{"level": r[0], "count": r[1]} for r in rows]
            results.append("**Evidence level distribution:**")
            for r in rows:
                results.append(f"  {r[0]}: {r[1]}")

        # Topic counts
        if any(k in question.lower() for k in ("topic", "by topic", "per topic")):
            rows = con.execute("""
                SELECT topic, COUNT(*) as cnt
                FROM sources
                WHERE topic IS NOT NULL
                GROUP BY topic
                ORDER BY cnt DESC
            """).fetchall()
            structured["by_topic"] = [{"topic": r[0], "count": r[1]} for r in rows]
            results.append("\n**Sources by topic:**")
            for r in rows[:10]:
                results.append(f"  {r[0] or '(none)'}: {r[1]}")

        # Source type counts
        rows = con.execute("""
            SELECT source_type, COUNT(*) as cnt
            FROM sources
            GROUP BY source_type
            ORDER BY cnt DESC
        """).fetchall()
        structured["by_source_type"] = [{"type": r[0], "count": r[1]} for r in rows]
        results.append("\n**Sources by type:**")
        for r in rows:
            results.append(f"  {r[0]}: {r[1]}")

        con.close()
        return {
            "mode": "analytical",
            "found": bool(results),
            "answer": "\n".join(results) if results else "No analytical query matched.",
            "structured": structured,
        }

    except Exception as e:
        if con:
            con.close()
        return {
            "mode": "analytical",
            "found": False,
            "answer": f"Analytical query failed: {e}",
            "structured": None,
        }


# ── Keyword fallback (original) ──────────────────────────────────────

def _find_pages(question: str) -> list:
    """Keyword search with exact title/slug matches boosted above incidental mentions."""
    keywords = set(re.findall(r'\w+', question.lower()))
    stop = {"what", "is", "the", "a", "an", "for", "in", "of", "and", "or", "to",
            "with", "are", "how", "does", "did", "do", "evidence", "treatment",
            "management", "current", "show", "me", "list", "all", "which", "type"}
    keywords -= stop

    matches = []
    searchable_dirs = [WIKI_ROOT / d for d in ("conditions", "drugs", "procedures", "concepts", "mechanisms")]
    question_slug_text = question.lower().replace(" ", "-")
    for subdir in searchable_dirs:
        if subdir.exists():
            for f in subdir.glob("*.md"):
                raw_text = f.read_text("utf-8")
                text = raw_text.lower()
                score = sum(1 for kw in keywords if kw in text)
                stem_tokens = set(f.stem.lower().replace("-", " ").split())
                if f.stem.lower() in question_slug_text or (stem_tokens and stem_tokens.issubset(keywords)):
                    score += 100
                title_match = re.search(r'^title:\s*["\']?([^"\'\n]+)', raw_text, re.M)
                if title_match and title_match.group(1).lower() in question.lower():
                    score += 100
                if "management" in question.lower() and f.parent.name == "conditions":
                    score += 5
                if score > 0:
                    matches.append((f, score))
    matches.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in matches[:5]]


def _extract_sections(text: str, keywords: set, max_chars: int = 2000) -> str:
    """Extract relevant paragraphs."""
    lines = text.split('\n')
    blocks = []
    current = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                block = '\n'.join(current)
                if any(kw in block.lower() for kw in keywords):
                    blocks.append(block)
                current = []
            continue
        current.append(stripped)
    if current and any(kw in '\n'.join(current).lower() for kw in keywords):
        blocks.append('\n'.join(current))
    result = '\n\n'.join(blocks)
    result = result.replace("```markdown", "")
    result = re.sub(r'^\s*[-*]\s*\[\]\s*$', '', result, flags=re.M)
    result = result.replace("[]", "")
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result[:max_chars]


def query_keyword(question: str) -> dict:
    """Original keyword-based wiki search."""
    keywords = set(re.findall(r'\w+', question.lower()))
    stop = {"what", "is", "the", "a", "an", "for", "in", "of", "and", "or", "to",
            "with", "are", "how", "does", "did", "do", "evidence", "treatment",
            "management", "current", "show", "me", "list", "all", "which", "type"}
    query_kw = keywords - stop

    relevant = _find_pages(question)
    context = []
    sources = []

    for page in relevant:
        text = page.read_text("utf-8").replace("```markdown", "")
        body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL)
        excerpt = _extract_sections(body, query_kw, max_chars=3000)
        if excerpt.strip():
            context.append(f"--- FROM: {page.stem} ---\n{excerpt}")
        sources.append(f"{page.stem}.md")

    if not context:
        return {
            "mode": "keyword",
            "found": False,
            "answer": "No relevant wiki pages found for this query.",
            "sources": [],
            "structured": None,
        }

    answer_parts = [
        f"📚 **Evidence-Based Answer**\n",
        f"Question: *{question}*\n",
        f"Relevant pages: {', '.join(sources)}\n",
        "---",
    ]
    for ctx in context:
        answer_parts.append(ctx)
        answer_parts.append("---")
    answer_parts.append("\n⚠️ This is a literature summary, not patient-specific advice.")

    return {
        "mode": "keyword",
        "found": True,
        "answer": "\n".join(answer_parts),
        "sources": sources,
        "structured": {"sources": sources, "excerpts": context},
    }


# ── Unified query entrypoint ──────────────────────────────────────────

def query_wiki_v2(question: str, mode: str = "auto", use_llm: bool = False) -> dict:
    """Unified query router.  mode='auto' detects intent; use_llm adds synthesis."""
    if mode == "auto":
        mode = classify_query(question)

    if mode == "graph":
        result = query_graph(question)
    elif mode == "analytical":
        result = query_analytical(question)
    else:
        result = query_keyword(question)

    # Optionally enhance with LLM synthesis
    if use_llm and result.get("structured"):
        try:
            from obgyn_wiki.local_llm import call_local_llm
            structured_text = str(result["structured"])[:4000]
            prompt = (
                f"You are an OB/GYN specialist assistant. The user asks: '{question}'\n\n"
                f"Structured data retrieved:\n{structured_text}\n\n"
                "Synthesize a concise, evidence-based answer. Never make up statistics. "
                "If evidence is limited, state limitations clearly."
            )
            llm_result = call_local_llm(prompt, model="medgemma-27b", expect_json=False,
                                        temperature=0.1, max_tokens=1024)
            result["llm_answer"] = llm_result.get("content", "")
            result["llm_tokens"] = llm_result.get("eval_count")
        except Exception as e:
            result["llm_answer"] = f"LLM synthesis failed: {e}"
            result["llm_tokens"] = None

    return result
