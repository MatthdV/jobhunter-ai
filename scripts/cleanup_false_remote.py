#!/usr/bin/env python3
"""One-shot cleanup: fix legacy jobs wrongly flagged is_remote=True.

Jobs scanned before the 2026-07-15 remote-filter fix could be flagged
remote because the old keyword heuristic matched "télétravail" inside
"télétravail hybride" (or "remote" inside "no remote" / "hybrid remote").

This script re-evaluates every is_remote=1 job against the hybrid markers
and, for confirmed false positives:
  - sets is_remote=0
  - moves NEW/MATCHED jobs to SKIPPED (already-applied jobs are left alone)

Usage (dry-run by default):
    python scripts/cleanup_false_remote.py            # report only
    python scripts/cleanup_false_remote.py --apply    # write changes

On the VPS:
    docker exec jobhunter-web python scripts/cleanup_false_remote.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

HYBRID_MARKERS = (
    "hybrid",
    "hybride",
    "télétravail partiel",
    "télétravail hybride",
    "partial remote",
    "partially remote",
    "no remote",
    "not remote",
    "pas de télétravail",
    "pas de remote",
    "sur site",
    "présentiel",
)

FULL_REMOTE_MARKERS = (
    "full remote",
    "fully remote",
    "100% remote",
    "100 % remote",
    "remote-first",
    "télétravail complet",
    "télétravail total",
    "100% télétravail",
)


def find_db() -> Path:
    candidates = [
        Path("/data/db/jobhunter.db"),  # VPS docker volume
        Path("/app/data/jobhunter.db"),
        Path("jobhunter.db"),
        Path("data/jobhunter.db"),
    ]
    # Fallback: any .db file in the docker volume mount
    db_dir = Path("/data/db")
    if db_dir.is_dir():
        candidates.extend(sorted(db_dir.glob("*.db")))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    sys.exit("jobhunter.db not found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = parser.parse_args()

    db_path = find_db()
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, title, status, COALESCE(description,''), COALESCE(location,'') "
        "FROM jobs WHERE is_remote = 1"
    ).fetchall()

    false_positives = []
    for job_id, title, status, description, location in rows:
        text = f"{title} {location} {description}".lower()
        # A hybrid marker with no explicit full-remote phrase = false positive
        if any(m in text for m in HYBRID_MARKERS) and not any(m in text for m in FULL_REMOTE_MARKERS):
            false_positives.append((job_id, title, status))

    if not false_positives:
        print(f"{len(rows)} remote jobs checked in {db_path} — no false positives.")
        return

    print(f"{len(false_positives)} false-remote job(s) out of {len(rows)} (db: {db_path}):")
    for job_id, title, status in false_positives:
        new_status = "SKIPPED" if status in ("NEW", "MATCHED") else status
        marker = "" if new_status == status else f" → {new_status}"
        print(f"  #{job_id} [{status}{marker}] {title}")

    if not args.apply:
        print("\nDry-run. Re-run with --apply to write changes.")
        return

    ids = [job_id for job_id, _, _ in false_positives]
    ph = ",".join("?" * len(ids))
    conn.execute(f"UPDATE jobs SET is_remote = 0 WHERE id IN ({ph})", ids)
    conn.execute(
        f"UPDATE jobs SET status = 'SKIPPED' WHERE id IN ({ph}) AND status IN ('NEW','MATCHED')",
        ids,
    )
    conn.commit()
    print(f"\nApplied: {len(ids)} job(s) updated.")


if __name__ == "__main__":
    main()
