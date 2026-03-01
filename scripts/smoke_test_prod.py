#!/usr/bin/env python3
"""E2E post-deployment smoke test for the AI News production API.

Triggers a real HN backfill run via Cloud Tasks, waits for it to complete,
then verifies articles are readable via the public API — proving the full
pipeline (Cloud Tasks → /internal/fetch-source → Cloud SQL → GET /articles)
is working end-to-end.

Usage:
    python scripts/smoke_test_prod.py \\
        --url https://ainews-api-zz7suegwma-uc.a.run.app \\
        --admin-key SECRET \\
        [--date 2026-02-22]   # default: yesterday
        [--timeout 180]        # default: 180s
"""
import argparse
import sys
import time
from datetime import date, timedelta

import requests

TERMINAL_STATUSES = {"success", "partial", "failed", "cancelled"}
POLL_INTERVAL = 5  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return time.strftime("[%H:%M:%S]")


def _log(msg: str) -> None:
    print(f"{_ts()} {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"{_ts()} ERROR: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def trigger_queue_run(url: str, key: str, date_str: str) -> dict:
    """POST /admin/queue-run — hn only, single date."""
    resp = requests.post(
        f"{url}/admin/queue-run",
        params={
            "date_from": date_str,
            "date_to": date_str,
            "sources": "hn",
            "triggered_by": "smoke_test",
        },
        headers={"X-Admin-Key": key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def poll_run(url: str, key: str, run_id: int, timeout: int, interval: int = POLL_INTERVAL) -> dict:
    """Poll GET /admin/runs/{run_id} until terminal status or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{url}/admin/runs/{run_id}",
            headers={"X-Admin-Key": key},
            timeout=15,
        )
        resp.raise_for_status()
        run = resp.json()
        status = run.get("status", "unknown")
        if status in TERMINAL_STATUSES:
            return run
        _log(f"  run #{run_id} status={status} … waiting {interval}s")
        time.sleep(interval)
    raise TimeoutError(f"Run #{run_id} did not reach terminal status within {timeout}s")


def get_run_tasks(url: str, key: str, run_id: int) -> dict:
    """GET /admin/runs/{run_id}/tasks — returns {run, tasks}."""
    resp = requests.get(
        f"{url}/admin/runs/{run_id}/tasks",
        headers={"X-Admin-Key": key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_articles(url: str, date_str: str) -> list:
    """GET /articles?digest_date=YYYY-MM-DD — returns list of articles."""
    resp = requests.get(
        f"{url}/articles",
        params={"digest_date": date_str, "per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    # Handle both {articles: [...]} and direct list responses
    if isinstance(data, list):
        return data
    return data.get("articles", data.get("items", []))


def get_coverage(url: str, key: str, days: int) -> dict:
    """GET /admin/coverage?days=N — returns {coverage: [...]}."""
    resp = requests.get(
        f"{url}/admin/coverage",
        params={"days": days},
        headers={"X-Admin-Key": key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def diagnose_enrichment(url: str, key: str, target_date: str) -> None:
    """Print coverage breakdown for target_date to diagnose assertion 2 failures."""
    try:
        data = get_coverage(url, key, days=3)
        rows = data.get("coverage", [])
        row = next((r for r in rows if r["date"] == target_date), None)
        print(f"\n  [DIAG] Coverage for {target_date}:")
        if row is None:
            print(f"    total in DB:         0   ← articles never written (DATABASE_URL issue?)")
            print(f"    is_enriched=1  :     0   enriched")
            print(f"    is_enriched=0  :     0   pending")
            print(f"    is_enriched=-1 :     0   failed")
        else:
            total   = row.get("total",   0)
            enriched = row.get("enriched", 0)
            pending  = row.get("pending",  0)
            failed   = row.get("failed",   0)
            note_total   = "← articles never written (DATABASE_URL issue?)" if total == 0 else ""
            note_failed  = "← EXCLUDED by is_enriched >= 0 filter!" if failed > 0 else ""
            print(f"    total in DB:     {total:>6}   {note_total}")
            print(f"    is_enriched=1  : {enriched:>6}   enriched — visible via >= 0 filter")
            print(f"    is_enriched=0  : {pending:>6}   pending  — visible via >= 0 filter")
            print(f"    is_enriched=-1 : {failed:>6}   failed   {note_failed}")
    except Exception as exc:
        _err(f"Could not fetch coverage for diagnosis: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    yesterday = str(date.today() - timedelta(days=1))

    parser = argparse.ArgumentParser(
        description="E2E post-deployment smoke test for AI News production API"
    )
    parser.add_argument("--url", required=True, help="Base API URL (no trailing slash)")
    parser.add_argument("--admin-key", required=True, dest="admin_key", help="X-Admin-Key value")
    parser.add_argument("--date", default=yesterday, help=f"Target date YYYY-MM-DD (default: yesterday = {yesterday})")
    parser.add_argument("--timeout", type=int, default=180, help="Max seconds to wait for run (default: 180)")
    args = parser.parse_args()

    url       = args.url.rstrip("/")
    key       = args.admin_key
    date_str  = args.date
    timeout   = args.timeout

    failures: list[str] = []

    print(f"\n{'='*62}")
    print(f"  AI News E2E Smoke Test")
    print(f"  URL:     {url}")
    print(f"  Date:    {date_str}")
    print(f"  Timeout: {timeout}s")
    print(f"{'='*62}\n")

    # ── Step 1: Health check ─────────────────────────────────────────
    _log("Step 1: GET /health …")
    try:
        resp = requests.get(f"{url}/health", timeout=10)
        resp.raise_for_status()
        _log(f"  ✓ /health → {resp.status_code}")
    except Exception as exc:
        _err(f"/health failed: {exc}")
        failures.append(f"Step 1 (health): {exc}")
        # Fatal — can't proceed if API is down
        print(f"\n{'='*62}")
        print(f"  FAILED — {len(failures)} assertion(s) failed")
        print(f"{'='*62}\n")
        sys.exit(1)

    # ── Step 2: Trigger queue-run (hn only, target date) ────────────
    _log(f"Step 2: POST /admin/queue-run  sources=hn  date={date_str} …")
    try:
        qr = trigger_queue_run(url, key, date_str)
        run_id  = qr["run_id"]
        status  = qr.get("status", "unknown")
        sources = qr.get("sources", [])
        _log(f"  ✓ Run #{run_id} created  status={status}  sources={sources}")
    except Exception as exc:
        _err(f"queue-run failed: {exc}")
        failures.append(f"Step 2 (queue-run): {exc}")
        print(f"\n{'='*62}")
        print(f"  FAILED — {len(failures)} assertion(s) failed")
        print(f"{'='*62}\n")
        sys.exit(1)

    # ── Step 3: Poll until terminal status ──────────────────────────
    _log(f"Step 3: Polling run #{run_id} (max {timeout}s) …")
    try:
        run = poll_run(url, key, run_id, timeout)
        status = run.get("status")
        _log(f"  ✓ Run #{run_id} finished  status={status}")
        if status == "failed":
            _log(f"  ⚠ Run status=failed — pipeline errors present")
        elif status == "cancelled":
            _log(f"  ⚠ Run status=cancelled")
    except TimeoutError as exc:
        _err(str(exc))
        failures.append(f"Step 3 (poll): {exc}")
        print(f"\n{'='*62}")
        print(f"  FAILED — run did not complete within {timeout}s")
        print(f"{'='*62}\n")
        sys.exit(1)
    except Exception as exc:
        _err(f"Poll failed: {exc}")
        failures.append(f"Step 3 (poll): {exc}")
        print(f"\n{'='*62}")
        print(f"  FAILED — {len(failures)} assertion(s) failed")
        print(f"{'='*62}\n")
        sys.exit(1)

    # ── Step 4: Task grid + ASSERTION 1 ─────────────────────────────
    _log(f"Step 4: GET /admin/runs/{run_id}/tasks  (assertion: ≥1 success) …")
    assertion1_pass = False
    try:
        tasks_data = get_run_tasks(url, key, run_id)
        tasks = tasks_data.get("tasks", [])

        print(f"\n  {'Source':<10} {'Date':<12} {'Status':<10} {'Saved'}")
        print(f"  {'-'*46}")
        for t in tasks:
            icon = {"success": "✓", "failed": "✗", "running": "●", "pending": "○"}.get(t["status"], "?")
            saved = t.get("articles_saved")
            saved_str = str(saved) if saved is not None else "—"
            print(f"  {t['source']:<10} {t['date']:<12} {icon} {t['status']:<8} {saved_str}")
        print()

        successful_tasks = [t for t in tasks if t["status"] == "success"]
        total_saved_across_tasks = sum(
            (t.get("articles_saved") or 0) for t in tasks if t.get("articles_saved") is not None
        )
        if successful_tasks:
            assertion1_pass = True
            _log(f"  ✓ ASSERTION 1 PASS — {len(successful_tasks)} task(s) succeeded, "
                 f"{total_saved_across_tasks} article(s) saved to DB")
        else:
            _err(f"ASSERTION 1 FAIL — no tasks with status=success (all failed or no tasks)")
            for t in tasks:
                if t.get("error_message"):
                    _err(f"  task {t['source']}@{t['date']}: {t['error_message'][:200]}")
            failures.append("Assertion 1: no successful task found — /internal/fetch-source failed")
    except Exception as exc:
        _err(f"get-run-tasks failed: {exc}")
        failures.append(f"Step 4 (tasks): {exc}")

    # ── Step 5: Article visibility + ASSERTION 2 ────────────────────
    _log(f"Step 5: GET /articles?digest_date={date_str}  (assertion: articles visible) …")
    assertion2_pass = False
    try:
        articles = get_articles(url, date_str)
        count = len(articles)
        if count > 0:
            assertion2_pass = True
            _log(f"  ✓ ASSERTION 2 PASS — {count} article(s) visible for {date_str}")
            if count >= 3:
                _log(f"  Sample titles:")
                for a in articles[:3]:
                    title = a.get("title", "(no title)")[:80]
                    _log(f"    • {title}")
        else:
            _err(f"ASSERTION 2 FAIL — 0 articles returned for digest_date={date_str}")
            failures.append(f"Assertion 2: GET /articles?digest_date={date_str} returned 0 articles")
    except Exception as exc:
        _err(f"get-articles failed: {exc}")
        failures.append(f"Step 5 (articles): {exc}")

    # ── Step 6: Diagnose if A1 passes but A2 fails ──────────────────
    if assertion1_pass and not assertion2_pass:
        _log("Step 6: Assertion 1 passed but Assertion 2 failed — running enrichment diagnosis …")
        diagnose_enrichment(url, key, date_str)

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    if not failures:
        print(f"  ✓ SMOKE TEST PASSED — pipeline E2E verified for {date_str}")
        print(f"  Cloud Tasks → /internal/fetch-source → Cloud SQL → GET /articles")
    else:
        print(f"  ✗ SMOKE TEST FAILED — {len(failures)} assertion(s) failed:")
        for f in failures:
            print(f"    • {f}")
    print(f"{'='*62}\n")

    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
