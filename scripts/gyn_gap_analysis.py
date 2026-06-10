#!/usr/bin/env python3
"""
Analyze GYN coverage gaps in the wiki and recommend PubMed search terms.
"""

import json
import os
from pathlib import Path
import yaml

WIKI_ROOT = Path("wiki")
RAW_DIR = Path("wiki/raw")

def load_frontmatter(path):
    """Extract YAML frontmatter from markdown file."""
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
        if text.startswith('---'):
            end = text.find('---', 3)
            if end != -1:
                return yaml.safe_load(text[3:end])
    except Exception as e:
        pass
    return {}

def analyze_gyn_gaps():
    """Identify scaffolded GYN pages with evidence gaps."""
    
    # Key GYN topic keywords to search raw sources for
    gyn_topics = {
        "abnormal-uterine-bleeding": ["abnormal uterine bleeding", "uterine hemorrhage", "dysfunctional bleeding", "AUB"],
        "leiomyomas": ["leiomyoma", "fibroid", "uterine fibroid", "myoma"],
        "adenomyosis": ["adenomyosis", "endometriosis interna"],
        "dysmenorrhea": ["dysmenorrhea", "menstrual pain", "painful menstruation"],
        "amenorrhea": ["amenorrhea", "secondary amenorrhea", "primary amenorrhea"],
        "menopause": ["menopause", "perimenopause", "hormone replacement therapy", "HRT"],
        "contraception": ["contraception", "birth control", "IUD", "oral contraceptive", "hormonal contraception"],
        "endometrial-hyperplasia": ["endometrial hyperplasia", "endometrial proliferation"],
        "cervical-dysplasia": ["cervical dysplasia", "CIN", "cervical intraepithelial neoplasia"],
        "hpv-screening": ["HPV screening", "human papillomavirus", "cervical cancer screening"],
        "endometrial-cancer": ["endometrial cancer", "uterine cancer", "corpus uteri cancer"],
        "ovarian-cancer": ["ovarian cancer", "ovarian carcinoma", "ovarian neoplasm"],
        "urinary-incontinence": ["urinary incontinence", "stress incontinence", "urge incontinence"],
        "pelvic-organ-prolapse": ["pelvic organ prolapse", "uterine prolapse", "cystocele", "rectocele"],
        "vulvovaginitis": ["vulvovaginitis", "vaginitis", "vulvitis"],
        "bacterial-vaginosis": ["bacterial vaginosis", "BV", "gardnerella"],
    }
    
    results = []
    
    for slug, keywords in gyn_topics.items():
        page_path = WIKI_ROOT / "conditions" / f"{slug}.md"
        if not page_path.exists():
            # Try root wiki
            page_path = WIKI_ROOT / f"{slug}.md"
        
        if page_path.exists():
            fm = load_frontmatter(page_path)
            has_sources = bool(fm.get('sources'))
            evidence_level = fm.get('evidence_level', '?')
            
            # Check for coverage-gap tag
            tags = fm.get('tags', [])
            is_scaffold = 'coverage-gap' in tags
            
            results.append({
                'slug': slug,
                'title': fm.get('title', slug),
                'has_sources': has_sources,
                'evidence_level': evidence_level,
                'is_scaffold': is_scaffold,
                'keywords': keywords
            })
    
    return results

def generate_pubmed_searches(gaps):
    """Generate PubMed search queries for gaps."""
    searches = []
    
    for gap in gaps:
        if not gap['has_sources'] or gap['is_scaffold']:
            # Build OR search with keywords
            terms = ' OR '.join(f'"{kw}"' if ' ' in kw else kw for kw in gap['keywords'])
            searches.append({
                'topic': gap['slug'],
                'search': f"({terms}) AND (guideline[Title/Abstract] OR systematic review[Title/Abstract])",
                'priority': 'high' if gap['is_scaffold'] else 'medium'
            })
    
    return searches

def main():
    print("=" * 70)
    print("OB/GYN Wiki Coverage Gap Analysis")
    print("=" * 70)
    
    gaps = analyze_gyn_gaps()
    
    print(f"\nTotal GYN topics analyzed: {len(gaps)}")
    
    scaffolded = [g for g in gaps if g['is_scaffold']]
    missing_sources = [g for g in gaps if not g['has_sources']]
    
    print(f"Scaffolded pages (coverage-gap): {len(scaffolded)}")
    print(f"Pages without sources: {len(missing_sources)}")
    
    print("\n--- Detailed Gap Report ---\n")
    
    for gap in gaps:
        status = []
        if gap['is_scaffold']:
            status.append("SCAFFOLD")
        if not gap['has_sources']:
            status.append("NO_SOURCES")
        
        if status:  # Only show gaps
            print(f"  {gap['slug']}")
            print(f"    Evidence level: {gap['evidence_level']}")
            print(f"    Status: {', '.join(status)}")
            print(f"    Keywords: {', '.join(gap['keywords'][:3])}")
            print()
    
    # Generate PubMed recommendations
    searches = generate_pubmed_searches(gaps)
    
    print("\n--- Recommended PubMed Ingestion Searches ---\n")
    
    high_priority = [s for s in searches if s['priority'] == 'high']
    medium_priority = [s for s in searches if s['priority'] == 'medium']
    
    print(f"High priority searches ({len(high_priority)}):")
    for s in high_priority[:5]:
        print(f"  {s['topic']}: {s['search']}")
    
    print(f"\nMedium priority searches ({len(medium_priority)}):")
    for s in medium_priority[:3]:
        print(f"  {s['topic']}: {s['search'][:80]}...")
    
    # Write actionable ingest script
    print("\n--- Action Steps ---")
    print("1. Run targeted PubMed ingestion with keyword searches above")
    print("2. Re-synthesize scaffolded pages with ingested sources")
    print("3. Update evidence_level from '4' to '1A-2B' per synthesis")

if __name__ == '__main__':
    main()
