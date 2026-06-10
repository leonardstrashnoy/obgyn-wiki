#!/usr/bin/env python3
"""Periodic PubMed OA ingestion script for cron.

Fetches new articles for configured OB/GYN topics and logs results.

Recommended cron entry (uses conda python which has pandas/duckdb):
    */30 * * * * cd /home/leonard/Projects/obgyn-wiki && /home/leonard/miniconda3/bin/python3 scripts/ingest_daily.py >> /home/leonard/Projects/obgyn-wiki/logs/cron.log 2>&1

Run manually:
    /home/leonard/miniconda3/bin/python3 scripts/ingest_daily.py
"""

import sys
import os
from datetime import datetime, timedelta

# Fetch only articles from last N days (prevents re-fetching old articles)
ROLLING_WINDOW_DAYS = 14
from pathlib import Path

sys.path.insert(0, "/home/leonard/Projects/obgyn-wiki")

from obgyn_wiki.pubmed_fetcher import ingest_mesh_topic

WIKI_ROOT = Path("/home/leonard/Projects/obgyn-wiki/wiki")
LOG_FILE = WIKI_ROOT / "log.md"

# OB/GYN topics to monitor
TOPICS = [
    "Preeclampsia",
    "Gestational Diabetes",
    "Preterm Labor",
    "Postpartum Hemorrhage",
    "Ectopic Pregnancy",
    "Placental Abruption",
    "Eclampsia",
    "HELLP Syndrome",
    "Fetal Growth Restriction",
    "Premature Rupture of Membranes",
]

def main():
    today = datetime.now()
    mindate = (today - timedelta(days=ROLLING_WINDOW_DAYS)).strftime("%Y/%m/%d")
    maxdate = today.strftime("%Y/%m/%d")
    date_str = today.strftime("%Y-%m-%d")
    
    log_entries = [f"## [{date_str}] auto-ingest | PubMed OA fetch (window: {mindate} to {maxdate})\n"]
    total_new = 0
    
    print(f"=== Auto-ingestion started: {today} ===\n")
    
    for topic in TOPICS:
        try:
            print(f"Fetching: {topic} ...")
            result = ingest_mesh_topic(topic, limit=5, mindate=mindate, maxdate=maxdate)
            count = len(result)
            total_new += count
            log_entries.append(f"- {topic}: {count} new articles\n")
            print(f"  [OK] {count} articles")
        except Exception as e:
            log_entries.append(f"- {topic}: ERROR {e}\n")
            print(f"  [ERR] {e}")
    
    log_entries.append(f"- Total new: {total_new}\n\n")
    
    # Append new articles to Parquet archive
    if total_new > 0:
        try:
            from obgyn_wiki.archive_ops import full_resync
            print("  Syncing Parquet archive...")
            full_resync()
            print("  [OK] Archive synced")
        except Exception as e:
            print(f"  [WARN] Archive sync failed: {e}")
    
    # Append to log
    existing_log = LOG_FILE.read_text("utf-8") if LOG_FILE.exists() else ""
    new_log = "".join(log_entries) + existing_log
    LOG_FILE.write_text(new_log, encoding="utf-8")
    
    print(f"\n=== Complete: {total_new} new articles added ===")
    print(f"Log updated: {LOG_FILE}")

if __name__ == "__main__":
    main()
