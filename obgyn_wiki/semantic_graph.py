"""obgyn_wiki/semantic_graph.py — DuckDB-backed concept graph CRUD and queries.
"""

import duckdb
import re
from pathlib import Path
from typing import Optional, List

class SemanticGraph:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.con = duckdb.connect(str(self.db_path))
        self._ensure_schema()

    def _ensure_schema(self):
        """Create tables if they don't exist."""
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS concept_nodes (
                node_id     VARCHAR PRIMARY KEY,
                label       VARCHAR NOT NULL,
                node_type   VARCHAR NOT NULL,
                canonical   BOOLEAN DEFAULT FALSE,
                page_path   VARCHAR,
                mesh_id     VARCHAR
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS concept_edges (
                edge_id      VARCHAR PRIMARY KEY,
                from_node    VARCHAR NOT NULL,
                to_node      VARCHAR NOT NULL,
                relation     VARCHAR NOT NULL,
                evidence     VARCHAR,
                source       VARCHAR,
                weight       FLOAT DEFAULT 1.0,
                extracted_by VARCHAR DEFAULT 'manual',
                CHECK(from_node != to_node)
            )
        """)
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS edge_indices (
                idx_name VARCHAR PRIMARY KEY,
                from_node VARCHAR,
                to_node VARCHAR
            )
        """)
        self.con.close()
        self.con = duckdb.connect(str(self.db_path))

    def add_node(self, node_id: str, label: str, node_type: str,
                 canonical: bool = False, page_path: str = None, mesh_id: str = None):
        self.con.execute("""
            INSERT OR REPLACE INTO concept_nodes (node_id, label, node_type, canonical, page_path, mesh_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (node_id, label, node_type, canonical, page_path, mesh_id))

    def add_edge(self, edge_id: str, from_node: str, to_node: str, relation: str,
                 evidence: str = None, source: str = None, weight: float = 1.0,
                 extracted_by: str = 'manual'):
        # Verify nodes exist
        fn = self.con.execute("SELECT 1 FROM concept_nodes WHERE node_id=?", (from_node,)).fetchone()
        tn = self.con.execute("SELECT 1 FROM concept_nodes WHERE node_id=?", (to_node,)).fetchone()
        if not fn or not tn:
            raise ValueError(f"Missing node(s): {from_node} or {to_node}")
        self.con.execute("""
            INSERT OR REPLACE INTO concept_edges (edge_id, from_node, to_node, relation, evidence, source, weight, extracted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (edge_id, from_node, to_node, relation, evidence, source, weight, extracted_by))

    def get_node(self, node_id: str):
        return self.con.execute("SELECT * FROM concept_nodes WHERE node_id=?", (node_id,)).fetchone()

    def query_related(self, node_id: str, relation: Optional[str] = None, depth: int = 1) -> List[dict]:
        """Find nodes related to given node."""
        if relation:
            rows = self.con.execute("""
                SELECT e.to_node, n.label, n.node_type, e.relation, e.evidence, e.weight
                FROM concept_edges e
                JOIN concept_nodes n ON e.to_node = n.node_id
                WHERE e.from_node = ? AND e.relation = ?
            """, (node_id, relation)).fetchall()
        else:
            rows = self.con.execute("""
                SELECT e.to_node, n.label, n.node_type, e.relation, e.evidence, e.weight
                FROM concept_edges e
                JOIN concept_nodes n ON e.to_node = n.node_id
                WHERE e.from_node = ?
            """, (node_id,)).fetchall()
        return [
            {"node_id": r[0], "label": r[1], "type": r[2], "relation": r[3], "evidence": r[4], "weight": r[5]}
            for r in rows
        ]

    def query_backward(self, node_id: str, relation: Optional[str] = None) -> List[dict]:
        """Find what points TO this node."""
        if relation:
            rows = self.con.execute("""
                SELECT e.from_node, n.label, n.node_type, e.relation, e.evidence
                FROM concept_edges e
                JOIN concept_nodes n ON e.from_node = n.node_id
                WHERE e.to_node = ? AND e.relation = ?
            """, (node_id, relation)).fetchall()
        else:
            rows = self.con.execute("""
                SELECT e.from_node, n.label, n.node_type, e.relation, e.evidence
                FROM concept_edges e
                JOIN concept_nodes n ON e.from_node = n.node_id
                WHERE e.to_node = ?
            """, (node_id,)).fetchall()
        return [
            {"node_id": r[0], "label": r[1], "type": r[2], "relation": r[3], "evidence": r[4]}
            for r in rows
        ]

    def list_nodes(self, node_type: Optional[str] = None) -> List[dict]:
        if node_type:
            rows = self.con.execute("SELECT * FROM concept_nodes WHERE node_type=? ORDER BY label", (node_type,)).fetchall()
        else:
            rows = self.con.execute("SELECT * FROM concept_nodes ORDER BY label").fetchall()
        return [dict(zip(["node_id","label","node_type","canonical","page_path","mesh_id"], r)) for r in rows]

    def list_edges(self, relation: Optional[str] = None) -> List[dict]:
        if relation:
            rows = self.con.execute("SELECT * FROM concept_edges WHERE relation=? ORDER BY from_node", (relation,)).fetchall()
        else:
            rows = self.con.execute("SELECT * FROM concept_edges ORDER BY from_node").fetchall()
        return [dict(zip(["edge_id","from_node","to_node","relation","evidence","source","weight","extracted_by"], r)) for r in rows]

    def count(self) -> dict:
        nodes = self.con.execute("SELECT COUNT(*) FROM concept_nodes").fetchone()[0]
        edges = self.con.execute("SELECT COUNT(*) FROM concept_edges").fetchone()[0]
        return {"nodes": nodes, "edges": edges}

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Manual core seed data for OB/GYN conditions
CORE_CONDITIONS = [
    ("preeclampsia", "Preeclampsia", "conditions/preeclampsia.md", "D011236"),
    ("gestational_diabetes", "Gestational Diabetes", "conditions/gestational-diabetes.md", "D016640"),
    ("preterm_labor", "Preterm Labor", "conditions/preterm-labor.md", "D007751"),
    ("postpartum_hemorrhage", "Postpartum Hemorrhage", "conditions/postpartum-hemorrhage.md", "D011248"),
    ("ectopic_pregnancy", "Ectopic Pregnancy", "conditions/ectopic-pregnancy.md", "D011248"),
    ("placental_abruption", "Placental Abruption", "conditions/placental-abruption.md", "D000073605"),
    ("amniotic_fluid", "Amniotic Fluid Disorders", "conditions/amniotic-fluid.md", None),
    ("fetal_surveillance", "Fetal Surveillance", "conditions/fetal-surveillance.md", None),
    ("fetal_growth_restriction", "Fetal Growth Restriction (IUGR)", None, "D005316"),
    ("fetal_anomalies", "Fetal Anomalies", None, None),
]

CORE_DRUGS = [
    ("magnesium_sulfate", "Magnesium Sulfate", "drug"),
    ("labetalol", "Labetalol", "drug"),
    ("nifedipine", "Nifedipine", "drug"),
    ("methyldopa", "Methyldopa", "drug"),
    ("low_dose_aspirin", "Low-Dose Aspirin", "drug"),
    ("tranexamic_acid", "Tranexamic Acid", "drug"),
    ("corticosteroids", "Corticosteroids", "drug"),
    ("insulin", "Insulin", "drug"),
    ("metformin", "Metformin", "drug"),
    ("glyburide", "Glyburide", "drug"),
    ("misoprostol", "Misoprostol", "drug"),
    ("carboprost", "Carboprost", "drug"),
    ("methylergonovine", "Methylergonovine", "drug"),
    ("oxytocin", "Oxytocin", "drug"),
    ("methotrexate", "Methotrexate", "drug"),
    ("rhogam", "Rh immune globulin (Rhogam)", "drug"),
]

CORE_PROCEDURES = [
    ("cesarean_delivery", "Cesarean Delivery", "procedure"),
    ("dilation_curettage", "Dilation and Curettage", "procedure"),
    ("cervical_cerclage", "Cervical Cerclage", "procedure"),
    ("ultrasound_tv", "Transvaginal Ultrasound", "procedure"),
    ("transvaginal_ultrasound", "Transvaginal Ultrasound", "procedure"),  # alias
    ("ultrasound_abd", "Abdominal Ultrasound", "procedure"),
    ("doppler_uta", "Uterine Artery Doppler", "procedure"),
    ("cervical_length", "Cervical Length Measurement", "procedure"),
    ("biophysical_profile", "Biophysical Profile", "procedure"),
    ("nonstress_test", "Nonstress Test", "procedure"),
    ("laceration_repair", "Laceration Repair", "procedure"),
    ("arterial_embolization", "Uterine Arterial Embolization", "procedure"),
    ("hysterectomy", "Hysterectomy", "procedure"),
    ("fetal_fibronectin", "Fetal Fibronectin Test", "procedure"),
    ("surgical_management", "Surgical Management", "procedure"),
]

CORE_SYMPTOMS = [
    ("hypertension", "Hypertension", "symptom"),
    ("proteinuria", "Proteinuria", "symptom"),
    ("edema", "Edema", "symptom"),
    ("vaginal_bleeding", "Vaginal Bleeding", "symptom"),
    ("abdominal_pain", "Abdominal Pain", "symptom"),
    ("uterine_tenderness", "Uterine Tenderness", "symptom"),
    ("fever", "Fever", "symptom"),
    ("oligohydramnios", "Oligohydramnios", "symptom"),
    ("polyhydramnios", "Polyhydramnios", "symptom"),
    ("seizures", "Seizures", "symptom"),
    ("headache", "Headache", "symptom"),
    ("visual_changes", "Visual Changes", "symptom"),
    ("thrombocytopenia", "Thrombocytopenia", "symptom"),
    ("elevated_liver_enzymes", "Elevated Liver Enzymes", "symptom"),
    ("pulmonary_edema", "Pulmonary Edema", "symptom"),
    ("hemorrhage", "Hemorrhage", "symptom"),
    ("coagulopathy", "Coagulopathy", "symptom"),
    ("fetal_distress", "Fetal Distress", "symptom"),
    ("macrosomia", "Fetal Macrosomia", "symptom"),
    ("shoulder_dystocia", "Shoulder Dystocia", "symptom"),
    ("rupture", "Rupture", "symptom"),
]

CORE_RISK_FACTORS = [
    ("primiparity", "Primiparity", "risk_factor"),
    ("advanced_maternal_age", "Advanced Maternal Age", "risk_factor"),
    ("obesity", "Obesity", "risk_factor"),
    ("chronic_hypertension", "Chronic Hypertension", "risk_factor"),
    ("diabetes_mellitus", "Diabetes Mellitus", "risk_factor"),
    ("multiple_pregnancy", "Multiple Pregnancy", "risk_factor"),
    ("smoking", "Smoking", "risk_factor"),
    ("previous_cesarean", "Previous Cesarean", "risk_factor"),
    ("placental_previa", "Placenta Previa", "risk_factor"),
    ("trauma", "Trauma", "risk_factor"),
    ("cocaine_use", "Cocaine Use", "risk_factor"),
    ("gitelman_syndrome", "Gitelman Syndrome", "risk_factor"),
    ("history_preeclampsia", "History of Preeclampsia", "risk_factor"),
    ("low_papp_a", "Low PAPP-A", "risk_factor"),
    ("cervical_incompetence", "Cervical Incompetence", "risk_factor"),
]

CORE_MECHANISMS = [
    ("placental_dysfunction", "Placental Dysfunction", "mechanism"),
    ("endothelial_dysfunction", "Endothelial Dysfunction", "mechanism"),
    ("angiogenic_imbalance", "Angiogenic Imbalance", "mechanism"),
    ("uterine_atony", "Uterine Atony", "mechanism"),
    ("trophoblast_invasion", "Abnormal Trophoblast Invasion", "mechanism"),
    ("spiral_artery_remodeling", "Incomplete Spiral Artery Remodeling", "mechanism"),
    ("iron_deficiency", "Iron Deficiency", "mechanism"),
    ("coagulopathy_mechanism", "Coagulopathy", "mechanism"),
]

# Seed edges with evidence (manual curation from page content)
# Format: (from, to, relation, evidence, source)
CORE_EDGES = [
    # Preeclampsia
    ("preeclampsia", "hypertension", "causes", "2B", "preeclampsia.md"),
    ("preeclampsia", "proteinuria", "causes", "2B", "preeclampsia.md"),
    ("preeclampsia", "thrombocytopenia", "causes", "2B", "preeclampsia.md"),
    ("preeclampsia", "elevated_liver_enzymes", "causes", "2B", "preeclampsia.md"),
    ("preeclampsia", "pulmonary_edema", "causes", "2B", "preeclampsia.md"),
    ("preeclampsia", "seizures", "causes", "2B", "preeclampsia.md"),  # eclampsia seizure
    ("preeclampsia", "placental_dysfunction", "mechanism_of", "2B", "preeclampsia.md"),
    ("preeclampsia", "endothelial_dysfunction", "mechanism_of", "2B", "preeclampsia.md"),
    ("preeclampsia", "angiogenic_imbalance", "mechanism_of", "2B", "preeclampsia.md"),
    ("low_dose_aspirin", "preeclampsia", "prevents", "1A", "preeclampsia.md"),
    ("magnesium_sulfate", "preeclampsia", "treats", "1A", "preeclampsia.md"),  # prevents eclampsia
    ("labetalol", "preeclampsia", "treats", "1B", "preeclampsia.md"),
    ("nifedipine", "preeclampsia", "treats", "1B", "preeclampsia.md"),
    ("methyldopa", "preeclampsia", "treats", "1B", "preeclampsia.md"),
    ("primiparity", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("advanced_maternal_age", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("obesity", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("chronic_hypertension", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("diabetes_mellitus", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("multiple_pregnancy", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("history_preeclampsia", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),
    ("placental_abruption", "preeclampsia", "risk_factor_for", "2B", "preeclampsia.md"),

    # Placental abruption
    ("placental_abruption", "vaginal_bleeding", "causes", "2B", "placental-abruption.md"),
    ("placental_abruption", "abdominal_pain", "causes", "2B", "placental-abruption.md"),
    ("placental_abruption", "uterine_tenderness", "causes", "2B", "placental-abruption.md"),
    ("placental_abruption", "fetal_distress", "causes", "2B", "placental-abruption.md"),
    ("placental_abruption", "coagulopathy", "causes", "2B", "placental-abruption.md"),
    ("placental_abruption", "preeclampsia", "risk_factor_for", "2B", "placental-abruption.md"),
    ("hypertension", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("smoking", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("cocaine_use", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("trauma", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("previous_cesarean", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("cesarean_delivery", "placental_abruption", "risk_factor_for", "2B", "placental-abruption.md"),
    ("transvaginal_ultrasound", "placental_abruption", "diagnoses", "2B", "placental-abruption.md"),

    # Postpartum hemorrhage
    ("postpartum_hemorrhage", "hemorrhage", "causes", "2B", "postpartum-hemorrhage.md"),
    ("postpartum_hemorrhage", "coagulopathy", "causes", "2B", "postpartum-hemorrhage.md"),
    ("postpartum_hemorrhage", "uterine_atony", "mechanism_of", "2B", "postpartum-hemorrhage.md"),
    ("postpartum_hemorrhage", "placental_previa", "risk_factor_for", "2B", "postpartum-hemorrhage.md"),
    ("postpartum_hemorrhage", "placental_abruption", "risk_factor_for", "2B", "postpartum-hemorrhage.md"),
    ("postpartum_hemorrhage", "multiple_pregnancy", "risk_factor_for", "2B", "postpartum-hemorrhage.md"),
    ("oxytocin", "postpartum_hemorrhage", "treats", "1A", "postpartum-hemorrhage.md"),
    ("tranexamic_acid", "postpartum_hemorrhage", "treats", "1A", "postpartum-hemorrhage.md"),
    ("misoprostol", "postpartum_hemorrhage", "treats", "1A", "postpartum-hemorrhage.md"),
    ("carboprost", "postpartum_hemorrhage", "treats", "2B", "postpartum-hemorrhage.md"),
    ("methylergonovine", "postpartum_hemorrhage", "treats", "2B", "postpartum-hemorrhage.md"),
    ("laceration_repair", "postpartum_hemorrhage", "treats", "1B", "postpartum-hemorrhage.md"),
    ("arterial_embolization", "postpartum_hemorrhage", "treats", "2B", "postpartum-hemorrhage.md"),
    ("hysterectomy", "postpartum_hemorrhage", "treats", "1B", "postpartum-hemorrhage.md"),

    # Gestational diabetes
    ("gestational_diabetes", "macrosomia", "causes", "2B", "gestational-diabetes.md"),
    ("gestational_diabetes", "shoulder_dystocia", "causes", "2B", "gestational-diabetes.md"),
    ("gestational_diabetes", "polyhydramnios", "causes", "2B", "gestational-diabetes.md"),
    ("gestational_diabetes", "preeclampsia", "risk_factor_for", "2B", "gestational-diabetes.md"),
    ("obesity", "gestational_diabetes", "risk_factor_for", "2B", "gestational-diabetes.md"),
    ("diabetes_mellitus", "gestational_diabetes", "risk_factor_for", "2B", "gestational-diabetes.md"),
    ("advanced_maternal_age", "gestational_diabetes", "risk_factor_for", "2B", "gestational-diabetes.md"),
    ("previous_cesarean", "gestational_diabetes", "risk_factor_for", "2B", "gestational-diabetes.md"),
    ("insulin", "gestational_diabetes", "treats", "1A", "gestational-diabetes.md"),
    ("metformin", "gestational_diabetes", "treats", "1B", "gestational-diabetes.md"),
    ("glyburide", "gestational_diabetes", "treats", "1B", "gestational-diabetes.md"),
    ("ultrasound_abd", "gestational_diabetes", "diagnoses", "2B", "gestational-diabetes.md"),  # estimates fetal weight

    # Ectopic pregnancy
    ("ectopic_pregnancy", "abdominal_pain", "causes", "2B", "ectopic-pregnancy.md"),
    ("ectopic_pregnancy", "vaginal_bleeding", "causes", "2B", "ectopic-pregnancy.md"),
    ("ectopic_pregnancy", "rupture", "causes", "2B", "ectopic-pregnancy.md"),
    ("ectopic_pregnancy", "hemorrhage", "causes", "2B", "ectopic-pregnancy.md"),
    ("ectopic_pregnancy", "smoking", "risk_factor_for", "2B", "ectopic-pregnancy.md"),
    ("ectopic_pregnancy", "previous_cesarean", "risk_factor_for", "2B", "ectopic-pregnancy.md"),  # prior ectopic strong RF
    ("ultrasound_tv", "ectopic_pregnancy", "diagnoses", "2B", "ectopic-pregnancy.md"),
    ("dilation_curettage", "ectopic_pregnancy", "treats", "2B", "ectopic-pregnancy.md"),
    ("methotrexate", "ectopic_pregnancy", "treats", "1B", "ectopic-pregnancy.md"),
    ("rhogam", "ectopic_pregnancy", "treats", "1B", "ectopic-pregnancy.md"),  # if Rh-negative
    ("surgical_management", "ectopic_pregnancy", "treats", "1B", "ectopic-pregnancy.md"),

    # Preterm labor
    ("preterm_labor", "previous_cesarean", "risk_factor_for", "2B", "preterm-labor.md"),
    ("preterm_labor", "multiple_pregnancy", "risk_factor_for", "2B", "preterm-labor.md"),
    ("preterm_labor", "cervical_incompetence", "risk_factor_for", "2B", "preterm-labor.md"),
    ("preterm_labor", "placental_abruption", "risk_factor_for", "2B", "preterm-labor.md"),
    ("preterm_labor", "low_papp_a", "risk_factor_for", "2B", "preterm-labor.md"),
    ("corticosteroids", "preterm_labor", "treats", "1A", "preterm-labor.md"),  # antenatal steroids
    ("cervical_cerclage", "preterm_labor", "treats", "1B", "preterm-labor.md"),
    ("cervical_length", "preterm_labor", "diagnoses", "2B", "preterm-labor.md"),
    ("ultrasound_tv", "preterm_labor", "diagnoses", "2B", "preterm-labor.md"),
    ("fetal_fibronectin", "preterm_labor", "diagnoses", "2B", "preterm-labor.md"),
    ("preeclampsia", "preterm_labor", "risk_factor_for", "2B", "preterm-labor.md"),

    # Amniotic fluid
    ("oligohydramnios", "fetal_growth_restriction", "causes", "2B", "amniotic-fluid.md"),
    ("polyhydramnios", "diabetes_mellitus", "risk_factor_for", "2B", "amniotic-fluid.md"),
    ("polyhydramnios", "fetal_anomalies", "risk_factor_for", "2B", "amniotic-fluid.md"),
    ("ultrasound_abd", "amniotic_fluid", "diagnoses", "2B", "amniotic-fluid.md"),

    # Fetal surveillance
    ("nonstress_test", "fetal_surveillance", "assesses", "2B", "fetal-surveillance.md"),
    ("biophysical_profile", "fetal_surveillance", "assesses", "2B", "fetal-surveillance.md"),
    ("doppler_uta", "fetal_surveillance", "assesses", "2B", "fetal-surveillance.md"),
    ("ultrasound_abd", "fetal_surveillance", "assesses", "2B", "fetal-surveillance.md"),
]


def seed_graph(db_path: str | Path):
    """Bootstrap the semantic graph with all core nodes and edges."""
    g = SemanticGraph(db_path)

    # Add nodes
    all_nodes = []
    for nid, label, page, mesh in CORE_CONDITIONS:
        g.add_node(nid, label, "condition", canonical=True, page_path=page, mesh_id=mesh)
        all_nodes.append(nid)
    for nid, label, ntype in CORE_DRUGS:
        g.add_node(nid, label, ntype)
        all_nodes.append(nid)
    for nid, label, ntype in CORE_PROCEDURES:
        g.add_node(nid, label, ntype)
        all_nodes.append(nid)
    for nid, label, ntype in CORE_SYMPTOMS:
        g.add_node(nid, label, ntype)
        all_nodes.append(nid)
    for nid, label, ntype in CORE_RISK_FACTORS:
        g.add_node(nid, label, ntype)
        all_nodes.append(nid)
    for nid, label, ntype in CORE_MECHANISMS:
        g.add_node(nid, label, ntype)
        all_nodes.append(nid)

    # Add edges
    edges = []
    for i, (from_n, to_n, rel, evidence, src) in enumerate(CORE_EDGES):
        # Skip if either node wasn't seeded (defensive)
        if from_n not in all_nodes or to_n not in all_nodes:
            continue
        edge_id = f"edge_{i:04d}"
        g.add_edge(edge_id, from_n, to_n, rel, evidence=evidence, source=src, extracted_by="manual")
        edges.append(edge_id)

    stats = g.count()
    g.close()
    return stats["nodes"], stats["edges"]
