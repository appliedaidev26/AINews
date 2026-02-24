#!/usr/bin/env python3
"""Local test harness for the Cloud Tasks-based queue-run pipeline.

Simulates what GCP Cloud Tasks + Pub/Sub would do in production by
directly calling the /internal/* endpoints in the correct order.

Usage:
    python scripts/test_queue_run_local.py
    python scripts/test_queue_run_local.py --date 2026-02-23
    python scripts/test_queue_run_local.py --date-from 2026-02-20 --date-to 2026-02-22
    python scripts/test_queue_run_local.py --sources hn,arxiv --date 2026-02-23
"""
import argparse
import base64
import json
import sys
from datetime import date, timedelta

import requests

BASE = "http://localhost:8000"

# Read admin key from .env
def _get_admin_key() -> str:
    try:
        with open(".env") as f:
            for line in f:
                if line.startswith("ADMIN_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    import os
    return os.getenv("ADMIN_API_KEY", "")


def queue_run(admin_key: str, date_from: str, date_to: str, sources: str) -> dict:
    """Create a PipelineRun via /admin/queue-run."""
    resp = requests.post(
        f"{BASE}/admin/queue-run",
        params={
            "date_from": date_from,
            "date_to": date_to,
            "sources": sources,
            "triggered_by": "local_test",
        },
        headers={"X-Admin-Key": admin_key},
    )
    resp.raise_for_status()
    return resp.json()


def fetch_source(run_id: int, source: str, target_date: str) -> dict:
    """Simulate a Cloud Tasks dispatch to /internal/fetch-source."""
    resp = requests.post(
        f"{BASE}/internal/fetch-source",
        json={"run_id": run_id, "source": source, "date": target_date},
    )
    resp.raise_for_status()
    return resp.json()


def enrich_articles(article_ids: list[int], run_id: int, source: str, target_date: str) -> dict:
    """Simulate a Pub/Sub push to /internal/enrich."""
    payload = json.dumps({
        "article_ids": article_ids,
        "run_id": run_id,
        "source": source,
        "date": target_date,
    }).encode()
    pubsub_body = {
        "message": {
            "data": base64.b64encode(payload).decode(),
            "messageId": "local-test",
        },
        "subscription": "local-test-sub",
    }
    resp = requests.post(f"{BASE}/internal/enrich", json=pubsub_body)
    resp.raise_for_status()
    return resp.json()


def vectorize_articles(article_ids: list[int], run_id: int, source: str, target_date: str) -> dict:
    """Simulate a Pub/Sub push to /internal/vectorize."""
    payload = json.dumps({
        "article_ids": article_ids,
        "run_id": run_id,
        "source": source,
        "date": target_date,
    }).encode()
    pubsub_body = {
        "message": {
            "data": base64.b64encode(payload).decode(),
            "messageId": "local-test",
        },
        "subscription": "local-test-sub",
    }
    resp = requests.post(f"{BASE}/internal/vectorize", json=pubsub_body)
    resp.raise_for_status()
    return resp.json()


def finalize_runs() -> dict:
    """Simulate Cloud Scheduler calling /internal/finalize-runs."""
    resp = requests.get(f"{BASE}/internal/finalize-runs")
    resp.raise_for_status()
    return resp.json()


def get_run_tasks(admin_key: str, run_id: int) -> dict:
    resp = requests.get(
        f"{BASE}/admin/runs/{run_id}/tasks",
        headers={"X-Admin-Key": admin_key},
    )
    resp.raise_for_status()
    return resp.json()


def get_enrich_status(admin_key: str, run_id: int) -> dict:
    resp = requests.get(
        f"{BASE}/admin/runs/{run_id}/enrich-status",
        headers={"X-Admin-Key": admin_key},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Local test harness for queue-run pipeline")
    parser.add_argument("--date", default=str(date.today()), help="Single date (default: today)")
    parser.add_argument("--date-from", dest="date_from", help="Range start")
    parser.add_argument("--date-to",   dest="date_to",   help="Range end")
    parser.add_argument("--sources",   default="hn,arxiv", help="Comma-separated sources (default: hn,arxiv)")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip enrichment step")
    args = parser.parse_args()

    admin_key = _get_admin_key()
    if not admin_key:
        print("ERROR: ADMIN_API_KEY not found in .env — set it and retry")
        sys.exit(1)

    date_from = args.date_from or args.date
    date_to   = args.date_to   or args.date
    sources   = args.sources

    # Build list of (source, date) pairs
    d0 = date.fromisoformat(date_from)
    d1 = date.fromisoformat(date_to)
    dates = [str(d0 + timedelta(days=i)) for i in range((d1 - d0).days + 1)]
    source_list = [s.strip() for s in sources.split(",") if s.strip()]

    print(f"\n{'='*60}")
    print(f"  Local Queue-Run Test")
    print(f"  Sources: {', '.join(source_list)}")
    print(f"  Dates:   {date_from} → {date_to}  ({len(dates)} day(s))")
    print(f"{'='*60}\n")

    # Step 1: Create PipelineRun
    print("▶ Step 1: Creating PipelineRun via POST /admin/queue-run …")
    result = queue_run(admin_key, date_from, date_to, sources)
    run_id = result["run_id"]
    total = result["total_tasks"]
    print(f"  ✓ Run #{run_id} created  (total_tasks={total}, status=queued)")
    print(f"  Note: enqueue_fetch_task returned failed={result['failed_to_enqueue']} "
          f"(expected — Cloud Tasks not configured locally)")

    # Step 2: Simulate Cloud Tasks calling /internal/fetch-source for each task
    print(f"\n▶ Step 2: Simulating {total} Cloud Tasks dispatches …")
    all_saved_ids: list[int] = []
    for d in dates:
        for src in source_list:
            print(f"  • fetch-source  source={src}  date={d} …", end=" ", flush=True)
            try:
                r = fetch_source(run_id, src, d)
                saved = r.get("saved", 0)
                print(f"fetched={r['fetched']}  saved={saved}")
                # Collect saved IDs for enrich/vectorize simulation
                # (we'll use enrich-status endpoint to verify counts instead)
                all_saved_ids.append(saved)
            except requests.HTTPError as e:
                print(f"FAILED ({e.response.status_code}: {e.response.text[:100]})")

    # Step 3: Simulate finalize-runs (Cloud Scheduler)
    print(f"\n▶ Step 3: Finalizing run via GET /internal/finalize-runs …")
    fin = finalize_runs()
    print(f"  ✓ Finalized: {fin}")

    # Step 4: Show task grid
    print(f"\n▶ Step 4: Task grid for run #{run_id} …")
    tasks_data = get_run_tasks(admin_key, run_id)
    run_info = tasks_data["run"]
    tasks = tasks_data["tasks"]
    print(f"  Run status: {run_info['status']}")
    print(f"  {'Source':<10} {'Date':<12} {'Status':<10} {'Saved'}")
    print(f"  {'-'*45}")
    for t in tasks:
        status_icon = {"success": "✓", "failed": "✗", "running": "●", "pending": "○"}.get(t["status"], "?")
        print(f"  {t['source']:<10} {t['date']:<12} {status_icon} {t['status']:<8} {t['articles_saved'] or '—'}")

    # Step 5: Check enrich/vectorize counts
    print(f"\n▶ Step 5: Enrich/vectorize status …")
    es = get_enrich_status(admin_key, run_id)
    total_saved = es["total_saved"]
    enriched = es["enriched"]
    vectorized = es["vectorized"]
    print(f"  Total saved:  {total_saved}")
    print(f"  Enriched:     {enriched} / {total_saved}")
    print(f"  Vectorized:   {vectorized} / {total_saved}  (Vertex AI not configured — expected 0)")

    if not args.skip_enrich and total_saved > 0:
        print(f"\n  Note: Enrichment runs asynchronously in production via Pub/Sub.")
        print(f"  To trigger enrichment now, the old /admin/ingest already handles it.")
        print(f"  Skipping local Pub/Sub simulation (enrichment still runs via the")
        print(f"  legacy pipeline if GEMINI_API_KEY is set).")

    print(f"\n{'='*60}")
    print(f"  ✓ Local test complete — run #{run_id}")
    print(f"  View detail at: http://localhost:5173/admin/backfill/{run_id}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
