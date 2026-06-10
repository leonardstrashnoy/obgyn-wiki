"""obgyn_wiki/auto_expand.py — Semantic graph auto-expansion engine V2.

Phase 4+: Detects thin nodes and proposes edges using:
  1. Section heading keyword matching on condition pages
  2. Full-body text co-occurrence mining
  3. Manual clinical relationship mapping as fallback

No LLM required — deterministic, auditable, and fast.
"""

import re
import sys
import json
from pathlib import Path
from typing import List, Optional, Set
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from obgyn_wiki.semantic_graph import SemanticGraph

WIKI_ROOT = Path("/home/leonard/Projects/obgyn-wiki/wiki")
SEMANTIC_DB = WIKI_ROOT / "semantic.db"


# ── 1. THIN NODE DETECTION ────────────────────────────────────────────────

def detect_thin_nodes(min_degree: int = 2) -> List[dict]:
    """Find nodes with fewer than min_degree connections."""
    with SemanticGraph(SEMANTIC_DB) as g:
        nodes = g.list_nodes()
        edges = g.list_edges()
    degree = Counter()
    for e in edges:
        degree[e["from_node"]] += 1
        degree[e["to_node"]] += 1
    thin = []
    for n in nodes:
        d = degree.get(n["node_id"], 0)
        if d < min_degree:
            thin.append({
                "node_id": n["node_id"], "label": n["label"],
                "type": n["node_type"], "degree": d,
            })
    return sorted(thin, key=lambda x: x["degree"])


# ── 2. RELATION KEYWORD MAP (expanded for real page headings) ─────────────

SECTION_RELATION_MAP = {
    # Management / treatment
    "management": "treats",
    "treatment": "treats",
    "therapy": "treats",
    "evidence-based management": "treats",
    "medical interventions": "treats",
    "antepartum management": "treats",
    "postpartum": "treats",
    "delivery timing": "treats",
    # Diagnosis
    "diagnosis": "diagnoses",
    "diagnostic": "diagnoses",
    "evaluation": "diagnoses",
    "screening": "diagnoses",
    "ultrasound": "diagnoses",
    "ultrasound diagnosis": "diagnoses",
    "ultrasound evaluation": "diagnoses",
    "differential diagnosis": "diagnoses",
    "laboratory confirmation": "diagnoses",
    "diagnostic criteria": "diagnoses",
    # Clinical features / symptoms / complications
    "clinical features": "causes",
    "signs and symptoms": "causes",
    "manifestations": "causes",
    "complications": "causes",
    "complications and prognosis": "causes",
    "maternal signs": "causes",
    "fetal signs": "causes",
    # Pathophysiology / mechanisms
    "pathophysiology": "mechanism_of",
    "pathophysiology summary": "mechanism_of",
    "mechanism": "mechanism_of",
    "inflammatory cascade": "mechanism_of",
    "fetal inflammatory response": "mechanism_of",
    # Risk factors / etiology
    "risk factor": "risk_factor_for",
    "risk factors": "risk_factor_for",
    "etiology": "risk_factor_for",
    "etiology and risk factors": "risk_factor_for",
    "predisposing": "risk_factor_for",
    "major risk factors": "risk_factor_for",
    "maternal factors": "risk_factor_for",
    "fetal/placental factors": "risk_factor_for",
    # Prevention
    "prevention": "prevents",
    "prophylaxis": "prevents",
    # Surveillance / monitoring
    "surveillance": "assesses",
    "monitoring": "assesses",
    "doppler studies": "assesses",
    "timing of delivery": "assesses",
}


# ── 3. MANUAL CLINICAL EDGE MAPPING (fallback) ───────────────────────────
# Known relationships that won't be caught by text mining
# Format: (from_node, to_node, relation, evidence, source)

