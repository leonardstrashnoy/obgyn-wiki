from pathlib import Path

from obgyn_wiki.orchestrator_v2 import classify_query, query_wiki_v2

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"


def test_lint_reports_structured_counts():
    from obgyn_wiki.wiki_lint import run_lint

    report = run_lint(WIKI, fail_on_warnings=False)
    assert "counts" in report
    assert "issues" in report
    assert "broken_wikilinks" in report["counts"]
    assert isinstance(report["ok"], bool)


def test_reconcile_has_made_real_pages_canonical():
    import duckdb

    con = duckdb.connect(str(WIKI / "semantic.db"), read_only=True)
    try:
        row = con.execute(
            "select canonical, page_path from concept_nodes where node_id='magnesium_sulfate'"
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row[0] is True
    assert row[1] == "drugs/magnesium-sulfate.md"


def test_graph_exports_are_synced():
    import json

    paths = [WIKI / "graph_data.json", ROOT / "web" / "graph_data.json", ROOT / "web" / "dist" / "graph_data.json"]
    payloads = [json.loads(p.read_text()) for p in paths]
    counts = {(len(p["nodes"]), len(p["edges"])) for p in payloads}
    assert len(counts) == 1


def test_count_query_routes_to_graph_entity_counts():
    result = query_wiki_v2("How many conditions are in the graph?")
    assert result["mode"] == "analytical"
    assert result["structured"].get("graph_node_counts")
    assert "condition" in result["answer"].lower()


def test_management_query_prefers_exact_condition_page():
    result = query_wiki_v2("What is postpartum hemorrhage management?")
    assert result["found"] is True
    assert result["sources"][0] == "postpartum-hemorrhage.md"
    assert "```markdown" not in result["answer"]
    assert "[]" not in result["answer"]


def test_high_priority_coverage_matrix_exists():
    path = WIKI / "coverage-matrix.md"
    text = path.read_text()
    assert "Benign gynecology" in text
    assert "Gynecologic oncology" in text


def test_auto_classifier_still_sends_risk_factor_questions_to_graph():
    assert classify_query("Risk factors for preeclampsia") == "graph"
