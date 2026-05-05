#!/usr/bin/env python3
"""
reset_db.py — Truncate all Cortexa tables for a clean test environment.

Usage:
    python3 tests/scripts/reset_db.py                    # truncate all tables
    python3 tests/scripts/reset_db.py --tenant <UUID>    # delete one tenant only
    python3 tests/scripts/reset_db.py --user <UUID>      # delete one user only

Options:
    --tenant UUID   Delete all rows where tenant_id = UUID
    --user   UUID   Delete all rows where user_id = UUID (across all tenants)
    --yes           Skip confirmation prompt

Requires: psycopg2-binary  (pip install psycopg2-binary)
DB connection is read from cortexa/.env → DATABASE_URL, or from PGURL env var.
"""

import argparse
import os
import sys
from pathlib import Path

# ── Load DATABASE_URL from cortexa/.env ───────────────────────────────────────
for _ep in ["cortexa/.env", "../cortexa/.env"]:
    if Path(_ep).exists():
        for _ln in Path(_ep).read_text().splitlines():
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                k, _, v = _ln.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        break

DATABASE_URL = os.environ.get("PGURL") or os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found. Set it in cortexa/.env or via PGURL env var.")
    sys.exit(1)

# Remap docker-internal host → localhost for running outside the container
DATABASE_URL = DATABASE_URL.replace("@postgres:", "@localhost:")

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# Tables in dependency order (children first so FK constraints aren't violated)
ALL_TABLES = [
    "entity_mentions",
    "experiences",
    "llm_usage",
    "memory_records",
    "messages",
    "sessions",
]

# Columns that carry tenant_id / user_id (all tables have both)
TENANT_COL = "tenant_id"
USER_COL   = "user_id"


def confirm(prompt: str) -> bool:
    ans = input(f"{prompt} [y/N] ").strip().lower()
    return ans in ("y", "yes")


def truncate_all(cur, yes: bool):
    if not yes:
        print(f"This will TRUNCATE all rows from: {', '.join(ALL_TABLES)}")
        if not confirm("Continue?"):
            print("Aborted.")
            sys.exit(0)
    # TRUNCATE with RESTART IDENTITY resets sequences; CASCADE handles FK refs
    tables_sql = ", ".join(ALL_TABLES)
    cur.execute(f"TRUNCATE {tables_sql} RESTART IDENTITY CASCADE")
    print(f"Truncated: {tables_sql}")


def delete_tenant(cur, tenant_id: str, yes: bool):
    if not yes:
        print(f"This will DELETE all rows for tenant_id = {tenant_id}")
        if not confirm("Continue?"):
            print("Aborted.")
            sys.exit(0)
    for table in ALL_TABLES:
        cur.execute(f"DELETE FROM {table} WHERE {TENANT_COL} = %s", (tenant_id,))
        print(f"  {table}: {cur.rowcount} rows deleted")


def delete_user(cur, user_id: str, yes: bool):
    if not yes:
        print(f"This will DELETE all rows for user_id = {user_id}")
        if not confirm("Continue?"):
            print("Aborted.")
            sys.exit(0)
    for table in ALL_TABLES:
        cur.execute(f"DELETE FROM {table} WHERE {USER_COL} = %s", (user_id,))
        print(f"  {table}: {cur.rowcount} rows deleted")


def main():
    ap = argparse.ArgumentParser(description="Reset Cortexa DB data")
    ap.add_argument("--tenant", metavar="UUID", help="Delete one tenant's data")
    ap.add_argument("--user",   metavar="UUID", help="Delete one user's data")
    ap.add_argument("--yes",    action="store_true", help="Skip confirmation")
    args = ap.parse_args()

    # Validate UUIDs if provided
    import uuid as _uuid
    for flag, val in (("--tenant", args.tenant), ("--user", args.user)):
        if val:
            try:
                _uuid.UUID(val)
            except ValueError:
                print(f"ERROR: {flag} value '{val}' is not a valid UUID")
                sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if args.tenant:
                delete_tenant(cur, args.tenant, args.yes)
            elif args.user:
                delete_user(cur, args.user, args.yes)
            else:
                truncate_all(cur, args.yes)
        conn.commit()
        print("Done.")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()

    # Flush Redis so cached recent-messages don't resurrect deleted data.
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6380/0")
    try:
        import redis as _redis
        r = _redis.from_url(redis_url)
        r.flushall()
        print("Redis: FLUSHALL done")
    except Exception as e:
        print(f"Redis: skipped ({e})")


if __name__ == "__main__":
    main()