MANUAL_EDGES = [
    # ── Drugs → Conditions ──
    ("carboprost", "postpartum_hemorrhage", "treats", "1A", "ACOG PPH guideline"),
    ("misoprostol", "postpartum_hemorrhage", "treats", "1A", "ACOG PPH guideline"),
    ("methylergonovine", "postpartum_hemorrhage", "treats", "1A", "ACOG PPH guideline"),
    ("oxytocin", "postpartum_hemorrhage", "treats", "1A", "ACOG PPH guideline"),
    ("tranexamic_acid", "postpartum_hemorrhage", "treats", "1A", "WOMAN trial"),
    ("labetalol", "preeclampsia", "treats", "1B", "ACOG hypertension guideline"),
    ("nifedipine", "preeclampsia", "treats", "1B", "ACOG hypertension guideline"),
    ("methyldopa", "preeclampsia", "treats", "1B", "ACOG hypertension guideline"),
    ("magnesium_sulfate", "preeclampsia", "treats", "1A", "MAGPIE trial / ACOG"),
    ("magnesium_sulfate", "eclampsia", "prevents", "1A", "MAGPIE trial"),
    ("insulin", "gestational_diabetes", "treats", "1A", "ACOG GDM guideline"),
    ("metformin", "gestational_diabetes", "treats", "2B", "ACOG GDM guideline"),
    ("glyburide", "gestational_diabetes", "treats", "2B", "ACOG GDM guideline"),
    ("methotrexate", "ectopic_pregnancy", "treats", "1A", "ACOG ectopic guideline"),
    ("rhogam", "ectopic_pregnancy", "prevents", "1A", "ACOG Rh sensitization"),
    ("corticosteroids", "preterm_labor", "treats", "1A", "ACOG / NIH consensus"),
    ("low_dose_aspirin", "preeclampsia", "prevents", "1A", "ASPRE trial / ACOG"),
    # ── Symptoms → Conditions ──
    ("preeclampsia", "proteinuria", "causes", "1A", "ACOG"),
    ("preeclampsia", "hypertension", "causes", "1A", "ACOG"),
    ("preeclampsia", "edema", "causes", "2B", "ACOG"),
    ("preeclampsia", "headache", "causes", "2B", "ACOG"),
    ("preeclampsia", "visual_changes", "causes", "2B", "ACOG"),
    ("preeclampsia", "seizures", "causes", "1A", "ACOG"),
    ("preeclampsia", "thrombocytopenia", "causes", "1A", "ACOG HELLP"),
    ("preeclampsia", "elevated_liver_enzymes", "causes", "1A", "ACOG HELLP"),
    ("preeclampsia", "pulmonary_edema", "causes", "2B", "ACOG"),
    ("placental_abruption", "vaginal_bleeding", "causes", "1A", "ACOG"),
    ("placental_abruption", "uterine_tenderness", "causes", "1A", "ACOG"),
    ("placental_abruption", "fetal_distress", "causes", "1A", "ACOG"),
    ("chorioamnionitis", "fever", "causes", "1A", "ACOG"),
    ("postpartum_hemorrhage", "coagulopathy", "causes", "1A", "ACOG"),
    ("postpartum_hemorrhage", "hemorrhage", "causes", "1A", "ACOG"),
    ("gestational_diabetes", "macrosomia", "causes", "1A", "ACOG"),
    ("ectopic_pregnancy", "abdominal_pain", "causes", "1A", "ACOG"),
    ("ectopic_pregnancy", "vaginal_bleeding", "causes", "1A", "ACOG"),
    ("ectopic_pregnancy", "rupture", "causes", "1A", "ACOG"),
    ("amniotic_fluid", "oligohydramnios", "causes", "1A", "ACOG"),
    ("amniotic_fluid", "polyhydramnios", "causes", "1A", "ACOG"),
    ("preterm_labor", "preterm_labor", "causes", "1A", "ACOG"),  # self-link skip later
    # ── Mechanisms → Conditions ──
    ("preeclampsia", "endothelial_dysfunction", "mechanism_of", "2A", "Literature"),
    ("preeclampsia", "placental_dysfunction", "mechanism_of", "2A", "Literature"),
    ("preeclampsia", "angiogenic_imbalance", "mechanism_of", "2A", "Literature"),
    ("preeclampsia", "trophoblast_invasion", "mechanism_of", "2A", "Literature"),
    ("preeclampsia", "spiral_artery_remodeling", "mechanism_of", "2A", "Literature"),
    ("placental_abruption", "placental_dysfunction", "mechanism_of", "2B", "Literature"),
    ("postpartum_hemorrhage", "uterine_atony", "mechanism_of", "1A", "ACOG"),
    ("postpartum_hemorrhage", "coagulopathy_mechanism", "mechanism_of", "1A", "ACOG"),
    ("fetal_growth_restriction", "placental_dysfunction", "mechanism_of", "1A", "ACOG"),
    # ── Risk factors → Conditions ──
    ("chronic_hypertension", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("gestational_diabetes", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("obesity", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("multiple_pregnancy", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("advanced_maternal_age", "preeclampsia", "risk_factor_for", "2B", "ACOG"),
    ("primiparity", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("history_preeclampsia", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("smoking", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("cocaine_use", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("trauma", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("previous_cesarean", "placental_abruption", "risk_factor_for", "2B", "ACOG"),
    ("placental_previa", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("multiple_pregnancy", "preterm_labor", "risk_factor_for", "1A", "ACOG"),
    ("cervical_incompetence", "preterm_labor", "risk_factor_for", "1A", "ACOG"),
    ("low_papp_a", "fetal_growth_restriction", "risk_factor_for", "2B", "Literature"),
    ("obesity", "gestational_diabetes", "risk_factor_for", "1A", "ACOG"),
    ("advanced_maternal_age", "gestational_diabetes", "risk_factor_for", "1A", "ACOG"),
    ("diabetes_mellitus", "gestational_diabetes", "risk_factor_for", "1A", "ACOG"),
    # ── Procedures → Conditions ──
    ("cesarean_delivery", "postpartum_hemorrhage", "risk_factor_for", "1A", "ACOG"),
    ("cesarean_delivery", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("hysterectomy", "postpartum_hemorrhage", "treats", "1B", "ACOG PPH refractory"),
    ("arterial_embolization", "postpartum_hemorrhage", "treats", "2B", "ACOG"),
    ("laceration_repair", "postpartum_hemorrhage", "treats", "1A", "ACOG"),
    ("cervical_cerclage", "preterm_labor", "prevents", "1A", "ACOG"),
    ("cervical_length", "preterm_labor", "diagnoses", "1A", "ACOG"),
    ("fetal_fibronectin", "preterm_labor", "diagnoses", "1B", "ACOG"),
    ("nonstress_test", "fetal_surveillance", "assesses", "1A", "ACOG"),
    ("biophysical_profile", "fetal_surveillance", "assesses", "1A", "ACOG"),
    ("doppler_uta", "fetal_growth_restriction", "diagnoses", "1A", "ACOG"),
    ("ultrasound_tv", "ectopic_pregnancy", "diagnoses", "1A", "ACOG"),
    ("dilation_curettage", "ectopic_pregnancy", "treats", "1A", "ACOG"),
    ("surgical_management", "ectopic_pregnancy", "treats", "1A", "ACOG"),
    ("ultrasound_abd", "placental_abruption", "diagnoses", "1B", "ACOG"),
    # ── Conditions → Conditions ──
    ("preeclampsia", "placental_abruption", "risk_factor_for", "1A", "ACOG"),
    ("preeclampsia", "fetal_growth_restriction", "risk_factor_for", "1A", "ACOG"),
    ("preeclampsia", "eclampsia", "risk_factor_for", "1A", "ACOG"),
    ("preeclampsia", "hellp", "causes", "1A", "ACOG"),
    ("gestational_diabetes", "preeclampsia", "risk_factor_for", "1A", "ACOG"),
    ("gestational_diabetes", "fetal_growth_restriction", "risk_factor_for", "2B", "ACOG"),
    ("gestational_diabetes", "macrosomia", "causes", "1A", "ACOG"),
    ("preterm_labor", "chorioamnionitis", "risk_factor_for", "1A", "ACOG"),
    ("preterm_labor", "premature_rupture_of_membranes", "causes", "1A", "ACOG"),
    ("placental_abruption", "fetal_growth_restriction", "causes", "1A", "ACOG"),
    ("fetal_growth_restriction", "fetal_anomalies", "risk_factor_for", "2B", "ACOG"),
    ("postpartum_hemorrhage", "iron_deficiency", "causes", "1A", "ACOG"),

    # ── Additional from newly ingested guidelines (PB 222, 183, NG25, 228) ──
    ("betamethasone", "preterm_labor", "prevents", "1A", "NICE NG25"),
    ("magnesium_sulfate", "preterm_labor", "neuroprotection", "1A", "NICE NG25"),
    ("doppler_ultrasound", "fetal_growth_restriction", "assesses", "1A", "ACOG PB 228"),
    ("magnesium_sulfate", "eclampsia", "prevents", "1A", "ACOG PB 222"),

]


# ── 4. SECTION EXTRACTION ──────────────────────────────────────────────────

def _extract_sections(text: str) -> List[tuple]:
    """Split markdown into (heading, body) sections."""
    sections = []
    current_heading = "Introduction"
    current_body = []
    for line in text.split("\n"):
        h_match = re.match(r"^(#{2,4})\s+(.+)$", line)
        if h_match:
            sections.append((current_heading, "\n".join(current_body)))
            current_heading = h_match.group(2).strip().lower()
            current_body = []
        else:
            current_body.append(line)
    sections.append((current_heading, "\n".join(current_body)))
    return sections


def _node_in_text(node_id: str, label: str, text: str) -> bool:
    """Check if a node's label or id appears in text (case-insensitive, whole-word aware)."""
    text_lower = text.lower()
    if label.lower() in text_lower:
        return True
    if node_id.replace("_", " ").lower() in text_lower:
        return True
    # Common abbreviations
    abbrevs = {
        "gdm": "gestational_diabetes",
        "pph": "postpartum_hemorrhage",
        "ptl": "preterm_labor",
        "fgr": "fetal_growth_restriction",
        "iugr": "fetal_growth_restriction",
        "hellp": "hellp",
        "txa": "tranexamic_acid",
        "mgso4": "magnesium_sulfate",
    }
    for abbrev, mapped in abbrevs.items():
        if mapped == node_id and re.search(rf"\b{abbrev}\b", text_lower):
            return True
    return False


# ── 5. TEXT-BASED EDGE MINING ──────────────────────────────────────────────

def _infer_relation_from_heading(heading: str) -> Optional[str]:
    """Map a section heading to a relation type."""
    for keyword, rel in SECTION_RELATION_MAP.items():
        if keyword in heading:
            return rel
    return None


def _infer_direction(node_id: str, ntype: str, relation: str, cond_id: str) -> Optional[tuple]:
    """Determine edge direction based on node type and relation."""
    if ntype in ("drug", "procedure") and relation in ("treats", "diagnoses", "prevents", "assesses"):
        return (node_id, cond_id)
    elif ntype in ("symptom", "mechanism") and relation in ("causes", "mechanism_of"):
        return (cond_id, node_id)
    elif ntype == "risk_factor" and relation == "risk_factor_for":
        return (node_id, cond_id)
    elif ntype == "condition" and relation in ("risk_factor_for", "causes"):
        return (node_id, cond_id)
    return None


# Page slug → canonical condition node_id
SLUG_MAP = {
    "preeclampsia": "preeclampsia",
    "gestational-diabetes": "gestational_diabetes",
    "preterm-labor": "preterm_labor",
    "postpartum-hemorrhage": "postpartum_hemorrhage",
    "ectopic-pregnancy": "ectopic_pregnancy",
    "placental-abruption": "placental_abruption",
    "amniotic-fluid": "amniotic_fluid",
    "fetal-surveillance": "fetal_surveillance",
    "fetal-growth-restriction": "fetal_growth_restriction",
    "chorioamnionitis": "chorioamnionitis",
    "eclampsia": "eclampsia",
    "hellp": "hellp",
    "premature-rupture-of-membranes": "premature_rupture_of_membranes",
}


def mine_edges_from_pages(batch_size: int = 50, min_degree: int = 2, dry_run: bool = True) -> dict:
    """Read condition pages, detect thin nodes in context, propose edges."""
    thin_nodes = detect_thin_nodes(min_degree=min_degree)
    if not thin_nodes:
        return {"status": "no_gaps", "message": "All nodes well-connected"}

    with SemanticGraph(SEMANTIC_DB) as g:
        node_cache = {n["node_id"]: n for n in g.list_nodes()}
        existing_edges = set()
        for e in g.list_edges():
            existing_edges.add((e["from_node"], e["to_node"], e["relation"]))

    conditions_dir = WIKI_ROOT / "conditions"
    proposals = []
    added = 0

    for node_info in thin_nodes[:batch_size]:
        nid = node_info["node_id"]
        ntype = node_info["type"]
        label = node_info["label"]

        # Skip if node doesn't exist in cache (shouldn't happen)
        if nid not in node_cache:
            continue

        # Scan each condition page for mentions
        for page in conditions_dir.glob("*.md"):
            text = page.read_text("utf-8")
            body = re.sub(r"^---\n.*?---\n", "", text, flags=re.DOTALL, count=1)

            if not _node_in_text(nid, label, body):
                continue

            # Determine which section the node appears in
            sections = _extract_sections(body)
            found_relation = None
            found_heading = None
            for heading, section_text in sections:
                if not _node_in_text(nid, label, section_text):
                    continue
                rel = _infer_relation_from_heading(heading)
                if rel:
                    found_relation = rel
                    found_heading = heading
                    break

            # If no section relation found, try body-level inference
            if not found_relation:
                # Fallback: check page slug for known condition relationships
                slug = page.stem
                cond_id = SLUG_MAP.get(slug)
                if not cond_id:
                    continue
                # Try generic co-occurrence — add a "related_to" edge
                found_relation = "related_to"
                found_heading = "body_cooccurrence"

            slug = page.stem
            cond_id = SLUG_MAP.get(slug)
            if not cond_id:
                continue

            direction = _infer_direction(nid, ntype, found_relation, cond_id)
            if not direction and found_relation == "related_to":
                # For generic edges: drug/procedure → condition; condition ← symptom
                if ntype in ("drug", "procedure", "risk_factor"):
                    direction = (nid, cond_id)
                elif ntype in ("symptom", "mechanism"):
                    direction = (cond_id, nid)
                else:
                    direction = (nid, cond_id)

            if not direction:
                continue

            from_n, to_n = direction
            if from_n == to_n:
                continue

            if (from_n, to_n, found_relation) in existing_edges:
                continue

            edge_proposal = {
                "from": from_n,
                "to": to_n,
                "relation": found_relation,
                "evidence": "2B",
                "source": f"conditions/{page.name}",
                "section": found_heading,
                "extracted_by": "rule_mining",
            }

            if dry_run:
                proposals.append(edge_proposal)
            else:
                g = SemanticGraph(SEMANTIC_DB)
                edge_id = f"rule_{from_n}_{to_n}_{found_relation}"
                try:
                    g.add_edge(edge_id, from_n, to_n, found_relation, evidence="2B",
                               source=f"conditions/{page.name}", extracted_by="rule_mining")
                    added += 1
                    existing_edges.add((from_n, to_n, found_relation))
                except ValueError:
                    pass
                g.close()

    return {
        "status": "dry_run" if dry_run else "expanded",
        "thin_nodes_found": len(thin_nodes),
        "processed": batch_size,
        "proposals": len(proposals),
        "edges_added": added,
        "details": proposals[:50] if dry_run else [],
    }


# ── 6. MANUAL EDGE INJECTION ─────────────────────────────────────────────

def inject_manual_edges(dry_run: bool = True) -> dict:
    """Inject predefined clinical edges into the graph."""
    with SemanticGraph(SEMANTIC_DB) as g:
        existing_edges = set()
        for e in g.list_edges():
            existing_edges.add((e["from_node"], e["to_node"], e["relation"]))
        node_ids = {n["node_id"] for n in g.list_nodes()}

    added = 0
    skipped = 0
    missing_nodes = set()
    proposals = []

    for from_n, to_n, relation, evidence, source in MANUAL_EDGES:
        if from_n not in node_ids:
            missing_nodes.add(from_n)
            skipped += 1
            continue
        if to_n not in node_ids:
            missing_nodes.add(to_n)
            skipped += 1
            continue
        if from_n == to_n:
            skipped += 1
            continue
        if (from_n, to_n, relation) in existing_edges:
            skipped += 1
            continue

        edge_id = f"manual_{from_n}_{to_n}_{relation}"
        proposal = {
            "from": from_n,
            "to": to_n,
            "relation": relation,
            "evidence": evidence,
            "source": source,
            "extracted_by": "manual_mapping",
        }

        if dry_run:
            proposals.append(proposal)
        else:
            g = SemanticGraph(SEMANTIC_DB)
            try:
                g.add_edge(edge_id, from_n, to_n, relation, evidence=evidence,
                           source=source, extracted_by="manual_mapping")
                added += 1
                existing_edges.add((from_n, to_n, relation))
            except ValueError as e:
                print(f"  [WARN] Could not add edge {edge_id}: {e}")
                skipped += 1
            g.close()

    return {
        "status": "dry_run" if dry_run else "injected",
        "proposals": len(proposals),
        "edges_added": added,
        "skipped": skipped,
        "missing_nodes": sorted(missing_nodes),
        "details": proposals[:50] if dry_run else [],
    }


# ── 7. COMBINED EXPANSION ─────────────────────────────────────────────────

def expand_all(dry_run: bool = True, min_degree: int = 2) -> dict:
    """Run text mining + manual injection, return summary."""
    text_result = mine_edges_from_pages(batch_size=50, min_degree=min_degree, dry_run=dry_run)
    manual_result = inject_manual_edges(dry_run=dry_run)

    return {
        "status": "dry_run" if dry_run else "committed",
        "text_mining": text_result,
        "manual": manual_result,
        "total_proposals": text_result["proposals"] + manual_result["proposals"],
        "total_edges_added": text_result["edges_added"] + manual_result["edges_added"],
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="OB/GYN Wiki semantic graph auto-expansion")
    parser.add_argument("--commit", action="store_true", help="Actually add edges")
    parser.add_argument("--batch", type=int, default=50, help="Max thin nodes to scan")
    parser.add_argument("--min-degree", type=int, default=2, help="Min connections")
    parser.add_argument("--manual-only", action="store_true", help="Only inject manual edges")
    parser.add_argument("--text-only", action="store_true", help="Only run text mining")
    args = parser.parse_args()

    if args.manual_only:
        result = inject_manual_edges(dry_run=not args.commit)
    elif args.text_only:
        result = mine_edges_from_pages(batch_size=args.batch, min_degree=args.min_degree,
                                        dry_run=not args.commit)
    else:
        result = expand_all(dry_run=not args.commit, min_degree=args.min_degree)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
