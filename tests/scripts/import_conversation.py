#!/usr/bin/env python3
"""
Import a conversation CSV into Cortexa via POST /v1/messages.

Usage:
    python3 tests/scripts/import_conversation.py <path>

Where <path> is one of:
    tests/data/<tenant-id>/<user-id>/<session-id>.csv   — single session
    tests/data/<tenant-id>/<user-id>/                   — all sessions for a user
    tests/data/<tenant-id>/                             — all users under a tenant

The tenant-id, user-id and session-id are inferred from the directory structure.
The session-id is the CSV filename without the .csv extension.

Options:
    --delay MS      Milliseconds to wait between messages (default: 0)
    --dry-run       Print what would be sent without calling the API
    --base-url URL  API base URL (default: http://localhost:8080/v1)

Examples:
    python3 tests/scripts/import_conversation.py tests/data/a1b2c3d4.../b1000001.../c1100001....csv
    python3 tests/scripts/import_conversation.py tests/data/a1b2c3d4.../b1000001.../
    python3 tests/scripts/import_conversation.py tests/data/a1b2c3d4.../
    python3 tests/scripts/import_conversation.py tests/data/a1b2c3d4.../ --delay 200 --dry-run
"""

import argparse
import csv
import sys
import time
import pathlib
import requests

BASE_URL = "http://localhost:8080/v1"


def resolve_files(path: pathlib.Path) -> list[tuple[str, str, str, pathlib.Path]]:
    """
    Return list of (tenant_id, user_id, session_id, csv_path) tuples.
    Accepts a .csv file, a user directory, or a tenant directory.
    """
    path = path.resolve()

    # Collect all csv files under the path
    if path.is_file() and path.suffix == ".csv":
        csv_files = [path]
    elif path.is_dir():
        csv_files = sorted(path.rglob("*.csv"))
    else:
        print(f"ERROR: '{path}' is not a .csv file or directory", file=sys.stderr)
        sys.exit(1)

    if not csv_files:
        print(f"ERROR: no .csv files found under '{path}'", file=sys.stderr)
        sys.exit(1)

    results = []
    for f in csv_files:
        # Expect structure: .../<tenant>/<user>/<session>.csv
        parts = f.parts
        if len(parts) < 3:
            print(f"WARNING: skipping '{f}' — cannot infer tenant/user/session from path")
            continue
        session_id = f.stem
        user_id    = parts[-2]
        tenant_id  = parts[-3]
        results.append((tenant_id, user_id, session_id, f))

    return results


def load_csv(csv_path: pathlib.Path) -> list[tuple[str, str]]:
    """Return list of (role, content) from a CSV file."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "role" not in reader.fieldnames or "content" not in reader.fieldnames:
            raise ValueError(f"'{csv_path}' must have 'role' and 'content' columns")
        for row in reader:
            role = row["role"].strip()
            content = row["content"].strip()
            if role and content:
                rows.append((role, content))
    return rows


def send_message(session: requests.Session, base_url: str,
                 tenant_id: str, user_id: str, session_id: str,
                 role: str, content: str) -> tuple[bool, str]:
    payload = {
        "tenant_id":  tenant_id,
        "user_id":    user_id,
        "session_id": session_id,
        "role":       role,
        "content":    content,
    }
    try:
        resp = session.post(f"{base_url}/messages", json=payload, timeout=15)
        if resp.status_code == 200:
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def import_file(http: requests.Session, base_url: str,
                tenant_id: str, user_id: str, session_id: str,
                csv_path: pathlib.Path, delay_ms: int, dry_run: bool) -> tuple[int, int]:
    """Import a single CSV. Returns (ok_count, fail_count)."""
    rows = load_csv(csv_path)
    ok = fail = 0

    print(f"\n  tenant={tenant_id}")
    print(f"  user  ={user_id}")
    print(f"  session={session_id}  ({len(rows)} messages)")

    for i, (role, content) in enumerate(rows, 1):
        preview = content[:60].replace("\n", " ")
        if dry_run:
            print(f"    [{i:>3}] {role:<9} {preview}...")
            ok += 1
            continue

        success, err = send_message(http, base_url, tenant_id, user_id, session_id, role, content)
        if success:
            print(f"    [{i:>3}] {role:<9} OK  — {preview}")
            ok += 1
        else:
            print(f"    [{i:>3}] {role:<9} FAIL — {err}")
            fail += 1

        if delay_ms > 0 and i < len(rows):
            time.sleep(delay_ms / 1000)

    return ok, fail


def main():
    parser = argparse.ArgumentParser(
        description="Import conversation CSV(s) into Cortexa."
    )
    parser.add_argument("path", help="CSV file, user dir, or tenant dir under tests/data/")
    parser.add_argument("--delay",    type=int, default=0,      metavar="MS",
                        help="ms to wait between messages (default: 0)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="print what would be sent without calling the API")
    parser.add_argument("--base-url", default=BASE_URL,
                        help=f"API base URL (default: {BASE_URL})")
    args = parser.parse_args()

    files = resolve_files(pathlib.Path(args.path))
    print(f"Found {len(files)} CSV file(s) to import")
    if args.dry_run:
        print("(dry-run mode — no API calls will be made)")

    http = requests.Session()
    http.headers.update({"Content-Type": "application/json"})

    total_ok = total_fail = 0
    for tenant_id, user_id, session_id, csv_path in files:
        ok, fail = import_file(
            http, args.base_url,
            tenant_id, user_id, session_id,
            csv_path, args.delay, args.dry_run,
        )
        total_ok   += ok
        total_fail += fail

    print(f"\n{'='*50}")
    print(f"Done.  sent={total_ok}  failed={total_fail}")
    if total_fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
