# OB/GYN Wiki Schema

## Domain
Evidence-based obstetrics and gynecology knowledge base. Focus: clinical conditions,
interventions, drug safety, and guideline summaries relevant to practicing OB/GYN
specialists and related providers.

## Conventions
- File names: lowercase, hyphens, no spaces (e.g., `preeclampsia-management.md`)
- Every wiki page starts with YAML frontmatter (see below)
- Use `[[wikilinks]]` to link between pages (minimum 2 outbound links per page)
- When updating a page, always bump the `updated` date
- Every new page must be added to `index.md` under correct section
- Every action must be appended to `log.md`
- **Provenance markers:** On pages synthesizing 3+ sources, append `^[raw/articles/source-file.md]`
  at paragraph end whose claims come from a specific source.
- **Evidence grading** is mandatory on every concept page (see taxonomy)
- **Scope boundary:** Pages never contain patient-specific data. Only population-level evidence.

## Frontmatter

```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | condition | intervention | guideline | comparison | query | drug
confidence: high | medium | low        # how well-supported the claims are
evidence_level: 1A | 1B | 2A | 2B | 3 | 4 | expert-opinion  # Oxford CEBM levels + recommendation grade
contested: true                        # set when unresolved contradictions exist
contradictions: [other-page-slug]      # pages this one conflicts with
tags: [see taxonomy]
sources: [raw/articles/source-name.md]
---
```

### Evidence Levels (Oxford CEBM adapted)

| Level | Description |
|-------|-------------|
| 1A   | Systematic review/meta-analysis of RCTs |
| 1B   | Individual RCT with narrow confidence intervals |
| 2A   | Systematic review of cohort studies |
| 2B   | Individual cohort/low-quality RCT |
| 3    | Case-control studies, case series |
| 4    | Expert opinion, bench/mechanistic research |

### Recommendation Grade
Append letter to level: **A** = consistent evidence, **B** = inconsistent/limited, **C** = consensus/extrapolation.

### raw/ Frontmatter

```yaml
---
source_url: https://pubmed.ncbi.nlm.nih.gov/...   # or guideline URL
ingested: YYYY-MM-DD
sha256: <hex digest of raw body below frontmatter>
---
```

## Tag Taxonomy

- **Conditions:** condition, maternal, fetal, gynecologic, neonatal, pregnancy
- **Interventions:** intervention, procedure, surgery, medical-therapy, prophylaxis
- **Pharmacology:** drug, drug-safety, drug-interaction, teratogenicity, lactation
- **Evidence:** evidence-level-1a, evidence-level-1b, evidence-level-2, evidence-level-3, evidence-level-4, evidence-contested
- **Guidelines:** guideline, acog, soic, nice, figo, ranzcog, who
- **Populations:** pregnancy, first-trimester, second-trimester, third-trimester, postpartum, adolescent, perimenopausal, geriatric
- **Clinical Areas:** maternal-fetal-medicine, reproductive-endocrinology, gynecologic-oncology, urogynecology, general-obgyn
- **Meta:** comparison, systematic-review, meta-analysis, rct, cohort-study, case-control, narrative-review, expert-opinion
- **Status:** draft, needs-review, stale, outdated

## Page Thresholds
- **Create a page** when an entity/concept appears in 2+ sources OR is central to one high-quality source
- **Add to existing page** when a source mentions something already covered
- **DON'T create** for passing mentions, minor details, or out-of-domain topics
- **Split a page** when it exceeds ~150 lines (medical content should be scannable)
- **Archive** when fully superseded — move to `_archive/`, remove from index

## Condition Pages
One page per notable condition. Include:
- Clinical definition and classification
- Epidemiology (incidence, risk factors)
- Pathophysiology summary
- Evidence-based management with grades
- Complications and prognosis
- Differential diagnosis pointers
- Related conditions and interventions ([[wikilinks]])
- Active research / open questions

## Intervention Pages
One page per drug, procedure, or device. Include:
- Indications and mechanism
- Dosing / technique key points
- Evidence for efficacy (by population)
- Contraindications and precautions
- Adverse effects and safety data
- Lactation / pregnancy classification if applicable
- Related conditions and alternatives ([[wikilinks]])

## Guideline Summary Pages
Structured extraction of official guidelines. Include:
- Guideline body, year, recommendation grade
- Key recommendations table
- What changed from prior version
- Controversies or dissenting opinions
- Link to full guideline and related condition pages

## Comparison Pages
Side-by-side evidence comparisons. Include:
- What is being compared and why
- Evidence table (study, population, intervention, outcome, grade)
- Synthesis and clinical bottom line
- Sources

## Update Policy
When new information conflicts with existing content:
1. Check dates — newer sources generally supersede older ones for clinical practice
2. If genuinely contradictory, note both positions with dates and sources
3. Mark `contradictions:` in frontmatter
4. Flag for user review in lint report
5. NEVER silently overwrite without noting the change

## Safety Rules
- No patient identifiers (PHI) anywhere in wiki
- No clinical advice phrased as directive to a specific patient
- Every therapeutic claim has an evidence level
- Uncertain claims use `confidence: low` and explain why
- Withdrawn/retracted studies noted prominently
